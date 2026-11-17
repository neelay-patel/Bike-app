import CoreLocation
import Foundation
import HealthKit

/// Reads cycling workouts from Apple Health and turns each into a `RecordingPayload`.
///
/// Scope (agreed with Neelay; CLAUDE.md): cycling workouts, their routes, and the heart rate, active
/// energy, cycling distance, power, cadence and speed recorded during them (power, cadence and speed
/// come from a sensor paired with the Watch, e.g. a smart trainer; added 17 Nov 2026); heart rate in the 3 minutes after each ride
/// (recovery); and VO2 max, HRV, resting heart rate and Cardio Recovery. Nothing else is requested or read.
final class HealthKitReader {
    let store = HKHealthStore()

    static let heartRate = HKQuantityType(.heartRate)
    static let activeEnergy = HKQuantityType(.activeEnergyBurned)
    static let cyclingDistance = HKQuantityType(.distanceCycling)

    /// Sensor channels recorded during a ride: (HealthKit type, unit, where the value goes).
    static let sensorTypes: [(type: HKQuantityType, unit: HKUnit, field: WritableKeyPath<SamplePayload, Double?>)] = [
        (HKQuantityType(.cyclingPower), .watt(), \.power),
        (HKQuantityType(.cyclingCadence), HKUnit.count().unitDivided(by: .minute()), \.cadence),
        (HKQuantityType(.cyclingSpeed), HKUnit.meter().unitDivided(by: .second()), \.speed),
    ]
    static let cyclingPower = HKQuantityType(.cyclingPower)

    /// Recovery and fitness readings: (HealthKit type, rideengine kind, unit).
    static let metricTypes: [(type: HKQuantityType, kind: String, unit: HKUnit)] = [
        (HKQuantityType(.vo2Max), "vo2max", HKUnit(from: "ml/kg*min")),
        (HKQuantityType(.heartRateVariabilitySDNN), "hrv_sdnn", .secondUnit(with: .milli)),
        (HKQuantityType(.restingHeartRate), "resting_hr", HKUnit.count().unitDivided(by: .minute())),
        (HKQuantityType(.heartRateRecoveryOneMinute), "hr_recovery_1min", HKUnit.count().unitDivided(by: .minute())),
    ]

    static let afterRideSeconds: TimeInterval = 180

    static var readTypes: Set<HKObjectType> {
        Set([HKObjectType.workoutType(), HKSeriesType.workoutRoute(), heartRate, activeEnergy, cyclingDistance]
            + sensorTypes.map { $0.type as HKObjectType }
            + metricTypes.map { $0.type as HKObjectType })
    }

    static let cyclingPredicate = HKQuery.predicateForWorkouts(with: .cycling)

    var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    func requestAuthorization() async throws {
        try await store.requestAuthorization(toShare: [], read: Self.readTypes)
    }

    /// True when there are types the rider hasn't been asked about yet (e.g. the recovery types,
    /// added after they first connected).
    func needsToAsk() async -> Bool {
        (try? await store.statusForAuthorizationRequest(toShare: [], read: Self.readTypes)) == .shouldRequest
    }

    // MARK: Finding workouts

    /// Cycling workouts that ended on or after `since`, newest first.
    func cyclingWorkouts(since: Date?) async throws -> [HKWorkout] {
        var predicate: NSPredicate = Self.cyclingPredicate
        if let since {
            let window = HKQuery.predicateForSamples(withStart: since, end: nil, options: [])
            predicate = NSCompoundPredicate(andPredicateWithSubpredicates: [predicate, window])
        }
        let query = HKSampleQueryDescriptor(predicates: [.workout(predicate)],
                                            sortDescriptors: [SortDescriptor(\.endDate, order: .reverse)])
        return try await query.result(for: store)
    }

    /// Cycling workouts added since `anchor` (nil: all of them), and the anchor to use next time.
    func newCyclingWorkouts(after anchor: HKQueryAnchor?) async throws -> ([HKWorkout], HKQueryAnchor) {
        let query = HKAnchoredObjectQueryDescriptor(predicates: [.workout(Self.cyclingPredicate)], anchor: anchor)
        let result = try await query.result(for: store)
        return (result.addedSamples, result.newAnchor)
    }

    // MARK: Building a recording

    /// The rideengine source key for whoever wrote the workout, or nil for sources we don't take
    /// (e.g. Strava, whose data we never use).
    static func sourceKey(for workout: HKWorkout) -> String? {
        sourceKey(for: workout.sourceRevision)
    }

    static func sourceKey(for revision: HKSourceRevision) -> String? {
        let product = revision.productType ?? ""
        let bundle = revision.source.bundleIdentifier.lowercased()
        if bundle.contains("strava") { return nil }
        if bundle.contains("whoop") { return "whoop" }
        if bundle.contains("oura") { return "oura" }
        if bundle.contains("fitbit") { return "fitbit" }
        if bundle.contains("garmin") { return "garmin" }
        if bundle.contains("wahoo") { return "wahoo" }
        if bundle.contains("hammerhead") { return "hammerhead" }
        if product.hasPrefix("Watch") { return "apple_watch" }
        if bundle.hasPrefix("com.apple.health") { return product.hasPrefix("iPhone") ? "iphone" : "apple_watch" }
        return nil
    }

    func recording(for workout: HKWorkout) async throws -> RecordingPayload? {
        guard let source = Self.sourceKey(for: workout) else { return nil }
        var samples = try await routeSamples(for: workout)
        let hasRoute = !samples.isEmpty
        samples += try await heartRateSamples(for: workout)
        for sensor in Self.sensorTypes {
            // Outdoors the route already gives speed; a sensor's speed is only used indoors.
            if sensor.field == \SamplePayload.speed && hasRoute { continue }
            samples += try await sensorSamples(sensor, for: workout)
        }
        samples.sort { $0.t < $1.t }
        let after = try await heartRateSamples(for: workout, from: workout.endDate,
                                               to: workout.endDate.addingTimeInterval(Self.afterRideSeconds))

        let product = workout.sourceRevision.productType
        let device = source == "apple_watch" ? "Apple Watch" + (product.map { " (\($0))" } ?? "")
            : workout.sourceRevision.source.name
        return RecordingPayload(
            source: source, device: device,
            start: workout.startDate.timeIntervalSince1970, end: workout.endDate.timeIntervalSince1970,
            indoor: (workout.metadata?[HKMetadataKeyIndoorWorkout] as? NSNumber)?.boolValue ?? false,
            origin: "healthkit:\(workout.uuid.uuidString)",
            totals: Self.totals(for: workout), samples: samples, after: after.isEmpty ? nil : after)
    }

    static func totals(for workout: HKWorkout) -> [String: Double] {
        var totals: [String: Double] = ["elapsed_s": workout.duration]
        let bpm = HKUnit.count().unitDivided(by: .minute())
        if let kcal = workout.statistics(for: activeEnergy)?.sumQuantity()?.doubleValue(for: .kilocalorie()) {
            totals["calories"] = kcal
        }
        if let m = workout.statistics(for: cyclingDistance)?.sumQuantity()?.doubleValue(for: .meter()) {
            totals["distance_m"] = m
        }
        let hr = workout.statistics(for: heartRate)
        if let avg = hr?.averageQuantity()?.doubleValue(for: bpm) { totals["avg_hr"] = avg }
        if let max = hr?.maximumQuantity()?.doubleValue(for: bpm) { totals["max_hr"] = max }
        if let ascent = workout.metadata?[HKMetadataKeyElevationAscended] as? HKQuantity {
            totals["ascent_m"] = ascent.doubleValue(for: .meter())
        }
        return totals
    }

    /// GPS points of the workout's route(s): position, altitude, speed.
    func routeSamples(for workout: HKWorkout) async throws -> [SamplePayload] {
        let routesQuery = HKSampleQueryDescriptor(
            predicates: [.sample(type: HKSeriesType.workoutRoute(), predicate: HKQuery.predicateForObjects(from: workout))],
            sortDescriptors: [SortDescriptor(\.startDate)])
        let routes = try await routesQuery.result(for: store).compactMap { $0 as? HKWorkoutRoute }
        var out: [SamplePayload] = []
        for route in routes {
            for try await loc in HKWorkoutRouteQueryDescriptor(route).results(for: store) {
                out.append(SamplePayload(
                    t: loc.timestamp.timeIntervalSince1970,
                    lat: loc.coordinate.latitude, lon: loc.coordinate.longitude,
                    ele: loc.verticalAccuracy >= 0 ? loc.altitude : nil,
                    speed: loc.speed >= 0 ? loc.speed : nil))
            }
        }
        return out
    }

    /// Every heart-rate reading the workout's own device took during the workout (or, with
    /// `from`/`to`, in that window: the minutes after the ride, for recovery).
    func heartRateSamples(for workout: HKWorkout, from: Date? = nil, to: Date? = nil) async throws -> [SamplePayload] {
        let during = HKQuery.predicateForSamples(withStart: from ?? workout.startDate, end: to ?? workout.endDate,
                                                 options: .strictStartDate)
        let sameDevice = HKQuery.predicateForObjects(from: workout.sourceRevision.source)
        let predicate = NSCompoundPredicate(andPredicateWithSubpredicates: [during, sameDevice])
        let query = HKQuantitySeriesSampleQueryDescriptor(
            predicate: .quantitySample(type: Self.heartRate, predicate: predicate))
        let bpm = HKUnit.count().unitDivided(by: .minute())
        var out: [SamplePayload] = []
        for try await result in query.results(for: store) {
            out.append(SamplePayload(t: result.dateInterval.start.timeIntervalSince1970,
                                     hr: result.quantity.doubleValue(for: bpm)))
        }
        return out
    }

    /// Readings from a sensor paired with the workout's device (power meter, smart trainer,
    /// cadence or speed sensor), during the workout only.
    func sensorSamples(_ sensor: (type: HKQuantityType, unit: HKUnit, field: WritableKeyPath<SamplePayload, Double?>),
                       for workout: HKWorkout) async throws -> [SamplePayload] {
        let query = HKQuantitySeriesSampleQueryDescriptor(
            predicate: .quantitySample(type: sensor.type, predicate: await duringWorkout(workout, sensor.type)))
        var out: [SamplePayload] = []
        for try await result in query.results(for: store) {
            var sample = SamplePayload(t: result.dateInterval.start.timeIntervalSince1970)
            sample[keyPath: sensor.field] = result.quantity.doubleValue(for: sensor.unit)
            out.append(sample)
        }
        return out
    }

    /// True when the workout has power readings (used to re-send rides once power can be read).
    func hasPower(_ workout: HKWorkout) async -> Bool {
        let query = HKSampleQueryDescriptor(predicates: [.quantitySample(type: Self.cyclingPower,
                                                                         predicate: await duringWorkout(workout, Self.cyclingPower))],
                                            sortDescriptors: [], limit: 1)
        return ((try? await query.result(for: store)) ?? []).isEmpty == false
    }

    /// Names of the apps or devices that wrote power readings during the workout, whoever they are
    /// (to tell the rider where their power is when it didn't come from the workout's own device).
    func powerSourceNames(_ workout: HKWorkout) async -> Set<String> {
        let window = HKQuery.predicateForSamples(withStart: workout.startDate, end: workout.endDate, options: [])
        let query = HKSampleQueryDescriptor(predicates: [.quantitySample(type: Self.cyclingPower, predicate: window)],
                                            sortDescriptors: [], limit: 50)
        return Set(((try? await query.result(for: store)) ?? []).map { $0.sourceRevision.source.name })
    }

    /// Sensor readings come from the workout's own device, or from the sensor Apple paired with it:
    /// the Watch files a trainer's or power meter's readings under a separate Apple source
    /// ("Bluetooth Device"). Other apps' readings (Zwift, Wahoo) belong to their own recordings.
    private func duringWorkout(_ workout: HKWorkout, _ type: HKQuantityType) async -> NSPredicate {
        let own = workout.sourceRevision.source
        let all = (try? await HKSourceQueryDescriptor(predicate: .quantitySample(type: type)).result(for: store)) ?? []
        let sources = Set(all.filter { $0.bundleIdentifier.hasPrefix("com.apple.") }).union([own])
        return NSCompoundPredicate(andPredicateWithSubpredicates: [
            HKQuery.predicateForSamples(withStart: workout.startDate, end: workout.endDate, options: .strictStartDate),
            HKQuery.predicateForObjects(from: sources)])
    }

    // MARK: Recovery and fitness readings

    /// Readings of one kind that Health added since `anchor` (nil: everything since `since`), and
    /// the anchor to use next time. Readings from sources we don't take (e.g. Strava) are left out.
    func newMetrics(_ metric: (type: HKQuantityType, kind: String, unit: HKUnit), after anchor: HKQueryAnchor?,
                    since: Date) async throws -> ([MetricPayload], HKQueryAnchor) {
        let window = HKQuery.predicateForSamples(withStart: since, end: nil, options: [])
        let query = HKAnchoredObjectQueryDescriptor(predicates: [.quantitySample(type: metric.type, predicate: window)],
                                                    anchor: anchor)
        let result = try await query.result(for: store)
        let out = result.addedSamples.compactMap { s -> MetricPayload? in
            guard let source = Self.sourceKey(for: s.sourceRevision) else { return nil }
            return MetricPayload(id: s.uuid.uuidString, kind: metric.kind, t: s.startDate.timeIntervalSince1970,
                                 value: s.quantity.doubleValue(for: metric.unit), source: source)
        }
        return (out, result.newAnchor)
    }
}

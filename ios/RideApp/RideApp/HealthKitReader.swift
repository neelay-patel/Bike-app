import CoreLocation
import Foundation
import HealthKit

/// Reads cycling workouts from Apple Health and turns each into a `RecordingPayload`.
///
/// Scope (agreed with Neelay): cycling workouts, their routes, and the heart rate, active energy
/// and cycling distance recorded during them. Nothing else is requested or read.
final class HealthKitReader {
    let store = HKHealthStore()

    static let heartRate = HKQuantityType(.heartRate)
    static let activeEnergy = HKQuantityType(.activeEnergyBurned)
    static let cyclingDistance = HKQuantityType(.distanceCycling)

    static var readTypes: Set<HKObjectType> {
        [HKObjectType.workoutType(), HKSeriesType.workoutRoute(), heartRate, activeEnergy, cyclingDistance]
    }

    static let cyclingPredicate = HKQuery.predicateForWorkouts(with: .cycling)

    var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    func requestAuthorization() async throws {
        try await store.requestAuthorization(toShare: [], read: Self.readTypes)
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
        let revision = workout.sourceRevision
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
        samples += try await heartRateSamples(for: workout)
        samples.sort { $0.t < $1.t }

        let product = workout.sourceRevision.productType
        let device = source == "apple_watch" ? "Apple Watch" + (product.map { " (\($0))" } ?? "")
            : workout.sourceRevision.source.name
        return RecordingPayload(
            source: source, device: device,
            start: workout.startDate.timeIntervalSince1970, end: workout.endDate.timeIntervalSince1970,
            indoor: (workout.metadata?[HKMetadataKeyIndoorWorkout] as? NSNumber)?.boolValue ?? false,
            origin: "healthkit:\(workout.uuid.uuidString)",
            totals: Self.totals(for: workout), samples: samples)
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

    /// Every heart-rate reading the workout's own device took during the workout.
    func heartRateSamples(for workout: HKWorkout) async throws -> [SamplePayload] {
        let during = HKQuery.predicateForSamples(withStart: workout.startDate, end: workout.endDate,
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
}

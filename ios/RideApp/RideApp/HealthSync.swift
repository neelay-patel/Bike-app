import Foundation
import HealthKit

/// The Apple Health connector: permission, history import, and background delivery of new rides.
///
/// New workouts are found with an anchored query, so each sync only looks at what Health added
/// since the last one. Uploaded workout ids are remembered, and the backend ignores repeats anyway.
@MainActor
final class HealthSync: ObservableObject {
    static let shared = HealthSync()

    @Published private(set) var isConnected = UserDefaults.standard.bool(forKey: Keys.connected)
    @Published private(set) var isWorking = false
    @Published private(set) var progress: (done: Int, total: Int)?
    @Published private(set) var lastMessage: String?

    let reader = HealthKitReader()
    private let api = APIClient()
    private var observer: HKObserverQuery?

    private enum Keys {
        static let connected = "health.connected"
        static let anchor = "health.anchor"
        static let uploaded = "health.uploaded"
    }

    // MARK: Connect / disconnect

    /// Ask for permission, start watching for new rides, then import history since `since`.
    func connect(importSince since: Date) async {
        guard reader.isAvailable else {
            lastMessage = "Apple Health isn't available on this device."
            return
        }
        do {
            try await reader.requestAuthorization()
            // Anchor first, so a ride saved while history imports is still picked up later.
            let (_, anchor) = try await reader.newCyclingWorkouts(after: nil)
            saveAnchor(anchor)
            isConnected = true
            UserDefaults.standard.set(true, forKey: Keys.connected)
            await startBackgroundDelivery()
            await importHistory(since: since)
        } catch {
            lastMessage = "Couldn't connect Apple Health: \(error.localizedDescription)"
        }
    }

    func disconnect() async {
        if let observer { reader.store.stop(observer) }
        observer = nil
        try? await reader.store.disableAllBackgroundDelivery()
        isConnected = false
        for key in [Keys.connected, Keys.anchor, Keys.uploaded] { UserDefaults.standard.removeObject(forKey: key) }
        do {
            try await api.disconnect("apple_health")
            lastMessage = "Disconnected. Rides from Apple Health were deleted from the server."
        } catch {
            lastMessage = "Disconnected here, but the server didn't respond: \(error.localizedDescription)"
        }
    }

    // MARK: History

    func importHistory(since: Date) async {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false; progress = nil }
        do {
            let workouts = try await reader.cyclingWorkouts(since: since).filter { !isUploaded($0) }
            let (sent, failed) = await upload(workouts)
            lastMessage = failed == 0 ? "Imported \(sent) rides from Apple Health."
                : "Imported \(sent) rides; \(failed) failed. Tap Import history to retry them."
        } catch {
            lastMessage = "History import failed: \(error.localizedDescription)"
        }
    }

    // MARK: New rides (foreground or background)

    /// Upload cycling workouts Health added since the last sync. The anchor only moves on when
    /// every upload worked, so failures are retried next time.
    @discardableResult
    func syncNew() async -> Int {
        guard isConnected, !isWorking else { return 0 }
        isWorking = true
        defer { isWorking = false; progress = nil }
        do {
            let (added, anchor) = try await reader.newCyclingWorkouts(after: loadAnchor())
            let (sent, failed) = await upload(added.filter { !isUploaded($0) })
            if failed == 0 { saveAnchor(anchor) }
            if sent > 0 { lastMessage = "Sent \(sent) new ride\(sent == 1 ? "" : "s")." }
            return sent
        } catch {
            lastMessage = "Sync failed: \(error.localizedDescription)"
            return 0
        }
    }

    /// Call at every launch (background launches included): HealthKit wakes the app for new
    /// workouts only while an observer query is registered.
    func startBackgroundDelivery() async {
        guard isConnected, observer == nil else { return }
        let query = HKObserverQuery(sampleType: HKObjectType.workoutType(),
                                    predicate: HealthKitReader.cyclingPredicate) { _, completion, error in
            guard error == nil else { completion(); return }
            Task { @MainActor in
                await HealthSync.shared.syncNew()
                completion()
            }
        }
        reader.store.execute(query)
        observer = query
        do {
            try await reader.store.enableBackgroundDelivery(for: HKObjectType.workoutType(), frequency: .immediate)
        } catch {
            lastMessage = "Background delivery is off: \(error.localizedDescription)"
        }
    }

    // MARK: Uploading

    private func upload(_ workouts: [HKWorkout]) async -> (sent: Int, failed: Int) {
        var sent = 0, failed = 0
        progress = (0, workouts.count)
        for (i, workout) in workouts.enumerated() {
            do {
                if let recording = try await reader.recording(for: workout) {
                    _ = try await api.upload(recording)
                    sent += 1
                }
                markUploaded(workout)  // also marks sources we skip (e.g. Strava) so they aren't re-read
            } catch {
                failed += 1
            }
            progress = (i + 1, workouts.count)
        }
        return (sent, failed)
    }

    private func isUploaded(_ workout: HKWorkout) -> Bool {
        uploadedIDs.contains(workout.uuid.uuidString)
    }

    private func markUploaded(_ workout: HKWorkout) {
        var ids = uploadedIDs
        ids.insert(workout.uuid.uuidString)
        UserDefaults.standard.set(Array(ids), forKey: Keys.uploaded)
    }

    private var uploadedIDs: Set<String> {
        Set(UserDefaults.standard.stringArray(forKey: Keys.uploaded) ?? [])
    }

    private func saveAnchor(_ anchor: HKQueryAnchor) {
        if let data = try? NSKeyedArchiver.archivedData(withRootObject: anchor, requiringSecureCoding: true) {
            UserDefaults.standard.set(data, forKey: Keys.anchor)
        }
    }

    private func loadAnchor() -> HKQueryAnchor? {
        guard let data = UserDefaults.standard.data(forKey: Keys.anchor) else { return nil }
        return try? NSKeyedUnarchiver.unarchivedObject(ofClass: HKQueryAnchor.self, from: data)
    }
}

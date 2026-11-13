import SwiftUI

@main
struct RideApp: App {
    @StateObject private var model = AppModel()
    @StateObject private var health = HealthSync.shared

    init() {
        // HealthKit only wakes the app for new rides while an observer is registered, and that
        // has to happen at every launch, including the background launches HealthKit triggers.
        Task { @MainActor in
            await HealthSync.shared.startBackgroundDelivery()
            await HealthSync.shared.syncNew()
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .environmentObject(health)
        }
    }
}

/// Screen state that comes from the backend.
@MainActor
final class AppModel: ObservableObject {
    @Published var connections: [Connection] = []
    @Published var rides: [RideSummary] = []
    @Published var error: String?
    @Published var isLoading = false

    private let api = APIClient()

    func refresh() async {
        guard ServerConfig.isConfigured else {
            error = "Add the server address and token in Settings."
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            async let c = api.connections()
            async let r = api.rides()
            (connections, rides) = try await (c, r)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    func run(_ action: () async throws -> Void) async {
        do {
            try await action()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        await refresh()
    }
}

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        TabView {
            RidesView().tabItem { Label("Rides", systemImage: "bicycle") }
            ConnectionsView().tabItem { Label("Connections", systemImage: "link") }
            SettingsView().tabItem { Label("Settings", systemImage: "gearshape") }
        }
        .task { await model.refresh() }
    }
}

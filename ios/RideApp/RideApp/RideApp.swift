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
    @Published var you: YouSummary?
    @Published var recovery: RecoverySummary?
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
            let tz = TimeZone.current.identifier
            if UserDefaults.standard.string(forKey: "sentTimeZone") != tz, (try? await api.setTimeZone(tz)) != nil {
                UserDefaults.standard.set(tz, forKey: "sentTimeZone")
            }
            async let c = api.connections()
            async let r = api.rides()
            async let y = try? api.you()  // an older server has no /v1/you: the rest still loads
            async let rc = try? api.recovery()
            (connections, rides) = try await (c, r)
            you = await y
            recovery = await rc
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
            YouView().tabItem { Label("You", systemImage: "person.crop.circle") }
            ConnectionsView().tabItem { Label("Sources", systemImage: "link") }
            SettingsView().tabItem { Label("Settings", systemImage: "gearshape") }
        }
        .tint(Theme.cobalt)
        .font(Theme.text())
        .foregroundStyle(Theme.ink)
        .preferredColorScheme(.light)  // the D look is light-only for now; a dark variant comes later
        .task { await model.refresh() }
    }
}

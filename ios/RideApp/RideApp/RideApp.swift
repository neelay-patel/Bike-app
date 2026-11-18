import SwiftUI

@main
struct RideApp: App {
    @StateObject private var model = AppModel()
    @StateObject private var health = HealthSync.shared

    init() {
        #if DEBUG
        // Dev only: launch with RIDE_DEV_SERVER and RIDE_DEV_TOKEN in the environment to point the Simulator at a server.
        let env = ProcessInfo.processInfo.environment
        if let server = env["RIDE_DEV_SERVER"].flatMap(URL.init(string:)), let token = env["RIDE_DEV_TOKEN"] {
            ServerConfig.serverURL = server
            ServerConfig.token = token
        }
        #endif
        // HealthKit only wakes the app for new rides while an observer is registered, and that
        // has to happen at every launch, including the background launches HealthKit triggers.
        // (New rides are sent when the app opens: AppModel.catchUp.)
        Task { @MainActor in
            await HealthSync.shared.startBackgroundDelivery()
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
    @Published var goal: GoalView?
    @Published var plan: TrainingPlan?
    /// The rider's bike (from the avatar spec), remembered for the tab icon at launch.
    @Published var bike = BikeSpec.saved {
        didSet { if bike != oldValue { BikeSpec.saved = bike } }
    }
    @Published var error: String?
    @Published var isLoading = false

    private let api = APIClient()

    private var lastCatchUp: Date?

    /// When the app opens (launch, or back from the background): show what the server has now, then send
    /// new Watch rides from Apple Health and have the server check Garmin, and show those too. At most
    /// once a minute; pull to refresh still works any time.
    func catchUp() async {
        guard ServerConfig.isConfigured else { return await refresh() }
        if let last = lastCatchUp, Date().timeIntervalSince(last) < 60 { return }
        lastCatchUp = Date()
        await refresh()
        let fromWatch = await HealthSync.shared.syncNew()
        let fromGarmin = (try? await api.refreshSources()) ?? 0
        if fromWatch + fromGarmin > 0 { await refresh() }
    }

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
            async let g = try? api.currentGoal()
            async let pl = try? api.plan()
            async let me = try? api.me()
            (connections, rides) = try await (c, r)
            you = await y
            recovery = await rc
            goal = (await g) ?? nil
            plan = (await pl) ?? nil
            if let me = await me { bike = BikeSpec(avatar: me.avatar) }
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
    @Environment(\.scenePhase) private var scenePhase
    @State private var tab = 0

    var body: some View {
        TabView(selection: $tab) {
            // Your own bike: in its colours when you're on Efforts, an outline otherwise.
            RidesView().tabItem {
                Label { Text("Efforts") } icon: { Image(uiImage: BikeIcon.image(model.bike, selected: tab == 0)) }
            }.tag(0)
            PlanView().tabItem { Label("Plan", systemImage: "calendar") }.tag(1)
            RoutesView().tabItem { Label("Routes", systemImage: "point.topleft.down.to.point.bottomright.curvepath") }.tag(3)
            YouView().tabItem { Label("You", systemImage: "person.crop.circle") }.tag(2)
            ConnectionsView().tabItem { Label("Sources", systemImage: "link") }.tag(4)
        }
        .tint(Theme.cobalt)
        .font(Theme.text())
        .foregroundStyle(Theme.ink)
        .preferredColorScheme(.light)  // the D look is light-only for now; a dark variant comes later
        .task { await model.catchUp() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { Task { await model.catchUp() } }   // back from the background: new rides
        }
        .onOpenURL { url in
            // A GPX shared from Ride with GPS, Komoot or Files: check it in Routes.
            guard url.pathExtension.lowercased() == "gpx" else { return }
            tab = 3
            Task { await RouteInbox.shared.add(url) }
        }
        #if DEBUG
        .onAppear { BikeArtRender.runIfAsked() }
        #endif
    }
}

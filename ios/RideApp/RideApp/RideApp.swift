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
        // Dev only: RIDE_DEV_COACH_DEMO=<seconds> forgets the coach's ride and review messages, then after that
        // many seconds (move Kova to the background first) checks the inbox as a background wake-up would, so
        // they show as notifications.
        if let wait = env["RIDE_DEV_COACH_DEMO"].flatMap(Double.init) {
            Task { @MainActor in
                let bg = UIApplication.shared.beginBackgroundTask()
                try? await Task.sleep(for: .seconds(wait))
                let shown = (UserDefaults.standard.stringArray(forKey: "coach.shown") ?? [])
                    .filter { !$0.hasPrefix("ride:") && !$0.hasPrefix("review:") }
                UserDefaults.standard.set(shown, forKey: "coach.shown")
                await CoachNotifier.shared.refresh(appActive: false)
                UIApplication.shared.endBackgroundTask(bg)
            }
        }
        // Dev only: RIDE_DEV_SEEN_UNTIL (seconds since 1970) shows the efforts after it as new.
        if let seen = env["RIDE_DEV_SEEN_UNTIL"].flatMap(Double.init) {
            UserDefaults.standard.set(seen, forKey: "efforts.seenUntil")
        }
        #endif
        // HealthKit only wakes the app for new rides while an observer is registered, and that
        // has to happen at every launch, including the background launches HealthKit triggers.
        // (New rides are sent when the app opens: AppModel.catchUp.)
        Task { @MainActor in
            await HealthSync.shared.startBackgroundDelivery()
        }
        // The coach's notifications: taps reach the app, even one that launched it (CoachNotifications.swift).
        Task { @MainActor in CoachNotifier.shared.start() }
    }

    /// The opening screen (Kova's mark and meaning) over the app while it loads, once per launch.
    @State private var opening = true

    var body: some Scene {
        WindowGroup {
            ZStack {
                ContentView()
                    .environmentObject(model)
                    .environmentObject(health)
                if opening {
                    KovaOpening { opening = false }   // it fades itself out first, then goes
                        .zIndex(1)
                }
            }
        }
        // Now and then iOS wakes Kova in the background: check for the coach's messages.
        .backgroundTask(.appRefresh(CoachNotifier.refreshTask)) {
            await CoachNotifier.shared.refresh(appActive: false)
            await CoachNotifier.shared.scheduleBackgroundRefresh()
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
    /// The Train tab's today (GET /v1/train/today).
    @Published var today: TrainToday?
    /// Every effort's card (by year, holo for bests, gaps for missed weeks), the badges and the rider card's numbers.
    @Published var collection: CollectionSummary?
    /// The rider's bike (from the avatar spec), remembered for the tab icon at launch.
    @Published var bike = BikeSpec.saved {
        didSet { if bike != oldValue { BikeSpec.saved = bike } }
    }
    /// What to tell the rider about the connection to the server, if anything (StatusLine shows it).
    @Published var problem: Problem?
    /// When rides last loaded from the server: shown when it can't be reached.
    @Published var loadedAt: Date?
    /// Sending new Watch rides and asking the server to check Garmin.
    @Published var checking = false
    @Published var isLoading = false
    /// Kept for screens that only need to know something is wrong.
    var error: String? { problem?.text(loadedAt: loadedAt) }

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
        guard problem == nil else { return }       // can't reach the server: nothing to send now
        checking = true
        let fromWatch = await HealthSync.shared.syncNew()
        let fromGarmin = (try? await api.refreshSources()) ?? 0
        checking = false
        if fromWatch + fromGarmin > 0 { await refresh() }
        await CoachNotifier.shared.refresh(appActive: true)   // the app is open: mark the coach's news as seen
    }

    func refresh() async {
        guard ServerConfig.isConfigured else {
            problem = .setup
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
            async let td = try? api.trainToday()
            async let me = try? api.me()
            async let col = try? api.collection()
            (connections, rides) = try await (c, r)
            you = await y
            recovery = await rc
            goal = (await g) ?? nil
            plan = (await pl) ?? nil
            today = await td
            if let col = await col { collection = col }
            if let me = await me { bike = BikeSpec(avatar: me.avatar) }
            loadedAt = Date()
            problem = nil
        } catch {
            if let p = Problem(error) { problem = p }   // a cancelled load (the screen moved on) isn't a problem
        }
    }

    /// Something the rider did (delete a ride, sync now, rename...). If it fails, say what didn't happen.
    func run(_ what: String = "That didn't go through", _ action: () async throws -> Void) async {
        var failed: Problem?
        do {
            try await action()
        } catch {
            if let p = Problem(error) { failed = p.isConnection ? p : .action(what, error.localizedDescription) }
        }
        await refresh()
        if let failed, problem == nil { problem = failed }   // the refresh worked; still say what didn't
    }
}

/// What can go wrong talking to the server, in words that say what it means and what to do. A cancelled
/// request (the app moved on before it finished) isn't a problem and is never shown.
enum Problem: Equatable {
    case setup                       // no server or token yet
    case offline                     // can't reach the Mac (not on home Wi-Fi, or the server is off)
    case signIn                      // the server didn't accept the token
    case server(String)              // the server answered with an error
    case action(String, String)      // something the rider did didn't go through: what, why

    init?(_ error: Error) {
        if error is CancellationError { return nil }
        if let u = error as? URLError {
            switch u.code {
            case .cancelled: return nil
            case .notConnectedToInternet, .cannotConnectToHost, .cannotFindHost, .timedOut, .networkConnectionLost,
                 .dnsLookupFailed, .dataNotAllowed, .internationalRoamingOff, .secureConnectionFailed:
                self = .offline
            default: self = .server(u.localizedDescription)
            }
            return
        }
        if (error as NSError).domain == NSURLErrorDomain, (error as NSError).code == NSURLErrorCancelled { return nil }
        if let a = error as? APIError {
            if a.status == 401 { self = .signIn } else if a.status == nil && !ServerConfig.isConfigured { self = .setup }
            else { self = .server(a.message) }
            return
        }
        self = .server(error.localizedDescription)
    }

    var isConnection: Bool { self == .setup || self == .offline || self == .signIn }
    /// Not the rider's doing and not broken: just out of reach for now.
    var isQuiet: Bool { self == .offline }

    func text(loadedAt: Date?) -> String {
        switch self {
        case .setup:
            return "Add your server and token in Settings (Sources, then the gear) to see your efforts."
        case .offline:
            let when = loadedAt.map { " Showing what loaded at \($0.formatted(date: .omitted, time: .shortened))." } ?? ""
            return "Can't reach your server right now.\(when) New rides come in when you're back on your home Wi-Fi and the Mac is on."
        case .signIn:
            return "The server didn't accept your token. Paste a new one in Settings (Sources, then the gear)."
        case .server(let why):
            return "The server ran into a problem (\(why)). Pull down to try again."
        case .action(let what, let why):
            return "\(what): \(why)"
        }
    }
}

/// One line under a screen's title about the connection: checking for new rides, out of reach (grey, with
/// when things last loaded), or a real problem (red). Nothing when all is well.
struct StatusLine: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        if let p = model.problem {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: p.isQuiet ? "wifi.slash" : "exclamationmark.circle.fill")
                Text(p.text(loadedAt: model.loadedAt)).fixedSize(horizontal: false, vertical: true)
            }
            .font(Theme.text(13)).foregroundStyle(p.isQuiet ? Theme.inkMuted : Theme.heart)
            .padding(.horizontal, 4)
        } else if model.checking {
            HStack(spacing: 8) {
                ProgressView().controlSize(.mini)
                Text("Checking for new rides…")
            }
            .font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
            .padding(.horizontal, 4)
        }
    }
}

struct ContentView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var tab = 0
    /// How many times each tab has been opened: its cards arrive again, and its charts draw in again, each time.
    @State private var visits: [Int: Int] = [:]
    @ObservedObject private var coach = CoachNotifier.shared

    var body: some View {
        TabView(selection: $tab) {
            // Your own bike: in its colours when you're on Efforts, an outline otherwise.
            RidesView().tabItem {
                Label { Text("Efforts") } icon: { Image(uiImage: BikeIcon.image(model.bike, selected: tab == 0)) }
            }.tag(0).environment(\.tabVisit, visits[0] ?? 0)
            // Not a trainer or a road bike: indoors or out is the rider's choice (21 Nov 2026). Rising bars, like
            // the climb in Kova's mark.
            TrainView().tabItem { Label("Train", systemImage: "chart.bar.xaxis.ascending") }.tag(1)
                .environment(\.tabVisit, visits[1] ?? 0)
            RoutesView().tabItem { Label("Routes", systemImage: "point.topleft.down.to.point.bottomright.curvepath") }.tag(3)
                .environment(\.tabVisit, visits[3] ?? 0)
            YouView().tabItem { Label("You", systemImage: "person.crop.circle") }.tag(2)
                .environment(\.tabVisit, visits[2] ?? 0)
            ConnectionsView().tabItem { Label("Sources", systemImage: "link") }.tag(4)
                .environment(\.tabVisit, visits[4] ?? 0)
        }
        .onChange(of: tab) { _, t in visits[t, default: 0] += 1 }
        .tint(Theme.cobalt)
        .font(Theme.text())
        .foregroundStyle(Theme.ink)
        .preferredColorScheme(.light)  // the D look is light-only for now; a dark variant comes later
        .task { await model.catchUp() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { Task { await model.catchUp() } }   // back from the background: new rides
            if phase == .background { coach.scheduleBackgroundRefresh() }
        }
        .onChange(of: coach.route) { _, route in
            if route != nil { tab = 1 }                  // a tapped coach notification opens Train
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

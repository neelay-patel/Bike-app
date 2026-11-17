import Foundation
import Security

/// Where the backend is and how to log in to it.
/// Dev setup: server URL + the token from `python -m backend create-user`.
/// Sign in with Apple replaces the token once the paid developer account is in place.
enum ServerConfig {
    private static let urlKey = "serverURL"
    private static let tokenAccount = "backend-token"

    static var serverURL: URL? {
        get { UserDefaults.standard.string(forKey: urlKey).flatMap(URL.init(string:)) }
        set { UserDefaults.standard.set(newValue?.absoluteString, forKey: urlKey) }
    }

    static var token: String? {
        get { Keychain.read(tokenAccount) }
        set {
            if let newValue, !newValue.isEmpty { Keychain.write(tokenAccount, newValue) } else { Keychain.delete(tokenAccount) }
        }
    }

    static var isConfigured: Bool { serverURL != nil && token != nil }
}

/// Generic-password Keychain storage, readable after first unlock so background syncs can use it.
enum Keychain {
    private static func query(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "com.neelaypatel.rideapp",
         kSecAttrAccount as String: account]
    }

    static func read(_ account: String) -> String? {
        var q = query(account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func write(_ account: String, _ value: String) {
        delete(account)
        var q = query(account)
        q[kSecValueData as String] = Data(value.utf8)
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(q as CFDictionary, nil)
    }

    static func delete(_ account: String) {
        SecItemDelete(query(account) as CFDictionary)
    }
}

// MARK: - What the backend sends back

struct Connection: Decodable, Identifiable {
    var id: String { provider }
    let provider: String
    let name: String
    let auth: String            // device | api_key | oauth2
    let availability: String    // available | planned | blocked
    let gives: String
    let notes: String
    let state: String           // connected | not_connected | error
    let detail: String?
    let lastSyncAt: Double?
    let recordings: Int
}

struct RideSummary: Decodable, Identifiable {
    var id: String { rideId }
    let rideId: String
    let summary: Summary
    let sources: [String]
    let provenance: [String: String]
    let use: [String: UsePolicy]
    /// Why the server would leave this ride out of lists ("false_start", "empty"), or nil.
    let hidden: String?
    let excluded: [Excluded]?
    /// What's notable about this ride, best first (rule-based, as of the ride's date).
    let notes: [RideNote]?

    /// A stretch left out because it wasn't riding (e.g. the bike computer left on in a car).
    struct Excluded: Decodable {
        let reason: String
        let km: Double
        let minutes: Int
        let peakKmh: Double
    }

    struct Summary: Decodable {
        let start: Double
        let km: Double
        let movingH: Double
        let avgKmh: Double?
        let ascentM: Double?
        let avgHr: Double?
        let maxHr: Double?
        let avgPower: Double?
        /// Best 1 minute and best 20 minutes of measured power, and average cadence.
        let power60S: Double?
        let power1200S: Double?
        let avgCadence: Double?
        let calories: Double?
        /// Heart rate fallen in the minute after the ride (recovery), when the watch kept measuring.
        let hrDrop60S: Double?
        let indoor: Bool
    }

    struct UsePolicy: Decodable {
        let allowed: Bool
        let blockedBy: [String]
    }

    var date: Date { Date(timeIntervalSince1970: summary.start) }

    /// An indoor session with no distance (spin bike, trainer without a sensor): shown by time, not km.
    /// Indoors (a trainer's distance isn't road distance) or no distance at all: shown by time.
    var noDistance: Bool { summary.indoor || summary.km < 0.05 }
}

/// "Your longest ride yet": one thing worth saying about a ride.
struct RideNote: Decodable, Hashable {
    let kind: String        // distance | climbing | time | speed | power | rides | streak
    let text: String
    let detail: String?
    let weight: Int
    let pb: Bool            // a personal best at the time
    let milestone: Bool     // a round number crossed
}

/// The You screen: tallies, streaks, personal bests (GET /v1/you).
struct YouSummary: Decodable {
    let since: String?
    let all: Tally
    let year: Tally
    let lastYear: Tally
    let lastYearToDate: Tally
    let month: Tally
    let biggestMonth: Tally?
    let streak: Streak
    let bests: [Best]
    let routes: [RouteRepeat]?
    let climbs: [ClimbRepeat]?
    let recent: [Recent]
    /// True while the server is still working new rides in (routes, climbs and notes may lag a little).
    let updating: Bool?
    /// FTP, recent bests and the latest ride's average power; nil before any ride with measured power.
    let power: PowerSummary?

    struct PowerSummary: Decodable {
        let ftp: FTPValue
        let best1200S: Double?
        let best60S: Double?
        let days: Int
        let latest: Latest

        struct FTPValue: Decodable { let watts: Double?; let source: String }
        struct Latest: Decodable { let rideId: String; let start: Double; let avgPower: Double? }
    }

    struct Tally: Decodable {
        let label: String?
        let rides: Int
        let km: Double
        let hours: Double
        let ascentM: Double
        let everests: Double
        let longestKm: Double
        let crowFlies: String?
    }

    struct Streak: Decodable {
        let longestWeeks: Int
        let longestFrom: String?
        let currentWeeks: Int
    }

    struct Best: Decodable, Identifiable {
        var id: String { kind }
        let kind: String
        let label: String
        let value: Double
        let unit: String
        let text: String
        let rideId: String
        let start: Double
    }

    struct Recent: Decodable, Identifiable {
        var id: String { rideId }
        let rideId: String
        let start: Double
        let km: Double
        let notes: [RideNote]
    }
}

enum RepeatKind { case route, climb }

/// GET /v1/plan: weeks of structured sessions with targets and status.
struct TrainingPlan: Decodable {
    let planId: Int
    let start: String
    let readyBy: String
    let days: [String]
    let times: [String: String]
    let weeklyHours: Double
    let ftp: FTP
    let hrZones: [String: [Int]]?
    let maxHr: Double?
    let thisWeek: Int?
    let weeks: [Week]

    struct FTP: Decodable { let watts: Double?; let source: String }

    struct Week: Decodable, Identifiable {
        var id: String { weekStart }
        let weekStart: String
        let phase: String
        let index: Int
        let hours: Double
        let sessions: [PlanSession]
        let done: Int
        let total: Int
    }

    var sessions: [PlanSession] { weeks.flatMap(\.sessions) }
}

struct PlanSession: Decodable, Identifiable, Hashable {
    static func == (a: PlanSession, b: PlanSession) -> Bool { a.id == b.id && a.status == b.status }
    func hash(into h: inout Hasher) { h.combine(id) }

    let id: String
    let date: String
    let time: String
    let kind: String
    let title: String
    let purpose: String
    let indoor: Bool
    let offBike: Bool
    let seconds: Double
    let steps: [PlanStep]
    let status: String          // done | missed | today | upcoming
    let summary: String?
    let load: Double?

    var day: Date? { GoalText.date(date) }
}

/// A step ("Hard, 1 min, Z6") or a set of repeated steps ("6 × 1 min hard / 2 min easy").
struct PlanStep: Decodable, Hashable {
    let label: String?
    let seconds: Double?
    let zone: String?
    let rampTo: String?
    let target: PlanTarget?
    let set: String?
    let `repeat`: Int?
    let steps: [PlanStep]?

    /// Every step in order, sets expanded.
    var flat: [PlanStep] {
        guard let steps, let n = `repeat` else { return [self] }
        return (0..<n).flatMap { _ in steps.flatMap(\.flat) }
    }

    var totalSeconds: Double { flat.reduce(0) { $0 + ($1.seconds ?? 0) } }
}

struct PlanTarget: Decodable, Hashable {
    let pctFtp: [Int]
    let zoneName: String
    let rpe: Int
    let watts: [Int]?
    let hr: [Int]?
}

/// A number or a short text (a climb time like "13:43"), as the goals engine sends them.
enum NumOrText: Decodable, Hashable {
    case number(Double), text(String)

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let d = try? c.decode(Double.self) { self = .number(d) } else { self = .text(try c.decode(String.self)) }
    }

    func formatted(decimals: Int = 1) -> String {
        switch self {
        case .number(let d): return d.rounded() == d ? String(Int(d)) : Format.number(d, decimals: decimals)
        case .text(let s): return s
        }
    }

    var number: Double? { if case .number(let d) = self { d } else { nil } }
}

struct GoalOptions: Decodable {
    let objectives: [Objective]
    let season: Season

    struct Objective: Decodable, Identifiable, Hashable {
        let id: String
        let title: String
        let line: String
        let aspirations: [Aspiration]
    }

    struct Aspiration: Decodable, Identifiable, Hashable {
        let id: String
        let title: String
        let line: String
        let targetKm: Double?
    }
}

struct Season: Decodable, Hashable {
    let now: String                 // outdoor | indoor | mixed | none
    let outdoorMonths: [Int]
    let outdoorFrom: String?
    let outdoorUntil: String?
}

/// A goal as the rider builds it in the flow; sent as JSON in the server's own key names.
struct GoalDraft: Hashable {
    var objective = ""
    var aspiration = ""
    var words = ""
    var groupKmh: Double = 30
    var rideHours: Double = 1.75
    var terrain = "rolling"
    var targetKm: Double?
    var eventKm: Double?
    var eventClimbingM: Double?
    var weeklyHours: Double = 4.5
    var readyBy: Date?              // nil: when outdoor riding starts

    func json() throws -> Data {
        var params: [String: Any] = ["weekly_hours": weeklyHours]
        if aspiration == "keep_up_group" {
            params["group_kmh"] = groupKmh
            params["ride_hours"] = rideHours
            params["terrain"] = terrain
        }
        if let targetKm { params["target_km"] = targetKm }
        if let eventKm { params["event_km"] = eventKm }
        if let eventClimbingM { params["event_climbing_m"] = eventClimbingM }
        var body: [String: Any] = ["objective": objective, "aspiration": aspiration, "params": params]
        let w = words.trimmingCharacters(in: .whitespacesAndNewlines)
        if !w.isEmpty { body["words"] = w }
        if let readyBy {
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.dateFormat = "yyyy-MM-dd"
            body["ready_by"] = f.string(from: readyBy)
        }
        return try JSONSerialization.data(withJSONObject: body)
    }
}

/// A goal with what it means (the reveal) and how we'll see it working (markers).
struct GoalView: Decodable {
    let goal: Goal
    let reveal: Reveal
    let markers: [Marker]
    let season: Season

    struct Goal: Decodable {
        let id: Int?
        let objective: String
        let aspiration: String
        let title: String
        let readyBy: String?
        let words: String?
    }

    struct Reveal: Decodable {
        let headline: String
        let figures: Figures
        let build: [Build]
        let notes: [String]
    }

    struct Figures: Decodable {
        let groupKmh: Double?
        let soloKmh: Double?
        let soloBestKmh: Double?
        let draftPowerPct: Double?
    }

    struct Build: Decodable, Identifiable {
        let id: String
        let title: String
        let line: String
    }

    struct Marker: Decodable, Identifiable {
        let id: String
        let label: String
        let unit: String
        let current: NumOrText?
        let target: NumOrText?
        let better: String
        let history: [Point]
        let pending: String?
        let how: String?

        struct Point: Decodable { let date: String; let value: Double }

        var unitText: String { unit == "time" || unit.isEmpty ? "" : " " + unit }
    }
}

struct Me: Decodable {
    let id: Int
    let tz: String?
    let name: String
    let avatar: [String: String]?
}

/// GET /v1/avatar/options: every part, its choices, and colours for the swatches.
struct AvatarOptions: Decodable {
    let options: [String: [String]]
    let defaults: [String: String]
    let colors: Colors

    struct Colors: Decodable {
        let skin: [String: String]
        let hairColor: [String: String]
        let kit: [String: String]
        let frame: [String: String]?   // bike frame colours (an older server has none)
        let tyres: [String: String]?
    }

    enum CodingKeys: String, CodingKey { case options, defaults = "default", colors }
}

/// GET /v1/collection: the rider card's ratings, badges, and the season binder.
struct CollectionSummary: Decodable {
    let rider: Rider
    let badges: [Badge]
    let binder: [BinderPage]

    struct Rider: Decodable {
        /// Nil until the rider makes one (the card shows a silhouette).
        let avatar: [String: String]?
        let ratings: [String: Int]
        let overall: Int
        let type: String
        let rides: Int
        let km: Double
        let name: String
        let badgesEarned: Int
        let badgesTotal: Int
    }

    struct Badge: Decodable, Identifiable {
        let id: String
        let group: String
        let title: String
        let description: String
        let earned: Bool
        let date: String?
        let rideId: String?
        let progress: Progress

        struct Progress: Decodable { let value: Double; let target: Double }
    }

    struct BinderPage: Decodable, Identifiable {
        var id: Int { year }
        let year: Int
        let cards: [BinderCard]
        let gaps: [String]
        let holo: Int
        let weeks: Int
    }

    struct BinderCard: Decodable, Identifiable {
        var id: String { rideId }
        let rideId: String
        let start: Double
        let date: String
        let number: Int
        let name: String?
        let km: Double
        let ascentM: Double?
        let holo: Bool
        let headline: String?
        let shape: [[Double]]
        let week: String
    }
}

/// GET /v1/recovery: HRV and resting heart rate against the rider's usual range, VO2 max, and
/// heart-rate recovery after rides. For the rider only.
struct RecoverySummary: Decodable {
    let disclaimer: String
    let readiness: Readiness
    let hrvSdnn: Trend
    let restingHr: Trend
    let vo2max: Trend
    let hrRecovery1Min: Trend
    let rideRecovery: RideRecovery

    struct Readiness: Decodable {
        let status: String      // good | watch | strained | unknown
        let text: String
    }

    struct Trend: Decodable {
        let label: String
        let unit: String
        let higherIsBetter: Bool
        let latest: Double?
        let latestDate: String?
        let recent: Double?
        let usual: Double?
        let low: Double?
        let high: Double?
        let status: String      // usual | better | worse | unknown
        let series: [Point]
        let change90D: Double?
        let note: String?

        struct Point: Decodable { let date: String; let value: Double }
    }

    struct RideRecovery: Decodable {
        let count: Int
        let latest: Ride?
        let best: Ride?
        let series: [Point]
        let trend: String?

        struct Ride: Decodable { let rideId: String; let start: Double; let hrDrop60S: Double }
        struct Point: Decodable { let rideId: String; let start: Double; let value: Double }
    }

    var hasAnything: Bool {
        [hrvSdnn, restingHr, vo2max].contains { $0.latest != nil } || rideRecovery.count > 0
    }
}

/// A route ridden again and again (the home loop first, if there is one). Laps oldest first.
struct RouteRepeat: Decodable, Identifiable {
    let id: String
    let name: String
    let home: Bool
    let km: Double
    let count: Int
    /// The rider gave it their own name.
    let custom: Bool?
    let best: Lap?
    let last: Lap?
    let laps: [Lap]

    struct Lap: Decodable {
        let rideId: String
        let start: Double
        let kmh: Double?
        let avgHr: Double?
    }
}

/// A climb timed on fixed start and finish points every time it's ridden. Attempts oldest first.
struct ClimbRepeat: Decodable, Identifiable {
    let id: String
    let name: String
    let lengthM: Double
    let gainM: Double
    let grade: Double
    let count: Int
    let custom: Bool?
    let best: Attempt
    let last: Attempt
    let attempts: [Attempt]

    struct Attempt: Decodable {
        let rideId: String
        let start: Double
        let seconds: Double
        let avgHr: Double?
    }
}

/// One ride with its per-second samples (for the elevation profile and heart-rate peak).
struct RideTrace: Decodable {
    let totals: [String: Double]
    let samples: [Point]

    struct Point: Decodable {
        let t: Double
        let lat: Double?
        let lon: Double?
        let ele: Double?
        let hr: Double?
    }
}

struct SyncResult: Decodable {
    let new: Int
    let skipped: Int
}

struct UploadResult: Decodable {
    let rideId: String?
}

// MARK: - Client

struct APIError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

struct APIClient {
    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private func request(_ method: String, _ path: String, query: [URLQueryItem] = [], body: Data? = nil) throws -> URLRequest {
        guard let base = ServerConfig.serverURL, let token = ServerConfig.token else {
            throw APIError(message: "Set the server address and token in Settings first.")
        }
        var components = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query }
        var req = URLRequest(url: components.url!)
        req.httpMethod = method
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body {
            req.httpBody = body
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        req.timeoutInterval = 60
        return req
    }

    private func send(_ req: URLRequest) async throws -> Data {
        let (data, response) = try await URLSession.shared.data(for: req)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            struct ErrorBody: Decodable { let error: String?; let detail: String? }
            let body = try? Self.decoder.decode(ErrorBody.self, from: data)
            throw APIError(message: body?.error ?? body?.detail ?? "Server error \(status)")
        }
        return data
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        try Self.decoder.decode(T.self, from: await send(request("GET", path, query: query)))
    }

    func connections() async throws -> [Connection] { try await get("v1/connections") }

    /// Every ride, false starts included (marked `hidden`), so the app can show or hide them.
    func rides() async throws -> [RideSummary] {
        try await get("v1/rides", query: [URLQueryItem(name: "include_hidden", value: "true")])
    }

    func you() async throws -> YouSummary { try await get("v1/you") }

    func collection() async throws -> CollectionSummary { try await get("v1/collection") }

    // MARK: Goals (rideengine/analysis/goals.py)

    func goalOptions() async throws -> GoalOptions { try await get("v1/goals/options") }

    /// What a goal would mean and what we'd watch, without saving it.
    func goalPreview(_ draft: GoalDraft) async throws -> GoalView {
        try Self.decoder.decode(GoalView.self, from: await send(request("POST", "v1/goals/preview", body: draft.json())))
    }

    func setGoal(_ draft: GoalDraft) async throws -> GoalView {
        try Self.decoder.decode(GoalView.self, from: await send(request("PUT", "v1/goals/current", body: draft.json())))
    }

    /// The active goal, or nil if none is set.
    func currentGoal() async throws -> GoalView? {
        do { return try await get("v1/goals/current") } catch let e as APIError where e.message == "No goal set" { return nil }
    }

    // MARK: Training plan (rideengine/analysis/plan.py)

    /// The plan for the active goal, or nil if there's no goal.
    func plan() async throws -> TrainingPlan? {
        do { return try await get("v1/plan") } catch let e as APIError where e.message.hasPrefix("No plan") { return nil }
    }

    func planSettings(days: [String], times: [String: String], weeklyHours: Double) async throws -> TrainingPlan {
        let body = try JSONSerialization.data(withJSONObject: ["days": days, "times": times, "weekly_hours": weeklyHours])
        return try Self.decoder.decode(TrainingPlan.self, from: await send(request("PUT", "v1/plan/settings", body: body)))
    }

    func setDone(_ sessionId: String, _ done: Bool) async throws {
        _ = try await send(request(done ? "PUT" : "DELETE", "v1/plan/sessions/\(sessionId)/done"))
    }

    /// The session as a Zwift workout file.
    func zwift(_ sessionId: String) async throws -> Data {
        try await send(request("GET", "v1/plan/sessions/\(sessionId)/zwift"))
    }

    struct CalendarLink: Decodable { let url: String; let webcal: String }

    func calendarLink() async throws -> CalendarLink { try await get("v1/plan/calendar") }

    func setFTP(_ watts: Double?) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["ftp": watts as Any? ?? NSNull()])
        _ = try await send(request("PUT", "v1/me", body: body))
    }

    func endGoal() async throws {
        _ = try await send(request("DELETE", "v1/goals/current"))
    }

    func me() async throws -> Me { try await get("v1/me") }

    /// Save the rider's name and avatar (nil avatar removes it).
    func updateMe(name: String, avatar: [String: String]?) async throws -> Me {
        struct Body: Encodable {
            let name: String
            let avatar: [String: String]?
            func encode(to encoder: Encoder) throws {
                var c = encoder.container(keyedBy: CodingKeys.self)
                try c.encode(name, forKey: .name)
                try c.encode(avatar, forKey: .avatar)  // null removes it
            }
            enum CodingKeys: String, CodingKey { case name, avatar }
        }
        let body = try JSONEncoder().encode(Body(name: name, avatar: avatar))
        return try Self.decoder.decode(Me.self, from: await send(request("PUT", "v1/me", body: body)))
    }

    func avatarOptions() async throws -> AvatarOptions { try await get("v1/avatar/options") }

    /// The avatar drawn from a spec, as SVG (for the builder's preview; nothing saved).
    func avatarPreview(_ spec: [String: String]) async throws -> String {
        let data = try await send(request("POST", "v1/avatar/preview", body: JSONEncoder().encode(spec)))
        return String(decoding: data, as: UTF8.self)
    }

    func riderCardHTML() async throws -> String {
        let data = try await send(request("GET", "v1/rider/card", query: [
            URLQueryItem(name: "fonts", value: "local"), URLQueryItem(name: "background", value: "transparent")]))
        return String(decoding: data, as: UTF8.self)
    }

    func recovery() async throws -> RecoverySummary { try await get("v1/recovery") }

    struct MetricsResult: Decodable { let received: Int; let new: Int }

    func uploadMetrics(_ batch: MetricsBatch) async throws -> MetricsResult {
        let body = try JSONEncoder().encode(batch)
        return try Self.decoder.decode(MetricsResult.self,
                                       from: await send(request("POST", "v1/metrics/apple_health", body: body)))
    }

    /// Dates, years and streaks are worked out in the rider's own time zone.
    func setTimeZone(_ identifier: String) async throws {
        let body = try JSONEncoder().encode(["tz": identifier])
        _ = try await send(request("PUT", "v1/me", body: body))
    }

    /// The rider's own name for a route or climb; nil goes back to the automatic name.
    func rename(_ kind: RepeatKind, id: String, to name: String?) async throws {
        struct Body: Encodable {
            let name: String?
            func encode(to encoder: Encoder) throws {
                var c = encoder.container(keyedBy: CodingKeys.self)
                try c.encode(name, forKey: .name)  // null, not left out
            }
            enum CodingKeys: String, CodingKey { case name }
        }
        let path = (kind == .route ? "v1/routes/" : "v1/climbs/") + (id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id)
        _ = try await send(request("PATCH", path, body: JSONEncoder().encode(Body(name: name))))
    }

    /// The ride's card as HTML, drawn by the server, with font files the app supplies.
    func cardHTML(_ rideId: String) async throws -> String {
        let data = try await send(request("GET", "v1/rides/\(rideId)/card", query: [
            URLQueryItem(name: "fonts", value: "local"), URLQueryItem(name: "background", value: "transparent")]))
        return String(decoding: data, as: UTF8.self)
    }

    /// Delete a ride and every recording merged into it; later syncs and uploads won't bring it back.
    func deleteRide(_ rideId: String) async throws {
        _ = try await send(request("DELETE", "v1/rides/\(rideId)"))
    }

    func trace(_ rideId: String) async throws -> RideTrace {
        try await get("v1/rides/\(rideId)", query: [URLQueryItem(name: "samples", value: "true")])
    }

    func connect(_ provider: String, credentials: [String: String], since: Date?) async throws {
        let body = try JSONEncoder().encode(credentials)
        _ = try await send(request("PUT", "v1/connections/\(provider)", query: Self.sinceQuery(since), body: body))
    }

    func sync(_ provider: String) async throws -> SyncResult {
        try Self.decoder.decode(SyncResult.self, from: await send(request("POST", "v1/connections/\(provider)/sync")))
    }

    func disconnect(_ provider: String) async throws {
        _ = try await send(request("DELETE", "v1/connections/\(provider)"))
    }

    func upload(_ recording: RecordingPayload) async throws -> UploadResult {
        let body = try JSONEncoder().encode(recording)
        return try Self.decoder.decode(UploadResult.self,
                                       from: await send(request("POST", "v1/uploads/apple_health", body: body)))
    }

    private static func sinceQuery(_ since: Date?) -> [URLQueryItem] {
        guard let since else { return [] }
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return [URLQueryItem(name: "since", value: f.string(from: since))]
    }
}

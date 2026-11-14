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

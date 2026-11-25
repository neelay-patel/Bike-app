import Foundation
import Security

/// Where the backend is and how to log in to it.
/// Dev setup: server URL + the token from `python -m backend create-user`.
/// Sign in with Apple replaces the token once the paid developer account is in place.
enum ServerConfig {
    private static let urlKey = "serverURL"
    private static let tokenAccount = "backend-token"

    static var serverURL: URL? {
        get {
            #if DEBUG
            // Simulator testing against a throwaway server: `SIMCTL_CHILD_KOVA_DEV_SERVER=... xcrun simctl launch`.
            if let s = ProcessInfo.processInfo.environment["KOVA_DEV_SERVER"] { return URL(string: s) }
            #endif
            return UserDefaults.standard.string(forKey: urlKey).flatMap(URL.init(string:))
        }
        set { UserDefaults.standard.set(newValue?.absoluteString, forKey: urlKey) }
    }

    static var token: String? {
        get {
            #if DEBUG
            if let t = ProcessInfo.processInfo.environment["KOVA_DEV_TOKEN"] { return t }
            #endif
            return Keychain.read(tokenAccount)
        }
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

/// What the rider did in a session: the real ride(s), the false starts folded in, and the phases worked out
/// from the samples (GET /v1/efforts/{id}; rideengine/analysis/effort.py).
struct Effort: Decodable {
    let effortId: String
    let parts: [Part]
    let folded: [Folded]
    /// Rule-based words, in order: what happened.
    let lines: [String]
    /// The planned session this ride counts as, planned against ridden (the same as the ride note in Train).
    let plan: Plan?

    struct Plan: Decodable {
        let sessionId: String
        let title: String
        let summary: String?
        let lines: [String]
        let sets: [PlannedSet]
    }

    struct Part: Decodable {
        let rideId: String
        let phases: Phases
    }

    struct Folded: Decodable {
        let rideId: String
        let reason: String?
        let minutes: Double
    }

    struct Phases: Decodable {
        /// "power" or "heart_rate": what the phases were read from.
        let basis: String
        let phases: [Phase]
        let pushes: [Phase]
        /// Every 15 s: [seconds from start, watts or nil, bpm or nil].
        let series: [[Double?]]
    }

    struct Phase: Decodable {
        /// warm_up | structured | riding | pause | cool_down | push
        let kind: String
        let startS: Double
        let endS: Double
        let minutes: Double
        let power: Double?
        let cadence: Double?
        let hr: Double?
        let hrMax: Double?
    }
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
    /// Riding another device recorded before the main recording started or after it stopped (merge.py).
    let added: [Added]?
    /// What's notable about this ride, best first (rule-based, as of the ride's date).
    let notes: [RideNote]?
    /// The effort (session) this ride is part of: the id of its main ride. False starts point at the real one.
    let effort: String?

    /// A stretch left out because it wasn't riding (e.g. the bike computer left on in a car).
    struct Excluded: Decodable {
        let reason: String
        let km: Double
        let minutes: Int
        let peakKmh: Double
    }

    /// "before" or "after" the main recording: minutes and km from another device.
    struct Added: Decodable {
        let where_: String
        let source: String
        let minutes: Double
        let km: Double?
        enum CodingKeys: String, CodingKey { case where_ = "where", source, minutes, km }
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

/// One planned set against what was ridden: "5 × 1 min hard", 5 of 5, 219 W against 183–226 W.
struct PlannedSet: Decodable, Hashable {
    let set: String
    let planned: Int
    let done: Int
    let power: Int?
    let watts: [Int]?
    let target: [Int]?
    /// on | above | below | done (no target) | missing
    let verdict: String
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
    /// The four headline numbers with the goal's targets (rideengine/analysis/headline.py).
    let headline: Headline?
    /// Prizes for the tallies that only go up: hours, km, rides, Everests.
    let milestones: [Milestone]?

    struct Headline: Decodable {
        let metrics: [Metric]
        let next: Next?
        let goal: GoalRef?

        struct Metric: Decodable, Identifiable {
            let id: String
            let label: String
            let plain: String
            let unit: String
            let decimals: Int
            let current: Double?
            let target: Double?
            let baseline: Double?
            let progress: Double?
            let history: [GoalView.Marker.Point]
            let pending: String?
            let detail: String?
            let action: String
            let focus: Bool
        }
        struct Next: Decodable { let id: String?; let text: String }
        struct GoalRef: Decodable { let id: Int; let title: String?; let words: String?; let readyBy: String? }
    }

    struct Milestone: Decodable, Identifiable {
        var id: String { kind }
        let kind: String
        let label: String
        let total: Double
        let earned: [Prize]
        let next: Next?

        struct Prize: Decodable, Identifiable {
            var id: Double { value }
            let value: Double
            let text: String
            let date: String
            let rideId: String
        }
        struct Next: Decodable { let value: Double; let text: String; let toGo: Double; let progress: Double }
    }

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
        /// The part of it on a trainer (Zwift km and climbing count in the totals, 19 Nov 2026).
        let indoor: Indoor?
        struct Indoor: Decodable { let rides: Int; let km: Double; let hours: Double; let ascentM: Double }
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

// MARK: - Train (docs/train-tab.md): today, the week as counted, and a note for each ride

/// GET /v1/train/today. state: session | rest | done | no_plan.
/// The Sunday review (rideengine/analysis/review.py): the week in a few lines, and next week's changes.
struct TrainReview: Decodable {
    let weekStart: String
    let index: Int
    let lines: [String]
    let proposals: [Proposal]
    let done: Int
    let total: Int
    let story: Story?

    struct Proposal: Decodable, Identifiable {
        let id: String
        let type: String
        let size: String          // small (applied on its own) | big (waits for the rider)
        let change: String
        let reason: String
        let rules: [String]
        let status: String        // open | applied | accepted | declined
    }
    struct Story: Decodable { let summary: String; let proposals: [String: String] }
}

/// A line in the coach's voice, with the key of its research in docs/training-science.md.
struct Learn: Decodable, Hashable { let key: String; let text: String }

struct TrainToday: Decodable {
    let state: String
    let date: String?
    let week: Int?
    let weeks: Int?
    let phase: String?
    let greeting: String?
    let session: PlanSession?
    let why: String?
    let feel: String?
    /// Where to ride it: advice only, since indoors or out is the rider's choice.
    let where_: String?
    let then: String?
    /// The sessions What's Next names (tomorrow's, and the one after), each opening its own page.
    let next: [NextSession]?
    let nextNote: String?

    enum CodingKeys: String, CodingKey {
        case state, date, week, weeks, phase, greeting, session, why, feel, then, readiness, goal, latest, days, done, total
        case next, nextNote, changes, learn, review, brief
        case where_ = "where"
    }
    let readiness: String?
    let goal: TrainGoal?
    let latest: TrainNote?
    /// This week, day by day, for the strip on Today.
    let days: [Day]?
    let done: Int?
    let total: Int?

    /// Why today's work works, in a line (its research: docs/training-science.md).
    let learn: Learn?
    /// The week in review (Sunday evening to Tuesday, or while a change waits for the rider's OK).
    let review: ReviewCard?
    /// This morning's brief in the AI coach's words (when the rider has the AI on).
    let brief: Brief?

    struct Brief: Decodable { let title: String; let body: String }

    struct ReviewCard: Decodable { let weekStart: String; let index: Int; let line: String?; let open: Int }
    /// The week laid out differently since last shown (docs/train-method.md "When the plan changes"): the week
    /// as it is now and why, in a line, until seen. The newest only.
    let changes: [Change]?

    struct Change: Decodable, Identifiable {
        let id: Int
        let line: String
        let reason: String?
        let big: Bool?
    }
    struct NextSession: Decodable, Identifiable {
        var id: String { session.id }
        let date: String
        let when: String
        let session: PlanSession
    }

    struct Day: Decodable, Identifiable {
        var id: String { date }
        let date: String
        let state: String          // rode | session | rest
        let title: String?
        let today: Bool

        var letter: String { GoalText.date(date)?.formatted(.dateTime.weekday(.narrow)) ?? "" }
    }
}

struct TrainGoal: Decodable {
    let title: String?
    let words: String?
    let readyBy: String?
    let weeksLeft: Int?
    let markers: [Marker]

    struct Marker: Decodable, Identifiable {
        let id: String
        let name: String
        let meaning: String
        let unit: String
        let current: Double?
        let target: Double?
        let baseline: Double?
        let reached: Bool

        /// How far from where the goal started to its aim, 0...1.
        var progress: Double {
            guard let c = current, let t = target else { return 0 }
            if reached { return 1 }
            let b = baseline ?? c
            return t > b ? max(0, min(1, (c - b) / (t - b))) : 0
        }
    }
}

/// GET /v1/train/rides/{id}: what you did, counted as, what it means, what's next, one thing to try.
struct TrainNote: Decodable, Identifiable {
    var id: String { rideId }
    let rideId: String
    let date: String
    let indoor: Bool?
    let did: Did
    let kind: String?
    let kindTitle: String?
    let reason: String?
    let counted: Counted?
    let means: [String]
    let next: String?
    let tips: [Tip]
    /// The AI coach's words, from the engine's facts (only with the personal-use setting on).
    let story: Story?
    let feel: Feel?
    /// The session it counts as, planned against ridden, set by set.
    let against: Against?
    /// What the rider's "how did it feel" changed (the targets going up after a hard session felt easy).
    let feelNote: String?
    /// Which of the week's jobs the ride did, and how much of each (docs/train-method.md).
    let jobs: Jobs?
    /// The session this ride did part of, and what's left of it.
    let toward: Toward?
    /// What's left of this week's jobs, on the days they're now expected.
    let left: String?
    /// The coach's voice (docs/train-method.md step 5): one specific thing done well, and why the work works.
    let doneWell: Learn?
    let learn: Learn?
    /// The ride's moving time in zone 2, above and below, and one line where zone 2 was the point.
    let zone2: Zone2Split?

    struct Toward: Decodable { let sessionId: String; let title: String; let job: String?; let line: String }

    struct Jobs: Decodable {
        let summary: String?
        let jobs: [Job]
        let also: [Job]
    }
    struct Job: Decodable, Identifiable {
        var id: String { job }
        let job: String
        let title: String
        /// done | more | part | also
        let status: String
        let line: String
    }

    struct Against: Decodable { let summary: String; let lines: [String]; let sets: [PlannedSet] }
    struct Story: Decodable { let headline: String; let story: String }
    struct Feel: Decodable { let feel: String; let hurts: Bool }

    struct Did: Decodable {
        let km: Double
        let minutes: Int
        let ascentM: Double?
        let avgPower: Double?
        let avgHr: Double?
        let bestMinute: Double?
    }

    struct Counted: Decodable {
        let sessionId: String
        let title: String
        let kind: String
        let reason: String?
        let byHand: Bool
    }

    struct Tip: Decodable, Identifiable, Hashable { let id: String; let title: String; let text: String }

    var day: Date? { GoalText.date(date) }
}

/// GET /v1/train/week: a plan week with what counted as each session, the week's rides, and (this week) the
/// days the open sessions are now expected on.
/// Moving time in zone 2, above and below (adds to 100), the range it was read against, and one line.
struct Zone2Split: Decodable, Hashable {
    let `in`: Int
    let above: Int
    let below: Int
    let minutes: Int
    let bpm: [Int]
    let line: String?
    /// Average watts while heart rate was in zone 2 (rides with power).
    let watts: Int?
}

/// GET /v1/train/zone2: the rider's range and where it came from, what the latest steady ride says about it,
/// this week's share, and watts at zone 2 by month.
struct TrainZone2: Decodable {
    let range: [Int]?
    let source: String?
    let how: String?
    let own: String?
    let talk: String?
    let why: String?
    let check: Check?
    let week: Zone2Split?
    let trend: [Month]?

    struct Check: Decodable { let rideId: String; let date: String; let verdict: String; let line: String }
    struct Month: Decodable, Identifiable {
        var id: String { month }
        let month: String
        let watts: Int
        let minutes: Int
    }
}

struct TrainWeek: Decodable {
    let weekStart: String
    let phase: String
    let index: Int
    let sessions: [PlanSession]
    let rides: [WeekRide]
    let extra: [Extra]
    let done: Int
    let total: Int
    let schedule: [String: String]
    /// The week's time in zone 2, above and below.
    let zone2: Zone2Split?

    struct WeekRide: Decodable, Identifiable {
        var id: String { rideId }
        let rideId: String
        let date: String
        let minutes: Int
        let indoor: Bool?
        let kindTitle: String?
    }

    struct Extra: Decodable, Identifiable {
        var id: String { rideId }
        let rideId: String
        let kindTitle: String?
        let reason: String?
    }
}

struct PlanSession: Decodable, Identifiable, Hashable {
    static func == (a: PlanSession, b: PlanSession) -> Bool { a.id == b.id && a.status == b.status }
    func hash(into h: inout Hasher) { h.combine(id) }

    let id: String
    /// The plan's first sketch of its day, and the rider's usual time that day.
    let date: String
    let time: String
    /// The day it's on (24 Nov 2026): the day it was ridden, else the day this week's fresh layout puts it on.
    let on: String?
    let kind: String
    let title: String
    let purpose: String
    let indoor: Bool
    let offBike: Bool
    let seconds: Double
    let steps: [PlanStep]
    let status: String          // done | open (earlier this week, still to do) | missed | today | upcoming
    let summary: String?
    let load: Double?
    /// The ride that counted as this session, by what it contained, whatever the day (Train, step 1).
    let counted: Counted?
    /// How to ride it: only on the session's own page (GET v1/plan/sessions/{id}).
    let guide: SessionGuide?
    /// The job it does in the week (docs/train-method.md): punch, top_end, hold, long, easy, strength.
    let job: String?
    /// Partly done: how much of its job rides have done, and what's left.
    let progress: Progress?
    /// Why it's bigger (or smaller) than the last one of its kind: grown from the evidence.
    let grew: String?
    /// The job's shape in words, so any workout can do it ("Or any ride with 7.5 min or more of hard efforts…").
    let shape: String?
    /// From a Sunday review: another way to do this job, the session it replaced, or the one it eased.
    let anotherWay: String?
    let swappedFrom: String?
    let easedFrom: String?
    /// Re-planned this week (docs/train-method.md): leftovers of other sessions added to this one ...
    let added: [String]?
    /// ... this session's leftover, added to another ride ...
    let foldedInto: FoldedInto?
    /// ... or let go: no room for it this week.
    let dropped: String?

    struct FoldedInto: Decodable, Hashable { let sessionId: String; let date: String; let line: String }

    struct Progress: Decodable, Hashable {
        let haveMin: Double
        let wantMin: Double
        let leftMin: Double
        let line: String
    }

    var jobTitle: String? {
        ["punch": "Punch", "top_end": "Top end", "hold": "Hold", "long": "Long", "easy": "Easy",
         "strength": "Strength"][job ?? ""]
    }

    struct Counted: Decodable, Hashable {
        let rideId: String
        let date: String
        let reason: String?
        let kindTitle: String?
        let byHand: Bool?
    }

    /// The day it's on, as the rider sees it everywhere (the week, the calendar, the Watch).
    var onDate: String { on ?? date }
    var day: Date? { GoalText.date(onDate) }
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
    /// Cadence to aim for (none for a sprint: wind it up as fast as you can).
    let rpm: [Int]?
}

/// How to ride a session, part by part (rideengine/analysis/today.py `guide`), on the session's own page.
struct SessionGuide: Decodable, Hashable {
    let why: String
    let feel: String?
    let where_: String?
    let warm: String?
    let main: [String]
    let cool: String?
    let after: String?
    let bring: [String]

    enum CodingKeys: String, CodingKey {
        case why, feel, warm, main, cool, after, bring
        case where_ = "where"
    }
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
    /// The morning brief's time, "HH:MM" in the rider's time zone (06:00 unless they changed it).
    let briefAt: String?
    /// The rider's own zone 2 range, "126-138"; nil when it's worked out.
    let zone2: String?
    /// AI is on for the account (personal use): the coach you can ask is there.
    let ai: Bool?
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
        var indoor: Bool? = nil
        /// Indoors: the session over time, 0..1 (power, else heart rate), and the ride game's world (Zwift).
        var trace: [Double]? = nil
        var traceKind: String? = nil
        var world: String? = nil
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

// MARK: - Planned routes (rideengine/routes/: the route check and export)

struct Course: Decodable, Identifiable {
    let id: Int
    let name: String
    let source: String?
    let link: String?
    let createdAt: Double
    let status: String              // checking, ready, failed
    let error: String?
    let km: Double?
    let ascentM: Double?
    let gravelShare: Double?
    let timeS: Double?
    let loop: Bool?
    let singletrackKm: Double?
    let verdict: [Verdict]
    let shape: [[Double]]
    let report: CourseReport?
    /// What tuning has done, oldest first (empty: the route as it came in).
    let changes: [Change]?
    /// For a loop made from a description: what was asked, and why this one.
    let plan: Plan?

    struct Plan: Decodable, Hashable {
        let text: String?
        let tags: [String]
        let why: [String]
        let via: String?
    }

    struct Verdict: Decodable, Hashable { let tone: String; let text: String }
    struct Change: Decodable, Hashable { let n: Int; let change: String }
}

/// What POST /v1/courses/plan understood, and the questions left or the loops it made.
/// Where home is: the one the rider set ("set"), or where most of the past year's rides start ("rides").
struct HomeInfo: Decodable {
    let lat: Double?
    let lon: Double?
    let label: String?
    let source: String?
    let rides: Int?
}

struct PlanResult {
    let ask: [String: Any]
    let tags: [String]
    let notes: [String]
    let questions: [Question]
    let home: Bool
    let courses: [Course]

    struct Question: Identifiable {
        var id: String { key }
        let key: String
        let text: String
        let hint: String?
        /// Words from the description we couldn't place ourselves (a street address): pre-filled to look up.
        let guess: String?
        let choices: [String]
        let raw: [Any]
    }
}

/// Tuning choices: stops near the route but off it, and places to start from.
struct CourseOptions: Decodable {
    let stops: [Stop]
    let starts: [Start]
    /// The longest stretch with no food or water on the map (25 km or more), if any.
    let gap: Gap?

    struct Gap: Decodable, Hashable { let fromKm: Double; let toKm: Double; let km: Double }

    struct Stop: Decodable, Identifiable, Hashable {
        let name: String; let kind: String; let what: String; let hours: String
        let lat: Double; let lon: Double; let km: Double; let offM: Double
        let fillsGap: Bool?
        var id: String { "\(name)-\(lat)" }
    }
    struct Start: Decodable, Identifiable, Hashable {
        let name: String; let lat: Double; let lon: Double; let km: Double; let kind: String
        var id: String { "\(name)-\(lat)" }
    }
}

struct CourseReport: Decodable {
    let km: Double
    let loop: Bool
    let ascentM: Double?
    let surfaces: [Surface]
    let gravelShare: Double?
    let unknownKm: Double
    let assumedKm: Double
    let singletrack: [Stretch]
    let trails: [Stretch]?
    let busy: [Stretch]
    let straights: [Stretch]
    let twiceKm: Double
    let climbs: [Climb]
    let stops: [Stop]
    /// A few sensible places to stop (rideengine/routes/check.py rest_stops); nil in reports made before.
    let rest: [Rest]?
    let longestGap: Gap?
    let midway: Midway?
    let timeS: Double
    let knownShare: Double?
    let stretches: [MapStretch]
    let profile: [ProfilePoint]
    let cues: [Cue]
    let start: [Double]
    let bbox: [Double]
    let credit: String
    let osmDate: String?
    let verdict: [Course.Verdict]

    struct Surface: Decodable, Identifiable { let `class`: String; let label: String; let km: Double; let share: Double
        var id: String { `class` } }
    struct Stretch: Decodable, Hashable { let fromKm: Double; let toKm: Double; let km: Double; let name: String }
    struct Climb: Decodable, Hashable { let km: Double; let lengthM: Double; let gainM: Double; let grade: Double }
    struct Gap: Decodable { let fromKm: Double; let toKm: Double; let km: Double }
    struct Midway: Decodable { let km: Double; let place: String?; let name: String }
    struct Stop: Decodable, Identifiable {
        let km: Double; let lat: Double; let lon: Double; let place: String?
        let food: Bool; let shop: Bool; let water: Bool; let toilets: Bool; let view: Bool
        let items: [Item]
        var id: String { "\(km)-\(lat)" }
        struct Item: Decodable, Hashable { let name: String; let kind: String; let what: String; let hours: String; let offM: Double }
    }
    struct Rest: Decodable, Identifiable {
        let km: Double; let name: String; let what: String; let kind: String; let hours: String
        let place: String?; let lat: Double; let lon: Double; let offM: Double
        let why: String; let rest: Bool; let also: [String]
        var id: String { "\(km)-\(name)" }
    }
    struct MapStretch: Decodable { let `class`: String; let fromKm: Double; let toKm: Double; let points: [[Double]] }
    struct ProfilePoint: Decodable {
        let km: Double; let ele: Double; let surface: String
        init(from decoder: Decoder) throws {
            var c = try decoder.unkeyedContainer()
            km = try c.decode(Double.self); ele = try c.decode(Double.self); surface = try c.decode(String.self)
        }
    }
    struct Cue: Decodable, Identifiable, Hashable {
        let km: Double; let turn: String; let text: String; let surface: String?; let forKm: Double?
        var id: String { "\(km)-\(text)" }
    }
}

// MARK: - The coach you can ask anything (backend/coach_chat.py)

/// GET /v1/coach: the one thing it's working on with you, the rest of its advice (each checked after every ride by
/// the engine), what it watches, ideas to ask, and the conversation. `on` is false until AI is on for the account.
struct CoachHome: Decodable {
    let on: Bool
    let why: String?
    let oneThing: CoachAdvice?
    let workingOn: [CoachAdvice]?
    let watching: [CoachWatch]?
    let ideas: [String]?
    let messages: [CoachChatMessage]?
    let remembers: Int?
}

/// Advice the coach gave and follows up: how it's going comes from the engine's numbers on the rides since.
struct CoachAdvice: Decodable, Identifiable, Hashable {
    let id: Int
    let title: String
    let `do`: String
    let why: String?
    let measure: String
    let status: String?        // waiting | working | not_yet (open advice); done | dropped | replaced in `closed`
    let statusLabel: String?
    let check: String?
    let closed: String?
}

struct CoachWatch: Decodable, Hashable {
    let label: String
    let value: String
    let unit: String
    let detail: String?
}

struct CoachChatMessage: Decodable, Identifiable, Hashable {
    let id: Int
    let role: String           // rider | coach
    let text: String
    let status: String         // working | done | failed
    let progress: String?
    let charts: [CoachChart]?
    let actions: [CoachAction]?
    let advice: [CoachAdviceRef]?
    let rideId: String?
}

/// A chart under an answer, drawn by the app; the numbers are the engine's, never the AI's.
struct CoachChart: Decodable, Hashable {
    let type: String           // trend | aim | ride
    let title: String
    let unit: String?
    let points: [Point]?
    let band: [Double]?
    let start: Double?
    let current: Double?
    let target: Double?
    let rideId: String?
    let date: String?
    let `where`: String?
    let minutes: Int?
    let km: Double?
    let avgHr: Double?
    let avgPower: Double?
    let zone2: Zone2Split?

    struct Point: Decodable, Hashable { let label: String; let value: Double }
}

/// A plan change the coach proposed: nothing changes until the rider says OK (the engine checks it again then).
struct CoachAction: Decodable, Identifiable, Hashable {
    let id: Int
    let preview: String
    let why: String?
    let status: String         // open | accepted | declined | failed
    let whyNot: String?
}

struct CoachAdviceRef: Decodable, Identifiable, Hashable {
    let id: Int
    let title: String
    let `do`: String
    let measure: String
    let status: String
}

struct CoachAsked: Decodable {
    let question: Int
    let answer: Int
    let messages: [CoachChatMessage]
}

/// GET /v1/coach/knows: what the coach reads, never reads, the notes it keeps, and its advice so far.
struct CoachKnows: Decodable {
    struct Read: Decodable, Hashable { let what: String; let detail: String }
    struct Note: Decodable, Identifiable, Hashable { let id: Int; let note: String }
    let reads: [Read]
    let never: String
    let memory: [Note]
    let advice: [CoachAdvice]
    let disclaimer: String
}

// MARK: - Client

struct APIError: LocalizedError {
    let message: String
    /// The HTTP status, when the server answered (401: token not accepted).
    var status: Int? = nil
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
            throw APIError(message: body?.error ?? body?.detail ?? "Server error \(status)", status: status)
        }
        return data
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        try Self.decoder.decode(T.self, from: await send(request("GET", path, query: query)))
    }

    func connections() async throws -> [Connection] { try await get("v1/connections") }

    /// Every ride, false starts included (marked `hidden`), so the app can show or hide them.
    func effort(_ rideId: String) async throws -> Effort {
        try await get("v1/efforts/\(rideId)")
    }

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

    // MARK: The coach you can ask anything (backend/coach_chat.py)

    func coachHome() async throws -> CoachHome { try await get("v1/coach") }

    /// Ask the coach; the answer arrives "working" and is read with `coachMessages(after:)` until it's done.
    func coachAsk(_ text: String, rideId: String? = nil) async throws -> CoachAsked {
        var b: [String: Any] = ["text": text]
        if let rideId { b["ride_id"] = rideId }
        let body = try JSONSerialization.data(withJSONObject: b)
        return try Self.decoder.decode(CoachAsked.self, from: await send(request("POST", "v1/coach/ask", body: body)))
    }

    func coachMessages(after: Int = 0) async throws -> [CoachChatMessage] {
        struct R: Decodable { let messages: [CoachChatMessage] }
        let r: R = try await get("v1/coach/messages", query: [URLQueryItem(name: "after", value: String(after))])
        return r.messages
    }

    func coachNewConversation() async throws {
        _ = try await send(request("POST", "v1/coach/new"))
    }

    func coachKnows() async throws -> CoachKnows { try await get("v1/coach/knows") }

    func coachForget(_ id: Int) async throws {
        _ = try await send(request("DELETE", "v1/coach/memory/\(id)"))
    }

    /// done | dropped | open
    func coachSetAdvice(_ id: Int, status: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["status": status])
        _ = try await send(request("PUT", "v1/coach/advice/\(id)", body: body))
    }

    func coachDecide(_ id: Int, accept: Bool) async throws -> CoachAction {
        let body = try JSONSerialization.data(withJSONObject: ["accept": accept])
        return try Self.decoder.decode(CoachAction.self, from: await send(request("POST", "v1/coach/actions/\(id)", body: body)))
    }

    // MARK: Train (rideengine/analysis/train.py, today.py, feedback.py)

    func trainToday() async throws -> TrainToday { try await get("v1/train/today") }

    /// The coach's messages for notifications (CoachNotifications.swift).
    func trainInbox() async throws -> CoachInbox { try await get("v1/train/inbox") }

    func trainWeek(start: String? = nil) async throws -> TrainWeek {
        try await get("v1/train/week", query: start.map { [URLQueryItem(name: "start", value: $0)] } ?? [])
    }

    func rideNote(_ rideId: String) async throws -> TrainNote { try await get("v1/train/rides/\(rideId)") }

    /// The one tap after a ride: easy, good, hard or wrecked, and whether something hurts.
    func setFeel(_ rideId: String, feel: String, hurts: Bool) async throws -> TrainNote {
        let body = try JSONSerialization.data(withJSONObject: ["feel": feel, "hurts": hurts])
        return try Self.decoder.decode(TrainNote.self, from: await send(request("PUT", "v1/train/rides/\(rideId)/feel", body: body)))
    }

    /// Count a ride as a session by hand (nil: as none), or hand it back to automatic counting.
    func countRide(_ rideId: String, as sessionId: String?, automatic: Bool = false) async throws {
        if automatic {
            _ = try await send(request("DELETE", "v1/plan/rides/\(rideId)/counts-as"))
        } else {
            let body = try JSONSerialization.data(withJSONObject: ["session_id": sessionId as Any? ?? NSNull()])
            _ = try await send(request("PUT", "v1/plan/rides/\(rideId)/counts-as", body: body))
        }
    }

    /// A session with how to ride it (its `guide`).
    func planSession(_ sessionId: String) async throws -> PlanSession { try await get("v1/plan/sessions/\(sessionId)") }

    func trainReview(week: String? = nil) async throws -> TrainReview {
        try await get("v1/train/review", query: week.map { [URLQueryItem(name: "week", value: $0)] } ?? [])
    }

    func decideProposal(_ id: String, accept: Bool) async throws -> TrainReview {
        let body = try JSONSerialization.data(withJSONObject: ["accept": accept])
        let path = "v1/train/review/proposals/" + (id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(.init(charactersIn: "/"))) ?? id)
        return try Self.decoder.decode(TrainReview.self, from: await send(request("POST", path, body: body)))
    }

    /// The rider has seen these plan changes: they're not shown again.
    func seenChanges(_ ids: [Int]) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["ids": ids])
        _ = try await send(request("POST", "v1/train/changes/seen", body: body))
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

    /// When the morning brief arrives, "HH:MM" from 04:00 to 12:00.
    func zone2() async throws -> TrainZone2 { try await get("v1/train/zone2") }

    /// The rider's own zone 2 range ("126-138"), or nil to have it worked out again.
    func setZone2(_ range: String?) async throws -> Me {
        let body = try JSONSerialization.data(withJSONObject: ["zone2": range as Any? ?? NSNull()])
        return try Self.decoder.decode(Me.self, from: await send(request("PUT", "v1/me", body: body)))
    }

    func setBriefAt(_ time: String) async throws -> Me {
        let body = try JSONSerialization.data(withJSONObject: ["brief_at": time])
        return try Self.decoder.decode(Me.self, from: await send(request("PUT", "v1/me", body: body)))
    }

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

    // MARK: Planned routes

    func courses() async throws -> [Course] {
        struct List: Decodable { let courses: [Course] }
        let list: List = try await get("v1/courses")
        return list.courses
    }

    func course(_ id: Int) async throws -> Course { try await get("v1/courses/\(id)") }

    /// Upload a GPX (Ride with GPS, Komoot...); the server checks it in the background.
    func addCourse(gpx: Data, name: String?) async throws -> Course {
        var req = try request("POST", "v1/courses", query: name.map { [URLQueryItem(name: "name", value: $0)] } ?? [])
        req.httpBody = gpx
        req.setValue("application/gpx+xml", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 120
        return try Self.decoder.decode(Course.self, from: await send(req))
    }

    func courseOptions(_ id: Int) async throws -> CourseOptions { try await get("v1/courses/\(id)/options") }

    /// Loops from a description. Send the words first; then the "ask" that came back with answers to its
    /// questions. Returns what was understood and either the questions left, or the loops made.
    func planRoutes(text: String?, ask: [String: Any]?, answers: [String: Any] = [:]) async throws -> PlanResult {
        var body: [String: Any] = ["answers": answers]
        if let text { body["text"] = text }
        if let ask { body["ask"] = ask }
        var req = try request("POST", "v1/courses/plan", body: JSONSerialization.data(withJSONObject: body))
        req.timeoutInterval = 180
        let data = try await send(req)
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        let ask = obj["ask"] as? [String: Any] ?? [:]
        let questions = (obj["questions"] as? [[String: Any]] ?? []).map { q in
            PlanResult.Question(key: q["key"] as? String ?? "", text: q["q"] as? String ?? "",
                                hint: q["hint"] as? String, guess: q["guess"] as? String,
                                choices: (q["choices"] as? [Any] ?? []).map { c in
                                    if let pair = c as? [Any], pair.count == 2 { return "\(pair[0])–\(pair[1]) km" }
                                    if let d = c as? [String: Any], let label = d["label"] as? String { return label }
                                    return "\(c)"
                                },
                                // {"label", "value"} choices answer with the value (a place, or "stay").
                                raw: (q["choices"] as? [Any] ?? []).map { c in (c as? [String: Any])?["value"] ?? c })
        }
        var courses: [Course] = []
        if let list = obj["courses"] {
            courses = try Self.decoder.decode([Course].self, from: JSONSerialization.data(withJSONObject: list))
        }
        return PlanResult(ask: ask, tags: ask["tags"] as? [String] ?? [], notes: ask["notes"] as? [String] ?? [],
                          questions: questions, home: obj["home"] as? Bool ?? false, courses: courses)
    }

    /// One change: ["op": "length", "km": -10], ["op": "stop", "lat":, "lon":, "name":] or ["op": "start", ...].
    func tuneCourse(_ id: Int, _ op: [String: Any]) async throws -> Course {
        let body = try JSONSerialization.data(withJSONObject: op)
        var req = try request("POST", "v1/courses/\(id)/tune", body: body)
        req.timeoutInterval = 120
        return try Self.decoder.decode(Course.self, from: await send(req))
    }

    func undoCourse(_ id: Int) async throws -> Course {
        try Self.decoder.decode(Course.self, from: await send(request("POST", "v1/courses/\(id)/undo")))
    }

    // MARK: Home (GET/PUT/DELETE /v1/home)

    func home() async throws -> HomeInfo { try await get("v1/home") }

    func setHome(lat: Double, lon: Double, label: String) async throws -> HomeInfo {
        let body = try JSONSerialization.data(withJSONObject: ["lat": lat, "lon": lon, "label": label])
        return try Self.decoder.decode(HomeInfo.self, from: await send(request("PUT", "v1/home", body: body)))
    }

    /// Back to working home out from rides.
    func clearHome() async throws -> HomeInfo {
        try Self.decoder.decode(HomeInfo.self, from: await send(request("DELETE", "v1/home")))
    }

    func recheckCourse(_ id: Int) async throws {
        _ = try await send(request("POST", "v1/courses/\(id)/check"))
    }

    func renameCourse(_ id: Int, to name: String) async throws {
        _ = try await send(request("PATCH", "v1/courses/\(id)", body: JSONEncoder().encode(["name": name])))
    }

    func deleteCourse(_ id: Int) async throws {
        _ = try await send(request("DELETE", "v1/courses/\(id)"))
    }

    /// The course for a bike computer: "fit" (Garmin Edge, Wahoo) or "gpx".
    func courseFile(_ id: Int, kind: String) async throws -> Data {
        try await send(request("GET", "v1/courses/\(id)/course.\(kind)"))
    }


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

    /// The app opened: the server fetches new rides from Garmin (and other pulled sources) if it hasn't
    /// in the last 5 minutes. Returns how many new rides came in.
    func refreshSources() async throws -> Int {
        var req = try request("POST", "v1/refresh")
        req.timeoutInterval = 60
        let obj = try JSONSerialization.jsonObject(with: await send(req)) as? [String: Any]
        return (obj?["synced"] as? [String: Any] ?? [:]).values.compactMap { $0 as? Int }.reduce(0, +)
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

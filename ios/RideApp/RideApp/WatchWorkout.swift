import Foundation
import HealthKit
import SwiftUI
import WorkoutKit

/// Sessions on the rider's Apple Watch (23 Nov 2026, docs/train-method.md "following a session"): each session
/// becomes a custom workout in the Watch's Workout app, with every step timed, its watts as a range the Watch
/// nudges you back into, and a tap on the wrist at each change. No phone to look at, and the ride records as the
/// rider's own Watch Cycling workout as always, so the merge and the jobs reading don't change.
///
/// One session in the engine, one sender per device: this is the Apple Watch's. Garmin (Training API), Wahoo
/// and Hammerhead follow when we connect them; spoken cues on the phone (RideAlong.swift) work for everyone.
enum WatchWorkout {
    /// The session as a Watch workout: warm-up, each set as a block of work and recovery repeated, the riding
    /// between sets as blocks of their own, cool-down. nil for off-bike sessions or ones without steps.
    static func plan(for s: PlanSession) -> WorkoutPlan? {
        guard !s.offBike, !s.steps.isEmpty else { return nil }
        var steps = s.steps
        let warm = steps.first?.label == "Warm up" ? steps.removeFirst() : nil
        let cool = steps.count > 0 && steps.last?.label == "Cool down" ? steps.removeLast() : nil
        var blocks: [IntervalBlock] = []
        for st in steps {
            if let inner = st.steps, let n = st.repeat {
                // A set: its steps repeated. A set of sets (over-unders) flattens the inner set into the block.
                let flat = inner.flatMap(\.flat)
                blocks.append(IntervalBlock(steps: flat.map(interval), iterations: max(1, n)))
            } else {
                blocks.append(IntervalBlock(steps: [interval(st)], iterations: 1))
            }
        }
        let w = CustomWorkout(activity: .cycling, location: s.indoor ? .indoor : .outdoor, displayName: s.title,
                              warmup: warm.map { step($0, alert: false) }, blocks: blocks,
                              cooldown: cool.map { step($0, alert: false) })
        return WorkoutPlan(.custom(w))
    }

    /// Easy steps are recovery; everything else is work, with its watts (or heart rate) as the range to hold.
    private static func interval(_ st: PlanStep) -> IntervalStep {
        let easy = ["Z1", "Z2"].contains(st.zone ?? "")
        return IntervalStep(easy ? .recovery : .work, step: step(st, alert: !easy))
    }

    private static func step(_ st: PlanStep, alert: Bool) -> WorkoutStep {
        let goal: WorkoutGoal = (st.seconds ?? 0) > 0 ? .time(st.seconds ?? 0, .seconds) : .open
        var a: (any WorkoutAlert)?
        if alert, let w = st.target?.watts, w.count == 2, w[1] > w[0] {
            a = .power(Double(w[0])...Double(w[1]), unit: .watts)
        } else if alert, let h = st.target?.hr, h.count == 2, h[1] > h[0] {
            a = .heartRate(Double(h[0])...Double(h[1]))
        }
        if let alert = a, !CustomWorkout.supportsAlert(alert, activity: .cycling) { a = nil }
        if #available(iOS 18.0, *) { return WorkoutStep(goal: goal, alert: a, displayName: name(st)) }
        return WorkoutStep(goal: goal, alert: a)
    }

    /// What the Watch shows for the step: "Hard 188–245 W", "Recover", "Sweet spot 140–149 W".
    private static func name(_ st: PlanStep) -> String? {
        guard let label = st.label else { return nil }
        if let w = st.target?.watts, w.count == 2, !["Z1", "Z2"].contains(st.zone ?? "") {
            return "\(label) \(w[0])–\(w[1]) W"
        }
        return label
    }

    /// When the session waits on the Watch: its day, from early that morning (24 Nov 2026). Apple asks for a time,
    /// but a scheduled workout can be started whenever you like; the time only orders them and sets the reminder.
    /// So it's the morning brief's time (06:00 unless the rider changed it): there before any ride, never late.
    static func when(_ s: PlanSession, at early: String = "06:00") -> DateComponents? {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm"
        f.locale = Locale(identifier: "en_US_POSIX")
        guard let d = f.date(from: "\(s.onDate) \(early)") else { return nil }
        return Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: d)
    }

    /// The rider's morning brief time, for when(_:at:).
    static func early() async -> String { (try? await APIClient().me().briefAt) ?? "06:00" }
}

/// Puts sessions on the Watch: one when the rider taps "Send to Apple Watch", or, with the setting on, the
/// coming week's every time Kova opens, so the Watch always has the plan as it is now (it re-plans after rides).
@MainActor
final class WatchSessions: ObservableObject {
    static let shared = WatchSessions()
    static let autoKey = "watch.sessions"

    @Published var auto: Bool = UserDefaults.standard.bool(forKey: WatchSessions.autoKey)

    static var supported: Bool { WorkoutScheduler.isSupported }

    enum Outcome: Equatable { case sent(String), failed(String) }

    /// Ask once (Apple's own prompt: "Allow Kova to send workouts to your Watch").
    private func authorized() async -> Bool {
        let s = WorkoutScheduler.shared
        switch await s.authorizationState {
        case .authorized: return true
        case .notDetermined: return await s.requestAuthorization() == .authorized
        default: return false
        }
    }

    /// One session, on its day; gives up after 20 seconds rather than spinning (no Watch paired, say).
    func send(_ s: PlanSession) async -> Outcome {
        await withTaskGroup(of: Outcome?.self) { group in
            group.addTask { await self.sendNow(s) }
            group.addTask {
                try? await Task.sleep(nanoseconds: 20_000_000_000)
                return nil
            }
            let first = await group.next() ?? nil
            group.cancelAll()
            return first ?? .failed("Couldn't reach your Apple Watch. Check it's paired with this iPhone and nearby, then try again.")
        }
    }

    private func sendNow(_ s: PlanSession) async -> Outcome {
        guard Self.supported else { return .failed("This iPhone can't send workouts to an Apple Watch.") }
        guard let plan = WatchWorkout.plan(for: s), let at = WatchWorkout.when(s, at: await WatchWorkout.early()) else {
            return .failed("This session has no steps to send.")
        }
        guard await authorized() else {
            return .failed("Kova isn't allowed to send workouts to your Watch. Turn it on in Settings › Kova.")
        }
        // A session sent again replaces itself rather than appearing twice.
        for old in await WorkoutScheduler.shared.scheduledWorkouts where old.date == at {
            await WorkoutScheduler.shared.remove(old.plan, at: old.date)
        }
        await WorkoutScheduler.shared.schedule(plan, at: at)
        return .sent(s.title)
    }

    func setAuto(_ on: Bool) async {
        auto = on
        UserDefaults.standard.set(on, forKey: Self.autoKey)
        if on { await sync(force: true) } else { await WorkoutScheduler.shared.removeAllWorkouts() }
    }

    private var lastSync: Date?

    /// The next 7 days' riding sessions, on the days this week's fresh layout has them, so a different session
    /// than the day's is there too if the rider feels like it. Kova's scheduled workouts are only its own, so
    /// clearing them first leaves nothing stale behind.
    func sync(force: Bool = false) async {
        guard auto, Self.supported else { return }
        if !force, let last = lastSync, Date().timeIntervalSince(last) < 600 { return }
        guard await authorized(), let plan = try? await APIClient().plan() else { return }
        lastSync = Date()
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        let today = f.string(from: Date())
        let end = f.string(from: Calendar.current.date(byAdding: .day, value: 7, to: Date()) ?? Date())
        let coming = plan.weeks.flatMap(\.sessions)
            .filter { !$0.offBike && $0.status != "done" && $0.dropped == nil && $0.foldedInto == nil
                      && $0.onDate >= today && $0.onDate < end }
            .prefix(max(1, WorkoutScheduler.maxAllowedScheduledWorkoutCount))
        let early = await WatchWorkout.early()
        await WorkoutScheduler.shared.removeAllWorkouts()
        for s in coming {
            if let p = WatchWorkout.plan(for: s), let at = WatchWorkout.when(s, at: early) {
                await WorkoutScheduler.shared.schedule(p, at: at)
            }
        }
    }
}

/// On the session's page: send it to the Watch, and say where to find it.
struct SendToWatch: View {
    let session: PlanSession
    @ObservedObject private var watch = WatchSessions.shared
    @State private var outcome: WatchSessions.Outcome?
    @State private var sending = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                Task {
                    sending = true
                    outcome = await watch.send(session)
                    sending = false
                }
            } label: {
                Label(sending ? "Sending…" : "Send to Apple Watch", systemImage: "applewatch")
            }
            .buttonStyle(SecondaryButton()).disabled(sending)
            switch outcome {
            case .sent(let title):
                Text("On your Watch: open Workout, scroll down to Scheduled and start \(title). It taps your wrist at every step and nudges you when the watts drift.")
                    .font(Theme.text(13)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
                if !watch.auto {
                    Button("Send every session automatically") { Task { await watch.setAuto(true) } }
                        .font(Theme.text(13, .medium)).foregroundStyle(Theme.cobalt)
                }
            case .failed(let why):
                Text(why).font(Theme.text(13)).foregroundStyle(Theme.heart).fixedSize(horizontal: false, vertical: true)
            case nil:
                EmptyView()
            }
        }
    }
}

/// In Settings: the coming week's sessions on the Watch, kept up to date as the plan changes.
struct WatchSettingsCard: View {
    @ObservedObject private var watch = WatchSessions.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            MonoLabel("Following a session").padding(.bottom, 4)
            Toggle("Sessions on my Apple Watch", isOn: Binding(get: { watch.auto },
                                                               set: { on in Task { await watch.setAuto(on) } }))
                .font(Theme.text(15)).tint(Theme.cobalt).frame(minHeight: 44)
            Text("The coming week's sessions wait in the Watch's Workout app, under Scheduled, from the time of your morning brief, and change when your plan does. Start any of them whenever you ride, instead of a plain Cycling workout: the Watch taps your wrist at every step.")
                .font(Theme.text(12)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true).padding(.top, 6)
        }
        .padding(16).surfaceCard(radius: 22)
    }
}

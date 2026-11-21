import SwiftUI

// The Train tab (docs/train-tab.md, step 3): the plan and the coach in one. Today leads: the next session big
// (or rest, with the same weight), why, how it should feel, and a sentence about what's next. The words follow
// docs/train-words.md: every card says whether it's a fact (What you did), how a ride was filed (Counted as),
// what it means for the goal (What it means), the next step (What's next) or coaching (One thing to try).
// Rule-based words for now; the AI coach writes in the same format later (step 5).

private let summit = Theme.stripes[3]

struct TrainView: View {
    @EnvironmentObject var model: AppModel
    @State private var settingGoal = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    header
                    StatusLine()
                    if let t = model.today, t.state != "no_plan" {
                        if let g = t.greeting { CoachLine(text: g) }
                        TodayCard(today: t, plan: model.plan)
                        if let then = t.then, !then.isEmpty { NextCard(text: then, moved: t.moved ?? []) }
                        if let note = t.latest { LatestRideCard(note: note) }
                        NavigationLink { TrainWeekView() } label: { WeekRow(plan: model.plan) }
                            .buttonStyle(.plain)
                        if let goal = t.goal { GoalCard(goal: goal) }
                        Text("Training guidance from your own data, not medical advice.")
                            .font(Theme.mono(11)).foregroundStyle(Theme.label).padding(.horizontal, 4)
                    } else if !model.isLoading {
                        Button { settingGoal = true } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Set a goal and your training appears here").font(Theme.text(16, .semibold))
                                    .foregroundStyle(Theme.ink)
                                Text("Tell Kova what you want from your riding. Each day it shows the session that gets you there, or rest, and why.")
                                    .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                            }
                            .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 16)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 24)
            }
            .background(Theme.ground.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
            .refreshable { await model.refresh() }
            .sheet(isPresented: $settingGoal) { GoalFlow() }
        }
    }

    private var header: some View {
        HStack(alignment: .center) {
            MonoLabel(headline)
            Spacer()
            if model.plan != nil {
                NavigationLink { PlanView(embedded: true) } label: {
                    Image(systemName: "calendar").font(.system(size: 20)).frame(width: 44, height: 44)
                }
                .accessibilityLabel("The plan ahead")
            }
        }
        .padding(.horizontal, 4).padding(.top, 8)
    }

    private var headline: String {
        let day = Date().formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))
        guard let t = model.today, let w = t.week, let n = t.weeks else { return day }
        return w == 0 ? "\(day) · plan starts soon" : "\(day) · week \(w) of \(n)"
    }
}

/// The coach's opening line, beside the Kova mark.
struct CoachLine: View {
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            CoachMark()
            Text(text).font(Theme.text(16)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 4)
    }
}

struct CoachMark: View {
    var size: CGFloat = 32

    var body: some View {
        ZStack {
            Circle().fill(Theme.panel)
            KovaMark(size: size * 0.5)
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// A small label over a block of words, in the words guide's order.
private struct Labelled: View {
    let label: String
    let text: String
    var labelColor: Color = Theme.label
    var textColor: Color = Theme.inkSoft

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            MonoLabel(label, color: labelColor)
            Text(text).font(Theme.text(15)).foregroundStyle(textColor).fixedSize(horizontal: false, vertical: true)
        }
    }
}

// MARK: - Today

struct TodayCard: View {
    let today: TrainToday
    let plan: TrainingPlan?

    var body: some View {
        switch today.state {
        case "session": if let s = today.session { session(s) }
        case "done": done
        default: rest
        }
    }

    private func session(_ s: PlanSession) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            MonoLabel("Today · \(PlanText.duration(s.seconds)) · indoors or out", color: Theme.panelLabel)
            VStack(alignment: .leading, spacing: 6) {
                Text(s.title).font(Theme.heading(52)).foregroundStyle(.white)
                if let line = TrainText.line(s) {
                    Text(line).font(Theme.text(15)).foregroundStyle(.white.opacity(0.88)).fixedSize(horizontal: false, vertical: true)
                }
            }
            if !s.steps.isEmpty { IntervalChart(steps: s.steps).frame(height: 64) }
            Rectangle().fill(Theme.panelLine).frame(height: 1)
            if let feel = today.feel { Labelled(label: "How it should feel", text: feel, labelColor: summit, textColor: .white.opacity(0.88)) }
            if let why = today.why, !why.isEmpty { Labelled(label: "Why", text: why, labelColor: summit, textColor: .white.opacity(0.88)) }
            if let where_ = today.where_ {   // indoors or out is the rider's choice: advice only
                Text(where_).font(Theme.text(13)).foregroundStyle(Theme.panelLabel).fixedSize(horizontal: false, vertical: true)
            }
            NavigationLink { SessionDetail(session: s, plan: plan) } label: {
                HStack(spacing: 6) {
                    Text("The session, step by step").font(Theme.text(14, .medium))
                    Image(systemName: "chevron.right").font(.system(size: 12, weight: .semibold))
                }
                .foregroundStyle(Theme.panelLabel).frame(minHeight: 32)
            }
        }
        .padding(18).frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private var rest: some View {
        VStack(alignment: .leading, spacing: 14) {
            MonoLabel("Today · rest day", color: Theme.cobalt)
            VStack(alignment: .leading, spacing: 6) {
                Text("Rest").font(Theme.heading(52)).foregroundStyle(Theme.ink)
                Text("No riding today. Rest is a session too.").font(Theme.text(15)).foregroundStyle(Theme.ink)
            }
            if let why = today.why, !why.isEmpty { Labelled(label: "Why", text: why, labelColor: Theme.cobalt, textColor: Theme.ink) }
        }
        .padding(18).frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.cobaltSoft, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private var done: some View {
        VStack(alignment: .leading, spacing: 14) {
            MonoLabel("Today · done", color: Theme.cobalt)
            VStack(alignment: .leading, spacing: 6) {
                Text("Ride's in").font(Theme.heading(52)).foregroundStyle(Theme.ink)
                if let why = today.why { Text(why).font(Theme.text(15)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true) }
            }
        }
        .padding(18).frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.cobaltSoft, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }
}

struct NextCard: View {
    let text: String
    let moved: [TrainToday.Moved]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Labelled(label: "What's next", text: text)
            if !moved.isEmpty {
                Text("Moved to fit the week: " + moved.map { m in
                    "\(m.title) to \(GoalText.date(m.to)?.formatted(.dateTime.weekday(.wide)) ?? m.to)"
                }.joined(separator: ", ") + ".")
                .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
    }
}

/// The latest ride's note in brief, opening the full note.
struct LatestRideCard: View {
    let note: TrainNote

    var body: some View {
        NavigationLink { RideNoteView(rideId: note.rideId, initial: note) } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    MonoLabel("After your ride · \(note.day?.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated)) ?? note.date)")
                    Spacer()
                    Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(Theme.label)
                }
                if let c = note.counted {
                    Text("Counted as \(c.title)").font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                } else if let k = note.kindTitle {
                    Text(k).font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                }
                if let first = note.means.first {
                    Text(first).font(Theme.text(14)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
                }
                if let tip = note.tips.first {
                    HStack(spacing: 6) {
                        MonoLabel("One thing to try", color: Theme.inkSoft)
                        Text(tip.title).font(Theme.text(14, .medium)).foregroundStyle(Theme.ink)
                    }
                    .padding(.horizontal, 10).padding(.vertical, 8)
                    .background(Theme.sand, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            }
            .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

private struct WeekRow: View {
    let plan: TrainingPlan?

    var body: some View {
        let week = plan?.thisWeek.flatMap { w in plan?.weeks.first { $0.index == w } }
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                MonoLabel("This week" + (week.map { " · \(PlanText.phase($0.phase))" } ?? ""))
                Text(week.map { "\($0.done) of \($0.total) done, any order" } ?? "See how your rides counted")
                    .font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
            }
            Spacer()
            Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(Theme.label)
        }
        .padding(16).surfaceCard(radius: 22).contentShape(Rectangle())
    }
}

struct GoalCard: View {
    let goal: TrainGoal

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                MonoLabel("Your goal")
                Spacer()
                if let w = goal.weeksLeft, let r = goal.readyBy.flatMap(GoalText.date) {
                    MonoLabel("\(w) weeks to \(r.formatted(.dateTime.day().month(.abbreviated)))")
                }
            }
            if let t = goal.title { Text(t).font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink) }
            ForEach(goal.markers) { m in
                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(m.name).font(Theme.text(14, .semibold)).foregroundStyle(Theme.ink)
                        Spacer()
                        Text(markerFigures(m)).font(Theme.mono(12)).foregroundStyle(m.reached ? Theme.cobalt : Theme.inkMuted)
                    }
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule().fill(Theme.surfaceSelected)
                            Capsule().fill(Theme.cobalt).frame(width: max(8, geo.size.width * m.progress))
                        }
                    }
                    .frame(height: 8)
                    Text(m.reached ? "\(m.meaning.components(separatedBy: ":").first ?? m.meaning). Past your aim already."
                                   : m.meaning.components(separatedBy: ":").first ?? m.meaning)
                        .font(Theme.text(12)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
    }

    private func markerFigures(_ m: TrainGoal.Marker) -> String {
        let cur = m.current.map { "\(Int($0)) \(m.unit)" } ?? "—"
        let aim = m.target.map { "aim \(Int($0))" } ?? ""
        return [cur, aim].filter { !$0.isEmpty }.joined(separator: " · ") + (m.reached ? " ✓" : "")
    }
}

enum TrainText {
    /// A session in one plain line, from its main set: "6 × 1 min hard / 2 min easy, inside 60 min".
    static func line(_ s: PlanSession) -> String? {
        if let set = s.steps.first(where: { $0.set != nil })?.set {
            return "\(set), inside \(PlanText.duration(s.seconds))."
        }
        return s.offBike ? s.purpose : nil
    }

    static func day(_ iso: String) -> String {
        GoalText.date(iso)?.formatted(.dateTime.weekday(.abbreviated).day()) ?? iso
    }
}

// MARK: - After a ride

struct RideNoteView: View {
    @EnvironmentObject var model: AppModel
    let rideId: String
    var initial: TrainNote?
    @State private var note: TrainNote?
    @State private var moreTips = false
    @State private var changing = false
    @State private var error: String?

    var body: some View {
        ScrollView {
            if let n = note ?? initial {
                VStack(alignment: .leading, spacing: 12) {
                    MonoLabel(n.day?.formatted(.dateTime.weekday(.wide).day().month(.wide)) ?? n.date)
                        .padding(.horizontal, 4)
                    Text(title(n)).font(Theme.heading(40)).foregroundStyle(Theme.ink).padding(.horizontal, 4)
                        .fixedSize(horizontal: false, vertical: true)
                    did(n)
                    counted(n)
                    if !n.means.isEmpty { card { Labelled(label: "What it means", text: n.means.joined(separator: " ")) } }
                    if let next = n.next, !next.isEmpty { card { Labelled(label: "What's next", text: next) } }
                    if let tip = n.tips.first { tips(n, first: tip) }
                    if let error { Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart) }
                }
                .padding(16)
            } else {
                ProgressView().padding(40)
            }
        }
        .background(Theme.ground.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .task { await load() }
        .sheet(isPresented: $changing) {
            if let n = note ?? initial { CountAsSheet(note: n) { await load(); await model.refresh() } }
        }
    }

    private func load() async {
        do { note = try await APIClient().rideNote(rideId) } catch { if note == nil && initial == nil { self.error = error.localizedDescription } }
    }

    private func title(_ n: TrainNote) -> String {
        if let best = n.means.first, best.hasPrefix("Best minute") { return "Your best minute yet" }
        if let best = n.means.first, best.contains("your best yet") { return best.components(separatedBy: ":").first.map { "\($0) yet" } ?? best }
        if let c = n.counted { return c.title }
        return n.kindTitle ?? "Your ride"
    }

    private func did(_ n: TrainNote) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            MonoLabel("What you did", color: Theme.panelLabel)
            HStack(alignment: .top, spacing: 8) {
                stat(Format.number(n.did.km, decimals: 1), n.indoor == true ? "km indoors" : "km")
                if let a = n.did.ascentM, a >= 1 { stat("\(Int(a))", "m climbed") } else { stat("\(n.did.minutes)", "minutes") }
                if let b = n.did.bestMinute { stat("\(Int(b))", "W best minute", highlight: n.means.contains { $0.hasPrefix("Best minute") }) }
                else if let p = n.did.avgPower { stat("\(Int(p))", "W average") }
                else if let h = n.did.avgHr { stat("\(Int(h))", "bpm average") }
            }
        }
        .padding(18).frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private func stat(_ value: String, _ label: String, highlight: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value).font(Theme.hero(28)).foregroundStyle(highlight ? summit : .white).lineLimit(1).minimumScaleFactor(0.6)
            MonoLabel(label, color: Theme.panelLabel)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func counted(_ n: TrainNote) -> some View {
        card {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    MonoLabel("Counted as")
                    Spacer()
                    Button("Change") { changing = true }.font(Theme.text(13, .medium)).foregroundStyle(Theme.cobalt)
                }
                if let c = n.counted {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(c.title).font(Theme.text(17, .semibold)).foregroundStyle(Theme.ink)
                        if let p = c.plannedFor { Text("· planned for \(p)").font(Theme.text(14)).foregroundStyle(Theme.inkMuted) }
                        if c.byHand { Text("· by you").font(Theme.text(14)).foregroundStyle(Theme.inkMuted) }
                    }
                } else {
                    Text("Extra riding").font(Theme.text(17, .semibold)).foregroundStyle(Theme.ink)
                }
                if let r = n.counted?.reason ?? n.reason {
                    Text(r).font(Theme.text(14)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
                }
                if n.counted == nil, let k = n.kindTitle {
                    Text("It was \(k.lowercased()) riding, but no open session this week needed it.")
                        .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func tips(_ n: TrainNote, first: TrainNote.Tip) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            MonoLabel("One thing to try", color: Theme.inkSoft)
            ForEach(moreTips ? n.tips : [first]) { t in
                VStack(alignment: .leading, spacing: 4) {
                    Text(t.title).font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                    Text(t.text).font(Theme.text(14)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
                }
            }
            if n.tips.count > 1 && !moreTips {
                Button("One more: \(n.tips[1].title.lowercased())") { withAnimation { moreTips = true } }
                    .font(Theme.text(13, .medium)).foregroundStyle(Theme.inkSoft).underline()
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.sand, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    private func card<C: View>(@ViewBuilder _ content: () -> C) -> some View {
        content().padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
    }
}

/// Count a ride as a different session of its week, as none, or back to automatic.
private struct CountAsSheet: View {
    @Environment(\.dismiss) private var dismiss
    let note: TrainNote
    let changed: () async -> Void
    @State private var week: TrainWeek?
    @State private var error: String?

    var body: some View {
        NavigationStack {
            List {
                if let week {
                    Section {
                        ForEach(week.sessions.filter { !$0.offBike }) { s in
                            Button { Task { await set(s.id) } } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(s.title).font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                                        Text("Planned \(TrainText.day(s.date))").font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                                    }
                                    Spacer()
                                    if note.counted?.sessionId == s.id { Image(systemName: "checkmark").foregroundStyle(Theme.cobalt) }
                                }
                            }
                        }
                    } footer: {
                        Text("Kova counts each ride as the session it fits best, by what it contained. Change it if it got it wrong.")
                    }
                    Section {
                        Button("Doesn't count as a session") { Task { await set(nil) } }
                        Button("Let Kova decide") { Task { await automatic() } }
                    }
                } else {
                    ProgressView()
                }
                if let error { Text(error).foregroundStyle(Theme.heart) }
            }
            .navigationTitle("Counts as")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .task { await load() }
        }
        .tint(Theme.cobalt)
        .presentationDetents([.medium, .large])
    }

    private func load() async {
        guard let day = note.day else { return }
        let monday = Calendar(identifier: .iso8601).dateInterval(of: .weekOfYear, for: day)?.start ?? day
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"
        do { week = try await APIClient().trainWeek(start: f.string(from: monday)) } catch { self.error = error.localizedDescription }
    }

    private func set(_ id: String?) async {
        do { try await APIClient().countRide(note.rideId, as: id); await changed(); dismiss() } catch { self.error = error.localizedDescription }
    }

    private func automatic() async {
        do { try await APIClient().countRide(note.rideId, as: nil, automatic: true); await changed(); dismiss() }
        catch { self.error = error.localizedDescription }
    }
}

// MARK: - The week, as counted

struct TrainWeekView: View {
    @EnvironmentObject var model: AppModel
    var start: String?
    @State private var week: TrainWeek?
    @State private var error: String?

    var body: some View {
        ScrollView {
            if let w = week {
                VStack(alignment: .leading, spacing: 12) {
                    MonoLabel("Week \(w.index) · \(PlanText.phase(w.phase)) · \(range(w))").padding(.horizontal, 4)
                    Text(w.done >= w.total ? "All done" : "\(w.done) of \(w.total) done")
                        .font(Theme.heading(42)).foregroundStyle(Theme.ink).padding(.horizontal, 4)
                    Text("Each ride counts as the session it fits best, by what you actually did, whatever the day.")
                        .font(Theme.text(15)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, 4)
                    VStack(spacing: 0) {
                        ForEach(Array(w.sessions.enumerated()), id: \.element.id) { i, s in
                            row(s, w)
                            if i < w.sessions.count - 1 { Rectangle().fill(Theme.line).frame(height: 1) }
                        }
                    }
                    .padding(.horizontal, 16).surfaceCard(radius: 22)
                    if !w.extra.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            MonoLabel("Extra riding")
                            ForEach(w.extra) { x in
                                NavigationLink { RideNoteView(rideId: x.rideId) } label: {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(x.kindTitle ?? "A ride").font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
                                        if let r = x.reason { Text(r).font(Theme.text(13)).foregroundStyle(Theme.inkMuted) }
                                    }
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
                    }
                    VStack(alignment: .leading, spacing: 6) {
                        MonoLabel("If a week goes sideways", color: Theme.panelLabel)
                        Text("A missed hard session moves to the next free day; a missed easy one just drops. Rest days stay between hard ones.")
                            .font(Theme.text(14)).foregroundStyle(.white.opacity(0.88)).fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(16).frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                }
                .padding(16)
            } else if let error {
                Text(error).font(Theme.text(14)).foregroundStyle(Theme.heart).padding(16)
            } else {
                ProgressView().padding(40)
            }
        }
        .background(Theme.ground.ignoresSafeArea())
        .navigationTitle("The week")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .task {
            do { week = try await APIClient().trainWeek(start: start) } catch { self.error = error.localizedDescription }
        }
    }

    private func range(_ w: TrainWeek) -> String {
        guard let s = GoalText.date(w.weekStart), let e = Calendar.current.date(byAdding: .day, value: 6, to: s) else { return "" }
        return "\(s.formatted(.dateTime.day().month(.abbreviated)))–\(e.formatted(.dateTime.day().month(.abbreviated)))"
    }

    @ViewBuilder private func row(_ s: PlanSession, _ w: TrainWeek) -> some View {
        let done = s.status == "done"
        let content = HStack(alignment: .top, spacing: 12) {
            ZStack {
                Circle().fill(done ? Theme.cobalt : .clear)
                Circle().stroke(done ? Theme.cobalt : s.status == "missed" ? Theme.heart : Theme.label, lineWidth: 1.5)
                if done { Image(systemName: "checkmark").font(.system(size: 12, weight: .bold)).foregroundStyle(.white) }
            }
            .frame(width: 26, height: 26)
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline) {
                    Text(s.title).font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                    Spacer()
                    MonoLabel(dayLine(s, w))
                }
                if let c = s.counted, let r = c.reason {
                    Text(r).font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                } else if s.status == "missed" {
                    Text("No ride fitted it this week.").font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                } else if !done {
                    Text(s.offBike ? s.purpose : TrainText.line(s) ?? "").font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(.vertical, 14).contentShape(Rectangle())
        if let c = s.counted {
            NavigationLink { RideNoteView(rideId: c.rideId) } label: { content }.buttonStyle(.plain)
        } else {
            NavigationLink { SessionDetail(session: s, plan: model.plan) } label: { content }.buttonStyle(.plain)
        }
    }

    private func dayLine(_ s: PlanSession, _ w: TrainWeek) -> String {
        if let c = s.counted {
            return c.date == s.date ? TrainText.day(c.date) : "\(TrainText.day(c.date)) · planned \(TrainText.day(s.date))"
        }
        if let to = w.schedule[s.id], to != s.date { return "now \(TrainText.day(to))" }
        return TrainText.day(s.date)
    }
}

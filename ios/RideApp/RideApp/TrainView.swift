import SwiftUI

// The Train tab (docs/train-tab.md, step 3): the plan and the coach in one. Today leads with one hero for the
// day (the session, rest, or the ride you've just done), its key numbers in the dot-matrix hero type, then what's
// next, the week as a strip, and the goal. The words follow docs/train-words.md: every card says whether it's a
// fact, how a ride was filed, what it means for the goal, the next step, or coaching. Rule-based words for now;
// the AI coach writes in the same format later (step 5). Design pass 21 Nov 2026: fewer words, more impact.

private let summit = Theme.stripes[3]

struct TrainView: View {
    @EnvironmentObject var model: AppModel
    @ObservedObject private var coach = CoachNotifier.shared
    @State private var settingGoal = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    header
                    StatusLine()
                    if let t = model.today, t.state != "no_plan" {
                        if let g = t.greeting { CoachLine(text: g) }
                        TodayHero(today: t, plan: model.plan)
                        if let then = t.then, !then.isEmpty { NextCard(text: then, moved: t.moved ?? []) }
                        if t.state != "done", let note = t.latest { LatestRideCard(note: note) }
                        if let days = t.days, !days.isEmpty {
                            NavigationLink { TrainWeekView() } label: { WeekStrip(days: days, done: t.done, total: t.total, phase: t.phase) }
                                .buttonStyle(.plain)
                        }
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
            .task { await coach.askPermissionOnce() }
            // A tapped coach notification: the ride's note, or the week; "today" is Train itself.
            .navigationDestination(item: Binding(get: { coach.route == .today ? nil : coach.route },
                                                 set: { coach.route = $0 })) { route in
                switch route {
                case .ride(let id): RideNoteView(rideId: id)
                case .week(let start): TrainWeekView(start: start)
                case .today: EmptyView()
                }
            }
            .onChange(of: coach.route) { _, r in if r == .today { coach.route = nil } }
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

/// The coach's opening line, beside the Kova mark: in ink, so it reads as the coach speaking.
struct CoachLine: View {
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            CoachMark()
            Text(text).font(Theme.text(16)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
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

/// A small label over a line of words, in the words guide's order.
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

/// A key number in the dot-matrix hero type, with its label under it.
private struct HeroNumber: View {
    let value: String
    let label: String
    var color: Color = .white
    var labelColor: Color = Theme.panelLabel

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(value).font(Theme.hero(30)).foregroundStyle(color).lineLimit(1).minimumScaleFactor(0.55)
            MonoLabel(label, color: labelColor).lineLimit(1).minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Today

struct TodayHero: View {
    let today: TrainToday
    let plan: TrainingPlan?
    @State private var showWhere = false

    var body: some View {
        switch today.state {
        case "session": if let s = today.session { session(s) }
        case "done":
            if let note = today.latest { DoneHero(note: note, why: today.why) } else { rest(done: true) }
        default: rest(done: false)
        }
    }

    private func session(_ s: PlanSession) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .firstTextBaseline) {
                MonoLabel("Today", color: Theme.panelLabel)
                Spacer()
                if today.where_ != nil {
                    Button { withAnimation { showWhere.toggle() } } label: {
                        HStack(spacing: 4) {
                            Text("Indoors or out").font(Theme.mono(11)).tracking(11 * 0.12)
                            Image(systemName: showWhere ? "chevron.up" : "info.circle").font(.system(size: 11))
                        }
                        .foregroundStyle(Theme.panelLabel).padding(.horizontal, 10).padding(.vertical, 5)
                        .overlay(Capsule().stroke(Theme.panelLine))
                    }
                    .buttonStyle(.plain)
                }
            }
            Text(s.title).font(Theme.heading(56)).foregroundStyle(.white).padding(.top, -6)
            HStack(alignment: .top, spacing: 8) {
                ForEach(Array(TrainText.numbers(s).enumerated()), id: \.offset) { _, n in
                    HeroNumber(value: n.value, label: n.label, color: n.accent ? summit : .white)
                }
            }
            if !s.steps.isEmpty { SessionShapeChart(steps: s.steps).frame(height: 56) }
            if showWhere, let w = today.where_ {
                Text(w).font(Theme.text(13)).foregroundStyle(Theme.panelLabel).fixedSize(horizontal: false, vertical: true)
            }
            Rectangle().fill(Theme.panelLine).frame(height: 1)
            if let feel = today.feel { line("Feel", TrainText.feelWords(feel)) }
            if let why = today.why, !why.isEmpty { line("Why", why) }
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

    /// One compact line: a yellow label, then the words.
    private func line(_ label: String, _ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            MonoLabel(label, color: summit).frame(width: 40, alignment: .leading)
            Text(text).font(Theme.text(15)).foregroundStyle(.white.opacity(0.9)).fixedSize(horizontal: false, vertical: true)
        }
    }

    private func rest(done: Bool) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            MonoLabel(done ? "Today · done" : "Today · rest day", color: Theme.cobalt)
            Text(done ? "Ride's in" : "Rest").font(Theme.heading(56)).foregroundStyle(Theme.ink)
            if !done {
                Text("No riding today. Rest is a session too.").font(Theme.text(15, .medium)).foregroundStyle(Theme.ink)
            }
            if let why = today.why, !why.isEmpty {
                Text(why).font(Theme.text(15)).foregroundStyle(Theme.ink.opacity(0.85)).fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(18).frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.cobaltSoft, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }
}

/// When you've ridden today, the ride itself is the hero: what it was, its numbers, what it counted as, and the
/// one thing to try. Opens the full note.
private struct DoneHero: View {
    let note: TrainNote
    let why: String?

    var body: some View {
        NavigationLink { RideNoteView(rideId: note.rideId, initial: note) } label: {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    MonoLabel("Today · ride's in", color: Theme.panelLabel)
                    Spacer()
                    Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(Theme.panelLabel)
                }
                let title = TrainText.noteTitle(note)
                Text(title).font(Theme.heading(title.count > 26 ? 34 : 44)).foregroundStyle(.white)
                    .fixedSize(horizontal: false, vertical: true).multilineTextAlignment(.leading)
                HStack(alignment: .top, spacing: 8) {
                    ForEach(Array(TrainText.numbers(note).enumerated()), id: \.offset) { _, n in
                        HeroNumber(value: n.value, label: n.label, color: n.accent ? summit : .white)
                    }
                }
                Rectangle().fill(Theme.panelLine).frame(height: 1)
                if let c = note.counted {
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        MonoLabel("Counted as", color: summit)
                        Text(c.title + (c.plannedFor.map { " · planned \($0)" } ?? ""))
                            .font(Theme.text(15, .medium)).foregroundStyle(.white)
                    }
                }
                if let tip = note.tips.first {
                    HStack(spacing: 8) {
                        MonoLabel("Try", color: Theme.inkSoft)
                        Text(tip.title).font(Theme.text(14, .semibold)).foregroundStyle(Theme.ink)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 12).padding(.vertical, 10)
                    .background(Theme.sand, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            }
            .padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// The session's shape in the brand's colours: the work in the summit's yellow, easy riding in soft greys, as
/// wide as each step is long and as tall as it is hard.
struct SessionShapeChart: View {
    let steps: [PlanStep]

    var body: some View {
        let flat = steps.flatMap(\.flat)
        let total = max(1, flat.reduce(0) { $0 + ($1.seconds ?? 0) })
        GeometryReader { geo in
            HStack(alignment: .bottom, spacing: 1) {
                ForEach(Array(flat.enumerated()), id: \.offset) { _, s in
                    RoundedRectangle(cornerRadius: 2)
                        .fill(color(s.zone))
                        .frame(width: max(1, geo.size.width * CGFloat((s.seconds ?? 0) / total) - 1),
                               height: max(6, geo.size.height * CGFloat(min(1, PlanText.intensity(s) / 1.3))))
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .bottomLeading)
        }
        .accessibilityHidden(true)
    }

    private func color(_ z: String?) -> Color {
        switch z {
        case "SS", "Z4", "Z5", "Z6", "Z7": summit
        case "Z3": Color.white.opacity(0.45)
        default: Theme.panelLine
        }
    }
}

struct NextCard: View {
    let text: String
    let moved: [TrainToday.Moved]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Labelled(label: "What's next", text: text, textColor: Theme.ink)
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

/// A recent ride's note in brief (a day or two ago), opening the full note.
struct LatestRideCard: View {
    let note: TrainNote

    var body: some View {
        NavigationLink { RideNoteView(rideId: note.rideId, initial: note) } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    MonoLabel("Your last ride · \(note.day?.formatted(.dateTime.weekday(.abbreviated)) ?? note.date)")
                    Spacer()
                    Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(Theme.label)
                }
                Text(note.counted.map { "Counted as \($0.title)" } ?? note.kindTitle ?? "Your ride")
                    .font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                if let tip = note.tips.first {
                    HStack(spacing: 8) {
                        MonoLabel("Try", color: Theme.inkSoft)
                        Text(tip.title).font(Theme.text(14, .semibold)).foregroundStyle(Theme.ink)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 12).padding(.vertical, 9)
                    .background(Theme.sand, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            }
            .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// The week as seven days: ridden (filled), a session expected (ring), rest (a dash), today outlined.
struct WeekStrip: View {
    let days: [TrainToday.Day]
    let done: Int?
    let total: Int?
    let phase: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                MonoLabel("This week" + (phase.map { " · \(PlanText.phase($0))" } ?? ""))
                Spacer()
                if let done, let total {
                    Text("\(done) of \(total) done").font(Theme.text(14, .semibold)).foregroundStyle(Theme.ink)
                }
                Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(Theme.label)
            }
            HStack(spacing: 0) {
                ForEach(days) { d in
                    VStack(spacing: 6) {
                        Text(d.letter).font(Theme.mono(11)).foregroundStyle(d.today ? Theme.ink : Theme.label)
                        ZStack {
                            if d.today {
                                RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(Theme.ink, lineWidth: 1.5)
                                    .frame(width: 38, height: 38)
                            }
                            switch d.state {
                            case "rode": Circle().fill(Theme.cobalt).frame(width: 18, height: 18)
                            case "session": Circle().stroke(Theme.cobalt, lineWidth: 2).frame(width: 16, height: 16)
                            default: Capsule().fill(Theme.label.opacity(0.5)).frame(width: 12, height: 3)
                            }
                        }
                        .frame(height: 40)
                    }
                    .frame(maxWidth: .infinity)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("\(d.letter): \(d.state == "rode" ? "ridden" : d.state == "session" ? (d.title ?? "session") : "rest")")
                }
            }
        }
        .padding(16).surfaceCard(radius: 22).contentShape(Rectangle())
    }
}

struct GoalCard: View {
    let goal: TrainGoal

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                MonoLabel("Your goal")
                Spacer()
                if let w = goal.weeksLeft, let r = goal.readyBy.flatMap(GoalText.date) {
                    MonoLabel("\(w) weeks · \(r.formatted(.dateTime.day().month(.abbreviated)))")
                }
            }
            if let t = goal.title { Text(t).font(Theme.heading(30)).foregroundStyle(Theme.ink).padding(.top, -4) }
            ForEach(goal.markers) { m in marker(m) }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
    }

    private func marker(_ m: TrainGoal.Marker) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .lastTextBaseline, spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(m.name).font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
                    Text(m.meaning.components(separatedBy: ":").first ?? m.meaning)
                        .font(Theme.text(12)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                HStack(alignment: .lastTextBaseline, spacing: 3) {
                    Text(m.current.map { "\(Int($0))" } ?? "—").font(Theme.hero(28)).foregroundStyle(Theme.ink)
                    Text(m.unit).font(Theme.text(13, .medium)).foregroundStyle(Theme.inkSoft)
                }
            }
            HStack(spacing: 10) {
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Capsule().fill(Theme.surfaceSelected)
                        Capsule().fill(m.reached ? summit : Theme.cobalt).frame(width: max(8, geo.size.width * m.progress))
                    }
                }
                .frame(height: 8)
                if m.reached {
                    HStack(spacing: 4) {
                        Image(systemName: "checkmark").font(.system(size: 10, weight: .bold))
                        Text("Aim \(m.target.map { "\(Int($0))" } ?? "") met").font(Theme.mono(11))
                    }
                    .foregroundStyle(Theme.ink).padding(.horizontal, 8).padding(.vertical, 4)
                    .background(summit, in: Capsule())
                } else if let t = m.target {
                    Text("Aim \(Int(t))").font(Theme.mono(11)).foregroundStyle(Theme.inkMuted)
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}

enum TrainText {
    struct Number { let value: String; let label: String; var accent = false }

    /// A session's key numbers: how long, the main set, and how hard (watts, else heart rate, else feel).
    static func numbers(_ s: PlanSession) -> [Number] {
        var out = [Number(value: "\(Int((s.seconds / 60).rounded()))", label: "min")]
        if let set = s.steps.first(where: { $0.set != nil }), let n = set.repeat,
           let work = set.steps?.first, let secs = work.seconds {
            let each = secs < 60 ? "\(Int(secs))" : "\(Int(secs / 60))"
            let unit = secs < 60 ? "sec" : "min"
            out.append(Number(value: "\(n)×\(each)", label: "\(unit) \(work.zone == "SS" || work.zone == "Z4" ? "steady" : "hard")"))
            if let w = work.target?.watts {
                let mid = Int((Double(w[0] + w[1]) / 2 / 5).rounded()) * 5
                out.append(Number(value: "\(mid)", label: "watts", accent: true))
            } else if let hr = work.target?.hr {
                out.append(Number(value: "\(hr[0])", label: "bpm +", accent: true))
            }
        } else if let main = s.steps.flatMap(\.flat).max(by: { ($0.seconds ?? 0) < ($1.seconds ?? 0) }) {
            if let w = main.target?.watts { out.append(Number(value: "\(w[1])", label: "watts max", accent: true)) }
            if let rpe = main.target?.rpe { out.append(Number(value: "\(rpe)/10", label: "effort")) }
        }
        return out
    }

    /// A ride's key numbers: distance, climbing (or time), and its best minute (or average power or heart rate).
    static func numbers(_ n: TrainNote) -> [Number] {
        var out = [Number(value: Format.number(n.did.km, decimals: 1), label: "km")]
        if let a = n.did.ascentM, a >= 1 { out.append(Number(value: "\(Int(a))", label: "m up")) }
        else { out.append(Number(value: "\(n.did.minutes)", label: "min")) }
        if let b = n.did.bestMinute {
            out.append(Number(value: "\(Int(b))", label: "W best min", accent: n.means.first?.hasPrefix("Best minute") == true))
        } else if let p = n.did.avgPower { out.append(Number(value: "\(Int(p))", label: "W avg")) }
        else if let h = n.did.avgHr { out.append(Number(value: "\(Int(h))", label: "bpm avg")) }
        return out
    }

    static func noteTitle(_ n: TrainNote) -> String {
        if let s = n.story { return s.headline }
        if let best = n.means.first, best.hasPrefix("Best minute") { return "Your best minute yet" }
        if let best = n.means.first, best.contains("your best yet") {
            return best.components(separatedBy: ":").first.map { "\($0) yet" } ?? best
        }
        if let c = n.counted { return c.title }
        return n.kindTitle ?? "Your ride"
    }

    /// How it should feel, without the watts (those are in the numbers above it).
    static func feelWords(_ feel: String) -> String {
        feel.replacingOccurrences(of: #" \(about [^)]*\)"#, with: "", options: .regularExpression)
    }

    /// A session in one plain line, from its main set.
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
                    if let s = n.story {
                        card { Labelled(label: "What it means", text: s.story) }
                    } else if !n.means.isEmpty {
                        card { Labelled(label: "What it means", text: n.means.joined(separator: " ")) }
                    }
                    if let next = n.next, !next.isEmpty { card { Labelled(label: "What's next", text: next) } }
                    if let tip = n.tips.first { tips(n, first: tip) }
                    feel(n)
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

    /// "How did it feel?": the one thing the data can't tell. It shapes the next days and what the coach says.
    private func feel(_ n: TrainNote) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("How did it feel?").font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
            HStack(spacing: 8) {
                ForEach(["easy", "good", "hard", "wrecked"], id: \.self) { f in
                    let on = n.feel?.feel == f
                    Button { Task { await setFeel(f, hurts: n.feel?.hurts ?? false) } } label: {
                        Text(f.capitalized).font(Theme.text(14, on ? .semibold : .medium))
                            .foregroundStyle(Theme.ink).frame(maxWidth: .infinity, minHeight: 46)
                            .background(on ? Theme.cobaltSoft : Theme.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(on ? Theme.cobalt : Theme.line, lineWidth: on ? 1.5 : 1))
                    }
                    .buttonStyle(.plain)
                }
            }
            Button {
                Task { await setFeel(n.feel?.feel ?? "good", hurts: !(n.feel?.hurts ?? false)) }
            } label: {
                Label(n.feel?.hurts == true ? "Something hurts (tap to clear)" : "Something hurts",
                      systemImage: n.feel?.hurts == true ? "checkmark.circle.fill" : "bandage")
                    .font(Theme.text(13, .medium)).foregroundStyle(Theme.heart).frame(minHeight: 36)
            }
            .buttonStyle(.plain)
            Text(n.feel == nil ? "Your answer shapes the next few days." : "Thanks: the next days take it into account.")
                .font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
    }

    private func setFeel(_ f: String, hurts: Bool) async {
        do {
            note = try await APIClient().setFeel(rideId, feel: f, hurts: hurts)
            await model.refresh()
        } catch { self.error = error.localizedDescription }
    }

    private func title(_ n: TrainNote) -> String {
        if let s = n.story { return s.headline }
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

import SwiftUI

/// A session's own page (22 Nov 2026), from Today, What's Next and the week: what it's for, how it should feel,
/// its shape, then each part in order (warm-up, the main set, cool-down) with its targets (watts, heart rate,
/// cadence, how hard) and how to ride it, where, and what to bring. Words come from the engine (today.py `guide`).
struct SessionDetail: View {
    @EnvironmentObject var model: AppModel
    let session: PlanSession
    let plan: TrainingPlan?
    /// "Tomorrow", "Wednesday": when it's next (from What's Next), else the session's own day.
    var when: String? = nil
    @State private var full: PlanSession?
    @State private var part: Int?
    @State private var shareURL: URL?
    @State private var error: String?

    private var s: PlanSession { full ?? session }
    private var guide: SessionGuide? { full?.guide }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header.arrive(0)
                if !s.steps.isEmpty { shape.arrive(1) }
                if let feel = guide?.feel { Note(label: "How it should feel", text: feel).arrive(2) }
                if !s.steps.isEmpty {
                    MonoLabel("The session, step by step").padding(.top, 4).arrive(3)
                    VStack(spacing: 10) {
                        ForEach(Array(parts.enumerated()), id: \.offset) { i, p in
                            PartCard(part: p, number: i + 1, selected: part == i, hasWatts: hasWatts)
                                .arrive(3 + i)
                        }
                    }
                    if let after = guide?.after {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Image(systemName: "lightbulb").font(.system(size: 13)).foregroundStyle(Theme.cobalt)
                            Text(after).font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(.horizontal, 4)
                    }
                }
                if let g = guide {
                    if let w = g.where_ { Note(label: "Where", text: w) }
                    if !g.bring.isEmpty { Note(label: "Before you go", text: g.bring.joined(separator: " ")) }
                }
                actions
            }
            .padding(16).padding(.bottom, 12)
        }
        .background(Theme.ground.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .task { full = try? await APIClient().planSession(session.id) }
        .sheet(isPresented: Binding(get: { shareURL != nil }, set: { if !$0 { shareURL = nil } })) {
            if let shareURL { ShareSheet(items: [shareURL]).presentationDetents([.medium, .large]) }
        }
    }

    // MARK: Header and shape

    private var dayLine: String {
        let date = s.day?.formatted(.dateTime.weekday(.wide).day().month(.wide)) ?? s.date
        if let when, !date.hasPrefix(when) { return "\(when) · \(date) · \(s.time)" }
        return "\(date) · \(s.time)"
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            MonoLabel(dayLine)
            Text(s.title).font(Theme.heading(44)).foregroundStyle(Theme.ink)
            Text(guide?.why ?? s.purpose).font(Theme.text(16)).foregroundStyle(Theme.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var hasWatts: Bool { s.steps.flatMap(\.flat).contains { $0.target?.watts != nil } }

    /// The session's shape on the dark panel: its key numbers, the chart (tap a part's name to light it up),
    /// a time scale, and the parts named under it.
    private var shape: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 8) {
                ForEach(Array(TrainText.numbers(s).enumerated()), id: \.offset) { _, n in
                    HeroNumber(value: n.value, label: n.label, color: n.accent ? Theme.stripes[3] : .white)
                }
            }
            IntervalChart(steps: s.steps, highlight: part.map { parts[$0].range }).frame(height: 96)
            TimeScale(total: s.seconds)
            HStack(spacing: 14) {
                ForEach(Array(parts.enumerated()), id: \.offset) { i, p in
                    Button { withAnimation(.snappy) { part = part == i ? nil : i } } label: {
                        HStack(spacing: 5) {
                            Circle().fill(p.color).frame(width: 7, height: 7)
                            Text(p.name).font(Theme.mono(11)).tracking(11 * 0.08)
                        }
                        .foregroundStyle(part == nil || part == i ? .white : Theme.panelLabel.opacity(0.6))
                    }
                    .buttonStyle(.plain)
                }
                Spacer(minLength: 0)
            }
            if !hasWatts {
                Text("Watts appear here once Kova has seen a few of your rides with power. Until then, ride it by heart rate and feel.")
                    .font(Theme.text(12)).foregroundStyle(Theme.panelLabel).fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    // MARK: Parts

    struct Part {
        let name: String
        let steps: [PlanStep]
        let cues: [String]
        let range: Range<Int>
        var seconds: Double { steps.reduce(0) { $0 + $1.totalSeconds } }
        var color: Color { PlanText.zoneColor(steps.flatMap(\.flat).max { PlanText.intensity($0) < PlanText.intensity($1) }?.zone) }
    }

    /// Warm-up, the main set (everything between), cool-down; each with its range of flat steps for the chart.
    private var parts: [Part] {
        var steps = s.steps
        var out: [(String, [PlanStep], [String])] = []
        if steps.first?.label == "Warm up" {
            out.append(("Warm up", [steps.removeFirst()], guide?.warm.map { [$0] } ?? []))
        }
        var cool: PlanStep?
        if steps.count > 0, steps.last?.label == "Cool down" { cool = steps.removeLast() }
        if !steps.isEmpty {
            let name = out.isEmpty && cool == nil ? "The ride" : "Main set"
            out.append((name, steps, guide?.main ?? []))
        }
        if let cool { out.append(("Cool down", [cool], guide?.cool.map { [$0] } ?? [])) }
        var start = 0
        return out.map { name, st, cues in
            let n = st.reduce(0) { $0 + $1.flat.count }
            defer { start += n }
            return Part(name: name, steps: st, cues: cues, range: start..<(start + n))
        }
    }

    // MARK: Actions

    private var actions: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                if s.steps.contains(where: { $0.set != nil }) {
                    Button("Export for Zwift") { Task { await export() } }.buttonStyle(SecondaryButton())
                }
                Spacer()
                Button(s.status == "done" ? "Mark not done" : "Mark as done") {
                    Task {
                        await model.run("Couldn't update the session") { try await APIClient().setDone(s.id, s.status != "done") }
                        full = try? await APIClient().planSession(session.id)
                    }
                }
                .buttonStyle(SecondaryButton())
            }
            if let error { Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart) }
            if s.steps.contains(where: { $0.set != nil }) {
                Text("Zwift: put the file in Documents/Zwift/Workouts and Zwift sets your KICKR's resistance for each step.")
                    .font(Theme.text(12)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.top, 4)
    }

    private func export() async {
        do {
            let data = try await APIClient().zwift(s.id)
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(s.title) \(s.date).zwo")
            try data.write(to: url)
            shareURL = url
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// A labelled paragraph on a light card.
private struct Note: View {
    let label: String
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            MonoLabel(label)
            Text(text).font(Theme.text(15)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 18)
    }
}

/// Minutes under the chart: 0, then every 15 (or 30 for long rides), and the end.
private struct TimeScale: View {
    let total: Double

    var body: some View {
        let minutes = total / 60
        let step: Double = minutes > 120 ? 60 : minutes > 75 ? 30 : 15
        let ticks = stride(from: 0, through: minutes - step * 0.4, by: step).map { $0 }
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {
                ForEach(ticks, id: \.self) { t in
                    Text("\(Int(t))").position(x: geo.size.width * t / max(1, minutes) + (t == 0 ? 4 : 0), y: 6)
                }
                Text("\(Int(minutes.rounded())) min").position(x: geo.size.width - 20, y: 6)
            }
        }
        .font(Theme.mono(10)).foregroundStyle(Theme.panelLabel)
        .frame(height: 12)
        .accessibilityHidden(true)
    }
}

/// One part of the session: its name and time, how to ride it, then each step with its targets.
private struct PartCard: View {
    let part: SessionDetail.Part
    let number: Int
    let selected: Bool
    let hasWatts: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text("\(number)").font(Theme.mono(12)).foregroundStyle(Theme.cobalt)
                Text(part.name).font(Theme.text(17, .semibold)).foregroundStyle(Theme.ink)
                Spacer()
                Text(PlanText.duration(part.seconds)).font(Theme.mono(13)).foregroundStyle(Theme.inkMuted)
            }
            ForEach(Array(part.cues.enumerated()), id: \.offset) { _, cue in
                Text(cue).font(Theme.text(14)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
            }
            VStack(spacing: 0) {
                ForEach(Array(part.steps.enumerated()), id: \.offset) { i, st in
                    if i > 0 { Rectangle().fill(Theme.line).frame(height: 1) }
                    StepBlock(step: st, hasWatts: hasWatts)
                }
            }
            .padding(.horizontal, 12)
            .background(Theme.ground.opacity(0.7), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .padding(14).frame(maxWidth: .infinity, alignment: .leading)
        .surfaceCard(radius: 18)
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(Theme.cobalt, lineWidth: selected ? 1.5 : 0))
    }
}

/// A step, or a set of repeated steps ("5 × 1 min hard / 2 min easy") with what each repeat holds.
private struct StepBlock: View {
    let step: PlanStep
    let hasWatts: Bool

    var body: some View {
        if let set = step.set, let inner = step.steps {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 6) {
                    Image(systemName: "repeat").font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.cobalt)
                    Text(set).font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
                }
                ForEach(Array(inner.enumerated()), id: \.offset) { _, s in
                    if s.set != nil { StepBlock(step: s, hasWatts: hasWatts).padding(.leading, 12) }
                    else { StepLine(step: s, each: true) }
                }
            }
            .padding(.vertical, 10)
        } else {
            StepLine(step: step, each: false).padding(.vertical, 10)
        }
    }
}

private struct StepLine: View {
    let step: PlanStep
    let each: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 2).fill(PlanText.zoneColor(step.zone)).frame(width: 4, height: 34)
            VStack(alignment: .leading, spacing: 3) {
                Text("\(step.label ?? "") · \(PlanText.short(step.seconds ?? 0))\(each ? " each" : "")")
                    .font(Theme.text(15, .medium)).foregroundStyle(Theme.ink)
                if let t = step.target {
                    Text(TrainText.targets(t)).font(Theme.mono(12)).foregroundStyle(Theme.cobalt)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.leading, each ? 12 : 0)
        .accessibilityElement(children: .combine)
    }
}

extension TrainText {
    /// A step's targets in one line: watts, heart rate (long efforts only), cadence, and how hard it feels.
    static func targets(_ t: PlanTarget) -> String {
        var parts: [String] = []
        if let w = t.watts { parts.append("\(w[0])–\(w[1]) W") }
        if let hr = t.hr { parts.append("♥ \(hr[0])–\(hr[1])") }
        if let r = t.rpm { parts.append("\(r[0])–\(r[1]) rpm") } else if t.rpe >= 10 { parts.append("spin it up") }
        parts.append(t.rpe >= 10 ? "all out" : "\(t.rpe)/10")
        return parts.joined(separator: " · ")
    }
}

/// Planned against ridden, set by set: the same words on the ride's own page (Efforts) and its note (Train).
struct PlannedVsRidden: View {
    let summary: String?
    let lines: [String]
    let sets: [PlannedSet]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let summary {
                Text(summary).font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ForEach(sets, id: \.self) { s in row(s) }
            ForEach(Array(lines.dropFirst(sets.count).enumerated()), id: \.offset) { _, line in
                Text(line).font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func row(_ s: PlannedSet) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon(s.verdict)).font(.system(size: 17)).foregroundStyle(color(s.verdict))
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline) {
                    Text(s.set).font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
                    Spacer()
                    Text("\(s.done) of \(s.planned)").font(Theme.mono(13)).foregroundStyle(Theme.inkSoft)
                }
                Text(detail(s)).font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private func detail(_ s: PlannedSet) -> String {
        guard let p = s.power else { return "Not found in the ride." }
        var out = "\(p) W on average"
        if let w = s.watts, w.count == 2, w[1] - w[0] >= 5 { out += " (\(w[0])–\(w[1]))" }
        if let t = s.target, t.count == 2 {
            switch s.verdict {
            case "above": out += " · above the \(t[0])–\(t[1]) W planned"
            case "below": out += " · under the \(t[0])–\(t[1]) W planned"
            default: out += " · planned \(t[0])–\(t[1]) W"
            }
        }
        return out
    }

    private func icon(_ v: String) -> String {
        switch v {
        case "above": return "arrow.up.circle.fill"
        case "below": return "arrow.down.circle"
        case "missing": return "xmark.circle"
        default: return "checkmark.circle.fill"
        }
    }

    private func color(_ v: String) -> Color {
        switch v {
        case "below": return Theme.inkMuted
        case "missing": return Theme.heart
        default: return Theme.cobalt
        }
    }
}

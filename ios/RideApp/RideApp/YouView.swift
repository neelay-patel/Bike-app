import SwiftUI

/// You: the four headline numbers and the goal's targets first, then fitness and recovery, the tallies
/// that only go up (with prizes), this year, personal bests, the home loop, lately, and the binder.
/// Everything comes from the server's rules (rideengine/analysis/headline.py, records.py), not an AI model.
struct YouView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        if let since = model.you?.since.flatMap(Self.month) { MonoLabel("On record since \(since)") }
                        Text("You").font(Theme.heading(44)).foregroundStyle(Theme.ink)
                        if model.you?.updating == true {
                            MonoLabel("Working in new rides…", color: Theme.cobalt)
                        }
                    }
                    .padding(.horizontal, 4)
                    .padding(.top, 8)

                    if let headline = model.you?.headline {
                        HeadlineCard(headline: headline)
                    }
                    if let recovery = model.recovery, recovery.hasAnything {
                        RecoverySection(recovery: recovery)
                    }
                    if let you = model.you, you.all.rides > 0 {
                        SectionTitle("Every ride adds up")
                        AllTimeHero(tally: you.all)
                        TotalsPanel(you: you)
                        if let ms = you.milestones, !ms.isEmpty { PrizeShelf(milestones: ms, rides: model.rides) }
                        YearCompare(you: you)
                        BestsCabinet(bests: you.bests, rides: model.rides)
                        if let home = you.routes?.first(where: \.home) {
                            HomeLoopLink(route: home, rides: model.rides)
                        }
                        LatelyList(recent: you.recent.filter { !$0.notes.isEmpty }, rides: model.rides)
                        BinderSection()
                    } else if let error = model.error {
                        Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart)
                    } else if !model.isLoading {
                        Text("Your totals and personal bests show up here once rides arrive.")
                            .font(Theme.text(15)).foregroundStyle(Theme.inkMuted)
                            .padding(.vertical, 24)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 24)
            }
            .background(Theme.ground.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
            .refreshable { await model.refresh() }
        }
    }

    /// "2025-03-29" → "March 2025"
    static func month(_ iso: String) -> String? {
        day(iso)?.formatted(.dateTime.month(.wide).year())
    }

    static func day(_ iso: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: iso)
    }
}

struct SectionTitle: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text).font(Theme.heading(26)).foregroundStyle(Theme.ink)
            .padding(.horizontal, 4).padding(.top, 14)
    }
}

// MARK: - The four

/// The one card to keep checking: four numbers, each with where it started, where it is and the
/// goal's target, and the one thing to work on next. Tap a number for its history and what it means.
private struct HeadlineCard: View {
    @EnvironmentObject var model: AppModel
    let headline: YouSummary.Headline
    @State private var open: String?
    @State private var settingGoal = false
    @State private var confirmEnd = false
    @State private var shown = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    MonoLabel(headline.goal == nil ? "Your four numbers" : "Your goal", color: Theme.cobaltSoft)
                    Text(headline.goal?.title ?? "Get these four up and you're riding faster and further.")
                        .font(Theme.heading(headline.goal == nil ? 22 : 28)).foregroundStyle(.white)
                        .fixedSize(horizontal: false, vertical: true)
                    if let by = headline.goal?.readyBy.flatMap(YouView.day) {
                        Text("Ready by \(by.formatted(.dateTime.day().month(.wide).year()))")
                            .font(Theme.mono(12)).foregroundStyle(Theme.panelLabel)
                    }
                }
                Spacer(minLength: 8)
                Menu {
                    Button(headline.goal == nil ? "Set a goal" : "Change goal") { settingGoal = true }
                    if headline.goal != nil {
                        Button("End goal", role: .destructive) { confirmEnd = true }
                    }
                } label: {
                    Image(systemName: "ellipsis.circle").font(.system(size: 20)).foregroundStyle(Theme.panelLabel)
                        .frame(width: 36, height: 36)
                }
                .accessibilityLabel("Goal options")
            }

            VStack(spacing: 0) {
                ForEach(Array(headline.metrics.enumerated()), id: \.element.id) { i, m in
                    MetricRow(metric: m, shown: shown, open: open == m.id)
                        .contentShape(Rectangle())
                        .onTapGesture { withAnimation(.snappy) { open = open == m.id ? nil : m.id } }
                    if i < headline.metrics.count - 1 { Rectangle().fill(Theme.panelLine).frame(height: 1) }
                }
            }

            if let next = headline.next {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: "arrow.right.circle.fill").foregroundStyle(Theme.cobaltSoft)
                    Text(next.text).font(Theme.text(14)).foregroundStyle(.white)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.cobalt, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
            if headline.goal == nil {
                Button("Set a goal for targets") { settingGoal = true }.buttonStyle(SecondaryButton())
            }
            Text("Read from your normal riding. No tests needed.").font(Theme.text(12)).foregroundStyle(Theme.panelLabel)
        }
        .padding(18)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .onAppear { withAnimation(.easeOut(duration: 0.9).delay(0.15)) { shown = true } }
        .sheet(isPresented: $settingGoal) { GoalFlow() }
        .confirmationDialog("End this goal?", isPresented: $confirmEnd, titleVisibility: .visible) {
            Button("End goal", role: .destructive) {
                Task { await model.run { try await APIClient().endGoal() } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("It's kept in your history. The four numbers stay; their targets go with the goal.")
        }
    }
}

private struct MetricRow: View {
    let metric: YouSummary.Headline.Metric
    let shown: Bool
    let open: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        Text(metric.label).font(Theme.text(16, .semibold)).foregroundStyle(.white)
                        if metric.focus {
                            Text("FOCUS").font(Theme.mono(9)).foregroundStyle(Theme.panel)
                                .padding(.horizontal, 5).padding(.vertical, 2)
                                .background(Theme.cobaltSoft, in: Capsule())
                        }
                    }
                    if let target = metric.target {
                        Text("target \(value(target)) \(metric.unit)").font(Theme.mono(11)).foregroundStyle(Theme.cobaltSoft)
                    }
                }
                Spacer(minLength: 8)
                if let cur = metric.current {
                    HStack(alignment: .firstTextBaseline, spacing: 3) {
                        CountingText(value: shown ? cur : (metric.baseline ?? cur) * 0.9, decimals: metric.decimals)
                            .font(Theme.hero(30)).foregroundStyle(.white)
                        Text(metric.unit).font(Theme.text(12, .medium)).foregroundStyle(Theme.panelLabel)
                    }
                } else {
                    Text("–").font(Theme.hero(30)).foregroundStyle(Theme.panelLabel)
                }
            }
            if let p = metric.progress {
                ProgressTrack(progress: shown ? p : 0)
                    .frame(height: 8)
            }
            if let pending = metric.pending {
                Text(pending).font(Theme.text(12)).foregroundStyle(Theme.panelLabel)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if open {
                VStack(alignment: .leading, spacing: 8) {
                    Text(metric.plain).font(Theme.text(14)).foregroundStyle(.white)
                        .fixedSize(horizontal: false, vertical: true)
                    let values = metric.history.map(\.value)
                    if values.count > 1 {
                        Sparkline(values: values, higherIsBetter: true).frame(height: 36)
                    }
                    if let detail = metric.detail {
                        Text(detail).font(Theme.text(12)).foregroundStyle(Theme.panelLabel)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if let base = metric.baseline, metric.target != nil {
                        Text("Started at \(value(base)) \(metric.unit) when this target was set.")
                            .font(Theme.text(12)).foregroundStyle(Theme.panelLabel)
                    }
                    Text(metric.action).font(Theme.text(13)).foregroundStyle(Theme.cobaltSoft)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(.vertical, 12)
        .accessibilityElement(children: .combine)
    }

    private func value(_ v: Double) -> String { Format.number(v, decimals: v.rounded() == v ? 0 : metric.decimals) }
}

/// From where the goal started to its target: filled to where you are now.
private struct ProgressTrack: View {
    let progress: Double

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.panelLine)
                Capsule().fill(progress >= 1 ? Theme.sand : Theme.cobaltSoft)
                    .frame(width: max(8, geo.size.width * min(1, progress)))
            }
        }
        .accessibilityLabel("\(Int((progress * 100).rounded()))% of the way to target")
    }
}

/// A number that counts up when it changes (animate the value with withAnimation).
struct CountingText: View, Animatable {
    var value: Double
    var decimals: Int = 0
    var animatableData: Double {
        get { value }
        set { value = newValue }
    }

    var body: some View {
        Text(Format.hero(value, decimals: decimals)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.6)
    }
}

// MARK: - Tallies that only go up

/// Cobalt hero: every kilometre on record, counting up, and what that distance would get you.
private struct AllTimeHero: View {
    let tally: YouSummary.Tally
    @State private var shown = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            MonoLabel("All time", color: Theme.cobaltSoft)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                CountingText(value: shown ? tally.km : 0).font(Theme.hero(64))
                Text("km").font(Theme.text(16)).foregroundStyle(Theme.cobaltSoft)
            }
            if let crow = tally.crowFlies {
                Text("About \(crow), as the crow flies.")
                    .font(Theme.text(14)).foregroundStyle(Color(hex: 0xE3E8F7))
            }
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20).padding(.vertical, 18)
        .background(Theme.cobalt, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .onAppear { withAnimation(.easeOut(duration: 1.4)) { shown = true } }
        .accessibilityElement(children: .combine)
    }
}

/// Dark panel: hours (first: time on the bike is what everything grows from), rides, climbing, streak.
private struct TotalsPanel: View {
    let you: YouSummary
    @State private var shown = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)],
                      alignment: .leading, spacing: 14) {
                stat("In the saddle", you.all.hours, "h")
                stat("Rides", Double(you.all.rides), nil)
                stat("Climbed", you.all.ascentM, "m")
                stat("Longest streak", Double(you.streak.longestWeeks), "weeks")
            }
            Rectangle().fill(Theme.panelLine).frame(height: 1)
            Text(everestLine).font(Theme.text(14)).foregroundStyle(Theme.panelLabel)
                .fixedSize(horizontal: false, vertical: true)
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 18).padding(.vertical, 16)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .onAppear { withAnimation(.easeOut(duration: 1.4)) { shown = true } }
    }

    private func stat(_ label: String, _ value: Double, _ unit: String?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            MonoLabel(label, color: Theme.panelLabel)
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                CountingText(value: shown ? value : 0).font(Theme.hero(34))
                if let unit { Text(unit).font(Theme.text(14, .medium)) }
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var everestLine: String {
        var line = "\(Format.number(you.all.everests, decimals: 2)) Everests of climbing."
        let now = you.streak.currentWeeks
        line += now > 0 ? " \(now) week\(now == 1 ? "" : "s") in a row right now." : " Your next ride starts a new streak."
        return line
    }
}

/// Prizes for the tallies: the latest one won in each, and how close the next is. A prize won since
/// you last looked gets a moment of its own.
private struct PrizeShelf: View {
    let milestones: [YouSummary.Milestone]
    let rides: [RideSummary]
    @AppStorage("prizes.seen") private var seen = ""
    @State private var celebrate: (YouSummary.Milestone, YouSummary.Milestone.Prize)?
    @State private var shown = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                MonoLabel("Prizes")
                Spacer()
                MonoLabel("\(milestones.reduce(0) { $0 + $1.earned.count }) won")
            }
            if let c = celebrate {
                Celebration(title: "New prize", line: "\(c.1.text) \(c.0.kind == "hours" ? "in the saddle" : c.0.kind == "everests" ? "climbed" : "on record")")
                    .transition(.scale.combined(with: .opacity))
            }
            ForEach(milestones) { m in row(m) }
        }
        .padding(16)
        .surfaceCard()
        .onAppear {
            withAnimation(.easeOut(duration: 1.0).delay(0.2)) { shown = true }
            findNew()
        }
    }

    private func row(_ m: YouSummary.Milestone) -> some View {
        HStack(alignment: .center, spacing: 12) {
            Medal(icon: icon(m.kind), won: !m.earned.isEmpty, big: m.kind == "hours")
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline) {
                    Text(m.earned.last?.text ?? m.label).font(Theme.text(m.kind == "hours" ? 17 : 15, .semibold))
                        .foregroundStyle(Theme.ink)
                    Spacer()
                    if let last = m.earned.last, let d = YouView.day(last.date) {
                        Text(d.formatted(.dateTime.day().month(.abbreviated).year())).font(Theme.mono(11)).foregroundStyle(Theme.label)
                    }
                }
                if let next = m.next {
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule().fill(Theme.surfaceSelected)
                            Capsule().fill(Theme.cobalt).frame(width: max(6, geo.size.width * (shown ? next.progress : 0)))
                        }
                    }
                    .frame(height: 6)
                    Text("\(toGo(m, next)) to \(next.text)").font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
                }
            }
        }
        .accessibilityElement(children: .combine)
    }

    private func toGo(_ m: YouSummary.Milestone, _ next: YouSummary.Milestone.Next) -> String {
        switch m.kind {
        case "hours": return "\(Format.number(max(1, next.toGo), decimals: 0)) h"
        case "km": return "\(Format.number(max(1, next.toGo), decimals: 0)) km"
        case "rides": return "\(Int(next.toGo)) ride\(next.toGo == 1 ? "" : "s")"
        default: return "\(Format.number(next.toGo * 8849, decimals: 0)) m"
        }
    }

    private func icon(_ kind: String) -> String {
        switch kind {
        case "hours": "clock.fill"
        case "km": "road.lanes"
        case "rides": "bicycle"
        default: "mountain.2.fill"
        }
    }

    /// The newest prize won in the last 30 days that hasn't been celebrated yet.
    private func findNew() {
        let keys = Set(seen.split(separator: ",").map(String.init))
        let month = Date().addingTimeInterval(-30 * 86400)
        let fresh = milestones.flatMap { m in m.earned.map { (m, $0) } }
            .filter { !keys.contains("\($0.0.kind):\(Int($0.1.value))") && (YouView.day($0.1.date) ?? .distantPast) > month }
            .max { $0.1.date < $1.1.date }
        seen = milestones.flatMap { m in m.earned.map { "\(m.kind):\(Int($0.value))" } }.joined(separator: ",")
        if let fresh {
            withAnimation(.spring(response: 0.5, dampingFraction: 0.6).delay(0.4)) { celebrate = fresh }
        }
    }
}

private struct Medal: View {
    let icon: String
    let won: Bool
    var big = false

    var body: some View {
        ZStack {
            Circle().fill(won ? Theme.cobalt : Theme.surfaceSelected)
            Circle().strokeBorder(won ? Theme.sand : Theme.line, lineWidth: 2.5).padding(3)
            Image(systemName: icon).font(.system(size: big ? 20 : 16, weight: .semibold))
                .foregroundStyle(won ? Theme.sand : Theme.label)
        }
        .frame(width: big ? 50 : 42, height: big ? 50 : 42)
    }
}

/// A pat on the back: a sand banner with sparkles that burst out once.
struct Celebration: View {
    let title: String
    let line: String
    @State private var burst = false

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                ForEach(0..<8) { i in
                    Image(systemName: "sparkle").font(.system(size: 10)).foregroundStyle(Theme.cobalt)
                        .offset(x: burst ? cos(Double(i) * .pi / 4) * 22 : 0, y: burst ? sin(Double(i) * .pi / 4) * 22 : 0)
                        .opacity(burst ? 0 : 1)
                }
                Image(systemName: "trophy.fill").font(.system(size: 22)).foregroundStyle(Theme.cobalt)
                    .scaleEffect(burst ? 1 : 0.4)
            }
            .frame(width: 40, height: 40)
            VStack(alignment: .leading, spacing: 2) {
                MonoLabel(title, color: Theme.cobalt)
                Text(line).font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(Theme.sand, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .onAppear { withAnimation(.spring(response: 0.6, dampingFraction: 0.5).delay(0.2)) { burst = true } }
        .accessibilityElement(children: .combine)
    }
}

/// This year against last year to the same day, as two bars.
private struct YearCompare: View {
    let you: YouSummary
    @State private var shown = false

    var body: some View {
        let now = you.year, then = you.lastYearToDate
        let top = max(now.km, then.km, 1)
        VStack(alignment: .leading, spacing: 12) {
            MonoLabel("This year so far")
            bar(label: now.label ?? "", km: now.km, share: now.km / top, color: Theme.cobalt)
            bar(label: then.label ?? "", km: then.km, share: then.km / top, color: Theme.inkMuted.opacity(0.45))
            Text(summary(now: now.km, then: then.km))
                .font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
            if let big = you.biggestMonth {
                Text("Biggest month: \(big.label ?? ""), \(Format.number(big.km, decimals: 0)) km over \(big.rides) rides.")
                    .font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16).surfaceCard()
        .onAppear { withAnimation(.easeOut(duration: 1.0).delay(0.1)) { shown = true } }
    }

    private func bar(label: String, km: Double, share: Double, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label).font(Theme.mono(12)).foregroundStyle(Theme.inkMuted)
                Spacer()
                Text("\(Format.number(km, decimals: 0)) km").font(Theme.text(15, .semibold)).monospacedDigit()
            }
            GeometryReader { geo in
                Capsule().fill(color).frame(width: max(6, geo.size.width * (shown ? share : 0)))
            }
            .frame(height: 10)
        }
        .accessibilityElement(children: .combine)
    }

    private func summary(now: Double, then: Double) -> String {
        let diff = now - then
        if then == 0 { return "\(Format.number(now, decimals: 0)) km so far this year." }
        if abs(diff) < 1 { return "Level with last year." }
        return "\(Format.number(abs(diff), decimals: 0)) km \(diff > 0 ? "ahead of" : "behind") last year at this point."
    }
}

// MARK: - Personal bests

/// The trophy cabinet: every personal best, the newest first, with the ones from the last 30 days
/// marked new. A best set since you last looked gets a celebration.
private struct BestsCabinet: View {
    let bests: [YouSummary.Best]
    let rides: [RideSummary]
    @AppStorage("bests.seen") private var seen = ""
    @State private var celebrate: YouSummary.Best?

    private static let newDays = 30.0

    var body: some View {
        let sorted = bests.sorted { $0.start > $1.start }
        let thisYear = bests.filter { Calendar.current.isDate(Date(timeIntervalSince1970: $0.start), equalTo: .now, toGranularity: .year) }.count
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle("Personal bests")
            Text(thisYear > 0 ? "\(thisYear) of your \(bests.count) bests were set this year." : "Your best rides, all time.")
                .font(Theme.text(14)).foregroundStyle(Theme.inkMuted).padding(.horizontal, 4)
            if let best = celebrate {
                Celebration(title: "New personal best", line: "\(best.label): \(best.text)")
                    .transition(.scale.combined(with: .opacity))
            }
            ForEach(sorted) { best in
                if let ride = rides.first(where: { $0.rideId == best.rideId }) {
                    NavigationLink { RideDetailView(ride: ride) } label: { row(best) }.buttonStyle(.plain)
                } else {
                    row(best)
                }
            }
        }
        .onAppear(perform: findNew)
    }

    private func isNew(_ best: YouSummary.Best) -> Bool {
        Date().timeIntervalSince1970 - best.start < Self.newDays * 86400
    }

    private func row(_ best: YouSummary.Best) -> some View {
        let fresh = isNew(best)
        return HStack(alignment: .center, spacing: 12) {
            ZStack {
                Circle().fill(fresh ? Theme.cobalt : Theme.sand)
                Image(systemName: "trophy.fill").font(.system(size: 16))
                    .foregroundStyle(fresh ? Theme.sand : Theme.cobalt)
            }
            .frame(width: 40, height: 40)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    MonoLabel(best.label)
                    if fresh {
                        Text("NEW").font(Theme.mono(9)).foregroundStyle(.white)
                            .padding(.horizontal, 5).padding(.vertical, 2)
                            .background(Theme.cobalt, in: Capsule())
                    }
                }
                Text(Date(timeIntervalSince1970: best.start).formatted(.dateTime.day().month(.wide).year()))
                    .font(Theme.text(14)).foregroundStyle(Theme.inkMuted)
            }
            Spacer(minLength: 8)
            Text(best.text).font(Theme.text(22, .semibold)).monospacedDigit().foregroundStyle(Theme.ink)
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .surfaceCard(radius: 16)
        .overlay {
            if fresh {
                RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Theme.cobalt, lineWidth: 1.5)
            }
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    /// The newest best (from the last 30 days) whose ride hasn't been seen for its kind yet.
    private func findNew() {
        let keys = Set(seen.split(separator: ",").map(String.init))
        let fresh = bests.filter { isNew($0) && !keys.contains("\($0.kind):\($0.rideId)") }.max { $0.start < $1.start }
        seen = bests.map { "\($0.kind):\($0.rideId)" }.joined(separator: ",")
        if let fresh {
            withAnimation(.spring(response: 0.5, dampingFraction: 0.6).delay(0.4)) { celebrate = fresh }
        }
    }
}

/// The latest rides that had something worth saying.
private struct LatelyList: View {
    let recent: [YouSummary.Recent]
    let rides: [RideSummary]

    var body: some View {
        if !recent.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                MonoLabel("Lately").padding(.horizontal, 4).padding(.top, 8)
                ForEach(recent) { r in
                    if let ride = rides.first(where: { $0.rideId == r.rideId }) {
                        NavigationLink { RideDetailView(ride: ride) } label: { row(r) }.buttonStyle(.plain)
                    } else {
                        row(r)
                    }
                }
            }
        }
    }

    private func row(_ r: YouSummary.Recent) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("\(Date(timeIntervalSince1970: r.start).formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))) · \(Format.number(r.km, decimals: 1)) km")
                .font(Theme.mono(12)).foregroundStyle(Theme.inkMuted)
            NoteList(notes: r.notes)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 16).padding(.vertical, 12)
        .surfaceCard(radius: 16)
        .contentShape(Rectangle())
    }
}

/// A ride's notes: personal bests marked with a cobalt star, the rest as plain lines.
struct NoteList: View {
    let notes: [RideNote]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(notes, id: \.self) { note in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Image(systemName: note.pb ? "star.fill" : "circle.fill")
                        .font(.system(size: note.pb ? 11 : 5))
                        .foregroundStyle(note.pb ? Theme.cobalt : Theme.inkMuted)
                        .frame(width: 12)
                    (Text(note.text).font(Theme.text(15, note.pb ? .semibold : .regular)).foregroundColor(Theme.ink)
                     + Text(note.detail.map { "  \($0)" } ?? "").font(Theme.mono(12)).foregroundColor(Theme.inkMuted))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .accessibilityElement(children: .combine)
            }
        }
    }
}

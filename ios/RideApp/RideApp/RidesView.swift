import SwiftUI

/// Efforts (18 Nov 2026): new efforts first, as their full ride card, then this month in one line, then
/// your collection of every effort's card. Each effort is the real ride of a session, with its false starts
/// (and any other part of the same outing) folded in.
struct RidesView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var health: HealthSync
    @State private var deleting: RideSummary?
    @AppStorage("rides.showHidden") private var showHidden = false
    /// The newest effort you've already seen here: anything after it is new.
    @AppStorage("efforts.seenUntil") private var seenUntil: Double = 0
    /// New this visit (kept while you look, so they don't vanish as soon as they're marked seen).
    @State private var fresh: [String] = []
    @State private var freshSince: Double = 0

    private var visible: [RideSummary] { model.rides.filter { $0.hidden == nil } }
    /// One per effort: its main ride.
    private var efforts: [RideSummary] { visible.filter { $0.effort == nil || $0.effort == $0.rideId } }
    private var hiddenCount: Int { model.rides.count - visible.count }

    private func folded(_ ride: RideSummary) -> (falseStarts: Int, parts: Int) {
        let mine = model.rides.filter { $0.effort == ride.rideId && $0.rideId != ride.rideId }
        return (mine.filter { $0.hidden != nil }.count, mine.filter { $0.hidden == nil }.count)
    }

    private var hero: [RideSummary] {
        let new = fresh.compactMap { id in efforts.first { $0.rideId == id } }
        return new.isEmpty ? Array(efforts.prefix(1)) : new
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    VStack(alignment: .leading, spacing: 4) {
                        if !efforts.isEmpty { MonoLabel("\(efforts.count) efforts on record") }
                        Text("Efforts").font(Theme.heading(44)).foregroundStyle(Theme.ink)
                    }
                    .padding(.horizontal, 4)
                    .padding(.top, 8)

                    StatusLine()
                    if !hero.isEmpty {
                        EffortHero(rides: hero, isNew: !fresh.isEmpty && hero.contains { fresh.contains($0.rideId) },
                                   since: freshSince > 0 ? Date(timeIntervalSince1970: freshSince) : nil)
                    }
                    if let month = MonthTotal(rides: visible) {
                        MonthStrip(month: month)
                    }
                    if efforts.isEmpty && model.problem == nil && !model.isLoading {
                        Text("No rides yet. Connect Apple Health or Garmin in Sources.")
                            .font(Theme.text(15)).foregroundStyle(Theme.inkMuted)
                            .padding(.vertical, 24)
                    }
                    if !efforts.isEmpty {
                        EffortCollection(efforts: showHidden ? model.rides : efforts, showingHidden: showHidden,
                                         folded: folded, delete: { deleting = $0 })
                    }
                    if hiddenCount > 0 {
                        Toggle(isOn: $showHidden) {
                            Text("Show \(hiddenCount) false starts and empty recordings")
                                .font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                        }
                        .tint(Theme.cobalt)
                        .padding(14)
                        .surfaceCard(radius: 16)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16)
                .padding(.bottom, 24)
            }
            .background(Theme.ground.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
            .refreshable {
                await health.syncNew()
                _ = try? await APIClient().refreshSources()
                await model.refresh()
            }
            .onAppear(perform: markSeen)
            .onChange(of: efforts.first?.rideId) { _, _ in markSeen() }
            .confirmationDialog("Delete this ride?", isPresented: Binding(get: { deleting != nil },
                                                                          set: { if !$0 { deleting = nil } }),
                                titleVisibility: .visible, presenting: deleting) { ride in
                Button("Delete ride", role: .destructive) {
                    Task { await model.run("Couldn't delete the ride") { try await APIClient().deleteRide(ride.rideId) } }
                }
                Button("Cancel", role: .cancel) {}
            } message: { ride in
                Text(DeleteRide.message(ride))
            }
        }
    }

    /// Efforts that arrived since you last looked become this visit's new ones (up to five), and are seen
    /// from now on. The very first time, nothing is new: the latest leads.
    private func markSeen() {
        guard let latest = efforts.map(\.summary.start).max() else { return }
        guard seenUntil > 0 else { seenUntil = latest; return }
        let newer = efforts.filter { $0.summary.start > seenUntil }.map(\.rideId)
        guard !newer.isEmpty else { return }
        if fresh.isEmpty { freshSince = seenUntil }
        fresh = Array((newer + fresh.filter { !newer.contains($0) }).prefix(5))
        seenUntil = latest
    }
}

/// The latest month that has rides: its total distance and a one-line summary.
struct MonthTotal {
    let title: String
    let km: Double
    let rides: Int
    let climbed: Double
    let longest: Double
    /// Time on the bike, indoors included: what the month shows when it has no road km.
    let hours: Double

    init?(rides all: [RideSummary]) {
        guard let latest = all.map(\.date).max() else { return nil }
        let cal = Calendar.current
        // One per effort: other parts of the same session count with their main ride.
        let month = all.filter { cal.isDate($0.date, equalTo: latest, toGranularity: .month) }
        let efforts = month.filter { $0.effort == nil || $0.effort == $0.rideId }.count
        title = latest.formatted(.dateTime.month(.wide).year())
        km = month.reduce(0) { $0 + ($1.noDistance ? 0 : $1.summary.km) }  // trainer km aren't road km
        rides = efforts
        climbed = month.reduce(0) { $0 + ($1.noDistance ? 0 : $1.summary.ascentM ?? 0) }  // nor its virtual climbing
        longest = month.map { $0.noDistance ? 0 : $0.summary.km }.max() ?? 0
        hours = month.reduce(0) { $0 + $1.summary.movingH }
    }
}

struct RideRow: View {
    let ride: RideSummary
    /// False starts and other parts of the same session, folded into this effort.
    var folded: (falseStarts: Int, parts: Int) = (0, 0)

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            Group {
                if ride.noDistance {
                    VStack(alignment: .leading, spacing: 0) {
                        Text(Format.duration(hours: ride.summary.movingH)).font(Theme.text(26, .semibold)).monospacedDigit()
                        Text("indoor").font(Theme.text(13, .medium)).foregroundStyle(Theme.inkMuted)
                    }
                } else {
                    HStack(alignment: .firstTextBaseline, spacing: 2) {
                        Text(Format.number(ride.summary.km, decimals: 1)).font(Theme.text(26, .semibold)).monospacedDigit()
                        Text("km").font(Theme.text(13, .medium)).foregroundStyle(Theme.inkMuted)
                    }
                }
            }
            .frame(width: 96, alignment: .leading)
            VStack(alignment: .leading, spacing: 3) {
                Text(ride.date.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated)))
                    .font(Theme.text(16, .semibold))
                details
                if let top = ride.notes?.first {
                    Label {
                        Text(top.text).font(Theme.text(13, .medium))
                    } icon: {
                        Image(systemName: top.pb ? "star.fill" : "sparkle").font(.system(size: 10))
                    }
                    .labelStyle(.titleAndIcon)
                    .foregroundStyle(Theme.cobalt)
                }
                if let cut = ride.excluded?.first {
                    Text("\(Format.number(cut.km, decimals: 1)) km in a car left out")
                        .font(Theme.text(12)).foregroundStyle(Theme.heart)
                }
                if let hidden = ride.hidden {
                    MonoLabel(hidden == "empty" ? "Empty recording" : "False start")
                }
                if folded.parts > 0 || folded.falseStarts > 0 {
                    Text([folded.parts > 0 ? "+ \(folded.parts) more part\(folded.parts == 1 ? "" : "s")" : nil,
                          folded.falseStarts > 0 ? "\(folded.falseStarts) false start\(folded.falseStarts == 1 ? "" : "s") folded in" : nil]
                        .compactMap { $0 }.joined(separator: " · "))
                        .font(Theme.mono(11)).foregroundStyle(Theme.label)
                }
            }
            Spacer(minLength: 0)
        }
        .foregroundStyle(Theme.ink)
        .padding(.horizontal, 16).padding(.vertical, 12)
        .surfaceCard(radius: 16)
        .contentShape(Rectangle())
    }

    private var details: Text {
        var parts = [ride.date.formatted(.dateTime.hour().minute())]
        if ride.noDistance {
            if ride.summary.power60S != nil, let w = ride.summary.avgPower {
                parts.append("\(Int(w.rounded())) W")
            } else if let kcal = ride.summary.calories { parts.append("\(Format.number(kcal, decimals: 0)) kcal") }
        } else {
            parts.append(Format.duration(hours: ride.summary.movingH))
        }
        if let up = ride.summary.ascentM { parts.append("\(Format.number(up, decimals: 0)) m") }
        let base = Text(parts.joined(separator: " · ")).font(Theme.mono(12)).foregroundColor(Theme.inkMuted)
        guard let hr = ride.summary.avgHr else { return base }
        return base + Text(" · ♥ \(Int(hr.rounded()))").font(Theme.mono(12)).foregroundColor(Theme.heart)
    }
}

// MARK: - Ride detail

struct RideDetailView: View {
    let ride: RideSummary
    @State private var profile: Profile?
    @StateObject private var card = CardRenderer()
    @State private var confirmShare = false
    @State private var shareImage: UIImage?
    @State private var confirmDelete = false
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                MonoLabel("\(ride.date.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated).hour().minute())) · \(Format.sourceList(ride.sources))")
                    .padding(.horizontal, 4)

                // The collectible card first: it's the ride's story, and what gets shared.
                RideCard(renderer: card, rideId: ride.rideId)

                // What you did: the session's phases, read from the samples.
                EffortPanel(rideId: ride.rideId)

                if let notes = ride.notes, !notes.isEmpty {
                    NoteList(notes: notes)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(16).surfaceCard()
                }

                ProfilePanel(ride: ride, profile: profile)

                if let more = secondary {
                    Text(more).font(Theme.text(14)).foregroundStyle(Theme.inkSoft).padding(.horizontal, 4)
                }
                if let cuts = ride.excluded, !cuts.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        MonoLabel("Left out")
                        ForEach(Array(cuts.enumerated()), id: \.offset) { _, cut in
                            Text(String(format: "%.1f km over %d min in a vehicle, up to %.0f km/h. Not counted in this ride.",
                                        cut.km, cut.minutes, cut.peakKmh))
                                .font(Theme.text(14)).foregroundStyle(Theme.heart)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(16).surfaceCard()
                }
                VStack(alignment: .leading, spacing: 8) {
                    MonoLabel("Where each value came from")
                    FlowChips(chips: Format.sourceChips(ride.provenance))
                    Text(useLine).font(Theme.mono(11)).foregroundStyle(Theme.label)
                }
                .padding(.horizontal, 4).padding(.top, 4)
            }
            .padding(.horizontal, 16).padding(.bottom, 24)
        }
        .background(Theme.ground.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button("Delete ride", systemImage: "trash", role: .destructive) { confirmDelete = true }
                } label: {
                    Label("More", systemImage: "ellipsis")
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    if shareCleared { Task { await share() } } else { confirmShare = true }
                } label: {
                    Label("Share card", systemImage: "square.and.arrow.up")
                }
                .disabled(!card.isLoaded)
            }
        }
        .confirmationDialog("Delete this ride?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete ride", role: .destructive) {
                Task {
                    await model.run("Couldn't delete the ride") { try await APIClient().deleteRide(ride.rideId) }
                    dismiss()
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(DeleteRide.message(ride))
        }
        .confirmationDialog("Share this card?", isPresented: $confirmShare, titleVisibility: .visible) {
            Button("Share anyway") { Task { await share() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This ride uses data from \(blockedNames), whose terms on showing data to other people haven't been reviewed yet. Fine to keep for yourself; check before posting.")
        }
        .sheet(isPresented: Binding(get: { shareImage != nil }, set: { if !$0 { shareImage = nil } })) {
            if let shareImage {
                ShareSheet(items: [shareImage]).presentationDetents([.medium, .large])
            }
        }
        .task {
            if profile == nil, let trace = try? await APIClient().trace(ride.rideId) {
                profile = Profile(trace: trace, km: ride.summary.km)
            }
        }
    }

    private var shareCleared: Bool { ride.use["share"]?.allowed ?? false }

    private var blockedNames: String {
        let names = (ride.use["share"]?.blockedBy ?? []).map(Format.sourceName)
        return names.isEmpty ? "a source" : names.joined(separator: " and ")
    }

    private func share() async {
        shareImage = await card.image()
    }

    private var secondary: String? {
        var parts: [String] = []
        let powerLeads = ride.noDistance && ride.summary.power60S != nil  // already in the panel
        if !ride.noDistance, ride.summary.avgHr != nil, let v = ride.summary.avgKmh { parts.append("\(Format.number(v, decimals: 1)) km/h average") }
        if !powerLeads, let v = ride.summary.avgPower { parts.append("\(Int(v.rounded())) W average") }
        if let v = ride.summary.power60S { parts.append("best minute \(Int(v)) W") }
        if let v = ride.summary.avgCadence { parts.append("cadence \(Int(v)) rpm") }
        if let v = ride.summary.hrDrop60S { parts.append("heart rate fell \(Int(v.rounded())) bpm in the minute after") }
        if let v = ride.summary.calories {
            let from = ride.provenance["total:calories"].map(Format.sourceName) ?? ""
            parts.append("\(Format.number(v, decimals: 0)) kcal" + (from.isEmpty ? "" : " (\(from))"))
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private var useLine: String {
        ["ai": "AI insights", "share": "Sharing"].sorted { $0.key < $1.key }.compactMap { key, label in
            guard let p = ride.use[key] else { return nil }
            return p.allowed ? "\(label): yes" : "\(label): not yet (\(p.blockedBy.map(Format.sourceName).joined(separator: ", ")) terms)"
        }.joined(separator: " · ")
    }
}

/// Dark panel: halftone elevation profile with the heart-rate peak, then the four hero totals.
struct ProfilePanel: View {
    let ride: RideSummary
    let profile: Profile?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if ride.noDistance {
                // Indoors: no route or elevation (the card above shows heart rate across the session).
                LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)],
                          alignment: .leading, spacing: 12) {
                    HeroStat(label: "Time", value: Format.duration(hours: ride.summary.movingH), unit: nil)
                    if let watts = ride.summary.avgPower, ride.summary.power60S != nil {
                        // A trainer or power meter: power leads.
                        HeroStat(label: "Avg power", value: "\(Int(watts.rounded()))", unit: "W")
                        HeroStat(label: "Best 20 min", value: ride.summary.power1200S.map { "\(Int($0))" } ?? "–", unit: "W")
                    } else {
                        HeroStat(label: "Calories", value: ride.summary.calories.map { Format.hero($0, decimals: 0) } ?? "–", unit: "kcal")
                        HeroStat(label: "Max heart rate", value: ride.summary.maxHr.map { "\(Int($0.rounded()))" } ?? "–", unit: "bpm")
                    }
                    HeroStat(label: "Avg heart rate", value: ride.summary.avgHr.map { "\(Int($0.rounded()))" } ?? "–", unit: "bpm")
                }
            } else {
            ElevationProfile(profile: profile, totalKm: ride.summary.km)
                .frame(height: 118)
            Rectangle().fill(Theme.panelLine).frame(height: 1)
            LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)],
                      alignment: .leading, spacing: 12) {
                HeroStat(label: "Length", value: Format.number(ride.summary.km, decimals: 1), unit: "km")
                HeroStat(label: "Climbing", value: ride.summary.ascentM.map { Format.hero($0, decimals: 0) } ?? "–", unit: "m")
                HeroStat(label: "Moving", value: Format.duration(hours: ride.summary.movingH), unit: nil)
                if let hr = ride.summary.avgHr {
                    HeroStat(label: "Avg heart rate", value: "\(Int(hr.rounded()))", unit: "bpm")
                } else {
                    HeroStat(label: "Avg speed", value: ride.summary.avgKmh.map { Format.number($0, decimals: 1) } ?? "–", unit: "km/h")
                }
            }
            }
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 18).padding(.vertical, 16)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }
}

struct HeroStat: View {
    let label: String
    let value: String
    let unit: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            MonoLabel(label, color: Theme.panelLabel)
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(value).font(Theme.hero(34)).lineLimit(1).minimumScaleFactor(0.6)
                if let unit { Text(unit).font(Theme.text(14, .medium)) }
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// Elevation by distance, thinned to ~160 points, and where the heart rate peaked.
struct Profile {
    var points: [(km: Double, ele: Double)] = []
    var peak: (km: Double, bpm: Double)?

    init(trace: RideTrace, km: Double) {
        var dist = 0.0
        var prev: RideTrace.Point?
        var raw: [(Double, Double)] = []
        var best: (Double, Double)?
        for s in trace.samples {
            if let p = prev, let a = p.lat, let b = p.lon, let c = s.lat, let d = s.lon {
                dist += Format.haversine(a, b, c, d)
            }
            if s.lat != nil { prev = s }
            if let e = s.ele { raw.append((dist, e)) }
            if let hr = s.hr, hr > (best?.1 ?? 0) { best = (dist, hr) }
        }
        guard let total = raw.last?.0, total > 0 else { return }
        let scale = km / (total / 1000)  // device distance over GPS distance
        let step = max(1, raw.count / 160)
        points = stride(from: 0, to: raw.count, by: step).map { (raw[$0].0 / 1000 * scale, raw[$0].1) }
        if let b = best { peak = (b.0 / 1000 * scale, b.1) }
    }
}

struct ElevationProfile: View {
    let profile: Profile?
    let totalKm: Double

    var body: some View {
        Canvas { ctx, size in
            let axis: CGFloat = 16
            let plotH = size.height - axis
            guard let pts = profile?.points, pts.count > 1, totalKm > 0 else {
                ctx.draw(Text("Loading profile…").font(Theme.mono(11)).foregroundColor(Theme.panelLabel),
                         at: CGPoint(x: size.width / 2, y: plotH / 2))
                return
            }
            let lo = pts.map(\.ele).min()!, hi = max(pts.map(\.ele).max()!, lo + 10)
            func at(_ km: Double, _ ele: Double) -> CGPoint {
                CGPoint(x: CGFloat(km / totalKm) * size.width,
                        y: 14 + CGFloat(1 - (ele - lo) / (hi - lo)) * (plotH - 20))
            }
            var line = Path()
            line.addLines(pts.map { at($0.km, $0.ele) })
            var area = line
            area.addLine(to: CGPoint(x: size.width, y: plotH))
            area.addLine(to: CGPoint(x: 0, y: plotH))
            area.closeSubpath()
            // Halftone fill: a dot grid inside the profile, fading towards the bottom.
            ctx.drawLayer { layer in
                layer.clip(to: area)
                var y: CGFloat = 2.5
                while y < plotH {
                    let alpha = 0.9 - 0.75 * Double(y / plotH)
                    var x: CGFloat = 2.5
                    while x < size.width {
                        layer.fill(Path(ellipseIn: CGRect(x: x - 1.1, y: y - 1.1, width: 2.2, height: 2.2)),
                                   with: .color(.white.opacity(alpha)))
                        x += 5
                    }
                    y += 5
                }
            }
            ctx.stroke(line, with: .color(.white), lineWidth: 1.6)
            ctx.fill(Path(CGRect(x: 0, y: plotH, width: size.width, height: 1)), with: .color(Theme.inkMuted))
            if let peak = profile?.peak,
               let near = pts.min(by: { abs($0.km - peak.km) < abs($1.km - peak.km) }) {
                let p = at(near.km, near.ele)
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - 4, y: p.y - 4, width: 8, height: 8)), with: .color(.white))
                let label = Text("MAX ♥ \(Int(peak.bpm)) · KM \(Int(peak.km.rounded()))")
                    .font(Theme.mono(11)).foregroundColor(.white)
                ctx.draw(label, at: CGPoint(x: min(p.x + 8, size.width - 120), y: max(p.y - 10, 6)), anchor: .leading)
            }
            ctx.draw(Text("0").font(Theme.mono(11)).foregroundColor(Theme.panelLabel),
                     at: CGPoint(x: 0, y: size.height - 6), anchor: .leading)
            ctx.draw(Text("\(Format.number(totalKm, decimals: 1)) KM").font(Theme.mono(11)).foregroundColor(Theme.panelLabel),
                     at: CGPoint(x: size.width, y: size.height - 6), anchor: .trailing)
        }
        .accessibilityLabel("Elevation profile" + (profile?.peak.map { ", heart rate peaked at \(Int($0.bpm)) at kilometre \(Int($0.km.rounded()))" } ?? ""))
    }
}

/// Source chips that wrap onto new lines.
struct FlowChips: View {
    let chips: [String]

    var body: some View {
        FlowLayout(spacing: 6) {
            ForEach(chips, id: \.self) { chip in
                Text(chip).font(Theme.text(12)).foregroundStyle(Theme.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 10).padding(.vertical, 4)
                    .background(Theme.surface, in: Capsule())
                    .overlay(Capsule().stroke(Theme.line, lineWidth: 1))
            }
        }
    }
}

struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowH: CGFloat = 0, maxX: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(ProposedViewSize(width: width, height: nil))
            if x > 0 && x + s.width > width { x = 0; y += rowH + spacing; rowH = 0 }
            x += s.width + spacing
            rowH = max(rowH, s.height)
            maxX = max(maxX, x)
        }
        return CGSize(width: min(maxX, width), height: y + rowH)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, rowH: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(ProposedViewSize(width: bounds.width, height: nil))
            if x > bounds.minX && x + s.width > bounds.maxX { x = bounds.minX; y += rowH + spacing; rowH = 0 }
            v.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
            x += s.width + spacing
            rowH = max(rowH, s.height)
        }
    }
}

// MARK: - Formatting

enum Format {
    static func duration(hours: Double) -> String {
        let minutes = Int((hours * 60).rounded())
        return String(format: "%d:%02d", minutes / 60, minutes % 60)
    }

    /// "13:43", or "1:02:05" past an hour.
    static func clock(_ seconds: Double) -> String {
        let s = Int(seconds.rounded())
        return s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, s % 3600 / 60, s % 60)
                         : String(format: "%d:%02d", s / 60, s % 60)
    }

    /// For dot-matrix hero numbers: no thousands separator (its punctuation is wide).
    static func hero(_ v: Double, decimals: Int) -> String {
        v.formatted(.number.precision(.fractionLength(decimals)).grouping(.never))
    }

    static func number(_ v: Double, decimals: Int) -> String {
        v.formatted(.number.precision(.fractionLength(decimals)).grouping(.automatic))
    }

    static func haversine(_ lat1: Double, _ lon1: Double, _ lat2: Double, _ lon2: Double) -> Double {
        let r = 6_371_000.0, p1 = lat1 * .pi / 180, p2 = lat2 * .pi / 180
        let dp = p2 - p1, dl = (lon2 - lon1) * .pi / 180
        let a = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
        return 2 * r * asin(min(1, sqrt(a)))
    }

    static func sourceName(_ key: String) -> String {
        let base = key.hasPrefix("derived:") ? String(key.dropFirst(8)) : key
        let names = ["apple_watch": "Apple Watch", "iphone": "iPhone", "garmin": "Garmin", "wahoo": "Wahoo",
                     "kickr": "KICKR", "hammerhead": "Hammerhead", "whoop": "WHOOP", "oura": "Oura",
                     "fitbit": "Fitbit", "gpx": "GPX", "hr": "heart rate", "power": "power"]
        return names[base] ?? base
    }

    static func sourceList(_ sources: [String]) -> String {
        sources.map(sourceName).joined(separator: " + ")
    }

    /// "Route, elevation, climbing · Garmin", one chip per source.
    static func sourceChips(_ provenance: [String: String]) -> [String] {
        let labels: [(String, String)] = [("channel:lat", "route"), ("channel:ele", "elevation"), ("channel:speed", "speed"),
                                          ("channel:hr", "heart rate"), ("channel:power", "power"), ("channel:cadence", "cadence"),
                                          ("channel:temp", "temperature"), ("total:distance_m", "distance"),
                                          ("total:ascent_m", "climbing"), ("total:moving_s", "moving time"),
                                          ("total:calories", "calories")]
        var bySource: [String: [String]] = [:]
        var order: [String] = []
        for (key, label) in labels {
            guard let src = provenance[key], src != "derived:hr", src != "derived:power" else { continue }
            let name = sourceName(src)
            if bySource[name] == nil { order.append(name) }
            bySource[name, default: []].append(label)
        }
        return order.map { name in
            let list = bySource[name]!.joined(separator: ", ")
            return list.prefix(1).uppercased() + list.dropFirst() + " · " + name
        }
    }
}


enum DeleteRide {
    /// What deleting means, in the confirmation.
    static func message(_ ride: RideSummary) -> String {
        let day = ride.date.formatted(.dateTime.weekday(.wide).day().month(.wide))
        let km = Format.number(ride.summary.km, decimals: 1)
        let from = Format.sourceList(ride.sources)
        return "\(day), \(km) km. Its recordings (\(from)) are deleted from the server and won't come back on the next "
            + "sync. They stay in \(from) itself. This can't be undone."
    }
}


// MARK: - Effort: what you did

/// The session's phases (warm-up, structured workout, own riding, pauses, cool-down) as a strip under the
/// power (or heart-rate) trace, then the story in words. From GET /v1/efforts/{id}.
struct EffortPanel: View {
    let rideId: String
    @State private var effort: Effort?
    @State private var failed = false

    private var part: Effort.Part? {
        effort.flatMap { e in e.parts.first { $0.rideId == rideId } ?? e.parts.first }
    }

    var body: some View {
        Group {
            if let effort, let part {
                VStack(alignment: .leading, spacing: 12) {
                    MonoLabel("What you did")
                    if !part.phases.phases.isEmpty {
                        EffortChart(phases: part.phases).frame(height: 132)
                        PhaseLegend(phases: part.phases.phases)
                    }
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(Array(effort.lines.enumerated()), id: \.offset) { _, line in
                            HStack(alignment: .firstTextBaseline, spacing: 6) {
                                Image(systemName: "circle.fill").font(.system(size: 5)).foregroundStyle(Theme.inkMuted)
                                    .frame(width: 12)
                                Text(line).font(Theme.text(15)).foregroundStyle(Theme.ink)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16).surfaceCard()
            } else if !failed {
                ProgressView().frame(maxWidth: .infinity).padding(16)
            }
        }
        .task(id: rideId) {
            do { effort = try await APIClient().effort(rideId) } catch { failed = true }
        }
    }
}

enum PhaseStyle {
    static func color(_ kind: String) -> Color {
        switch kind {
        case "warm_up": return Theme.sand
        case "structured": return Theme.cobalt
        case "riding": return Theme.strip
        case "cool_down": return Theme.cobaltSoft
        default: return Theme.line            // pause
        }
    }

    static func name(_ kind: String) -> String {
        switch kind {
        case "warm_up": return "Warm-up"
        case "structured": return "Workout"
        case "riding": return "Own riding"
        case "cool_down": return "Cool-down"
        default: return "Pause"
        }
    }
}

struct EffortChart: View {
    let phases: Effort.Phases

    var body: some View {
        Canvas { ctx, size in
            let strip: CGFloat = 12, gap: CGFloat = 6, axis: CGFloat = 14
            let plotH = size.height - strip - gap - axis
            let total = max(phases.phases.map(\.endS).max() ?? 1, 1)
            func x(_ t: Double) -> CGFloat { CGFloat(t / total) * size.width }
            let watts = phases.basis == "power"
            let pts: [(Double, Double)] = phases.series.compactMap { row in
                guard let t = row.first ?? nil else { return nil }
                let v = watts ? (row.count > 1 ? row[1] : nil) : (row.count > 2 ? row[2] : nil)
                return v.map { (t, $0) }
            }
            // Phase bands behind the trace, and the strip under it.
            for p in phases.phases where p.kind != "pause" {
                let r = CGRect(x: x(p.startS), y: 0, width: max(1, x(p.endS) - x(p.startS)), height: plotH)
                ctx.fill(Path(r), with: .color(PhaseStyle.color(p.kind).opacity(0.10)))
            }
            for p in phases.phases {
                let r = CGRect(x: x(p.startS), y: plotH + gap, width: max(1, x(p.endS) - x(p.startS)), height: strip)
                ctx.fill(Path(roundedRect: r, cornerRadius: 2), with: .color(PhaseStyle.color(p.kind)))
            }
            // Pushes (or heavier stretches): ticks above the strip.
            for p in phases.pushes {
                let r = CGRect(x: x(p.startS), y: plotH - 3, width: max(2, x(p.endS) - x(p.startS)), height: 3)
                ctx.fill(Path(r), with: .color(Theme.heart))
            }
            guard pts.count > 1 else { return }
            let lo = min(pts.map(\.1).min()!, watts ? 0 : 60), hi = max(pts.map(\.1).max()!, lo + 20)
            func y(_ v: Double) -> CGFloat { 4 + CGFloat(1 - (v - lo) / (hi - lo)) * (plotH - 8) }
            var line = Path()
            line.addLines(pts.map { CGPoint(x: x($0.0), y: y($0.1)) })
            ctx.stroke(line, with: .color(watts ? Theme.ink : Theme.heart), lineWidth: 1.4)
            let unit = watts ? "W" : "BPM"
            ctx.draw(Text("\(Int(hi)) \(unit)").font(Theme.mono(10)).foregroundColor(Theme.label),
                     at: CGPoint(x: 0, y: 6), anchor: .leading)
            ctx.draw(Text("0").font(Theme.mono(10)).foregroundColor(Theme.label),
                     at: CGPoint(x: 0, y: size.height - 5), anchor: .leading)
            ctx.draw(Text(Format.clock(total)).font(Theme.mono(10)).foregroundColor(Theme.label),
                     at: CGPoint(x: size.width, y: size.height - 5), anchor: .trailing)
        }
        .accessibilityLabel("Phases: " + phases.phases.filter { $0.kind != "pause" }
            .map { "\(PhaseStyle.name($0.kind)) \(Int($0.minutes.rounded())) minutes" }.joined(separator: ", "))
    }
}

struct PhaseLegend: View {
    let phases: [Effort.Phase]

    private var kinds: [(String, Double)] {
        var order: [String] = [], mins: [String: Double] = [:]
        for p in phases where p.kind != "pause" {
            if mins[p.kind] == nil { order.append(p.kind) }
            mins[p.kind, default: 0] += p.minutes
        }
        return order.map { ($0, mins[$0]!) }
    }

    var body: some View {
        FlowLayout(spacing: 10) {
            ForEach(kinds, id: \.0) { kind, minutes in
                HStack(spacing: 5) {
                    RoundedRectangle(cornerRadius: 2).fill(PhaseStyle.color(kind)).frame(width: 10, height: 10)
                    Text("\(PhaseStyle.name(kind)) \(Int(minutes.rounded())) min").font(Theme.mono(11)).foregroundStyle(Theme.inkMuted)
                }
            }
        }
    }
}

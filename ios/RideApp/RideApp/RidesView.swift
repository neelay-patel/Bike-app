import SwiftUI

/// Merged rides from the backend, newest first, in the D look (docs/design.md).
struct RidesView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var health: HealthSync
    @AppStorage("rides.showHidden") private var showHidden = false

    private var visible: [RideSummary] { model.rides.filter { $0.hidden == nil } }
    private var shown: [RideSummary] { showHidden ? model.rides : visible }
    private var hiddenCount: Int { model.rides.count - visible.count }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        if let month = MonthTotal(rides: visible) { MonoLabel(month.title) }
                        Text("Rides").font(Theme.heading(44)).foregroundStyle(Theme.ink)
                    }
                    .padding(.horizontal, 4)
                    .padding(.top, 8)

                    if let error = model.error {
                        Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart)
                    }
                    if let month = MonthTotal(rides: visible) {
                        MonthHero(month: month)
                    }
                    if shown.isEmpty && model.error == nil && !model.isLoading {
                        Text("No rides yet. Connect Apple Health or Garmin in Sources.")
                            .font(Theme.text(15)).foregroundStyle(Theme.inkMuted)
                            .padding(.vertical, 24)
                    }
                    LazyVStack(spacing: 8) {
                        ForEach(shown) { ride in
                            NavigationLink { RideDetailView(ride: ride) } label: { RideRow(ride: ride) }
                                .buttonStyle(.plain)
                        }
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
                .padding(.horizontal, 16)
                .padding(.bottom, 24)
            }
            .background(Theme.ground.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
            .refreshable {
                await health.syncNew()
                await model.refresh()
            }
        }
    }
}

/// The latest month that has rides: its total distance and a one-line summary.
struct MonthTotal {
    let title: String
    let km: Double
    let rides: Int
    let climbed: Double
    let longest: Double

    init?(rides all: [RideSummary]) {
        guard let latest = all.map(\.date).max() else { return nil }
        let cal = Calendar.current
        let month = all.filter { cal.isDate($0.date, equalTo: latest, toGranularity: .month) }
        title = latest.formatted(.dateTime.month(.wide).year())
        km = month.reduce(0) { $0 + $1.summary.km }
        rides = month.count
        climbed = month.reduce(0) { $0 + ($1.summary.ascentM ?? 0) }
        longest = month.map(\.summary.km).max() ?? 0
    }
}

struct MonthHero: View {
    let month: MonthTotal

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            MonoLabel("This month", color: Theme.cobaltSoft)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(Format.hero(month.km, decimals: 0)).font(Theme.hero(64))
                Text("km").font(Theme.text(16)).foregroundStyle(Theme.cobaltSoft)
            }
            Text("\(month.rides) ride\(month.rides == 1 ? "" : "s") · \(Format.number(month.climbed, decimals: 0)) m climbed · longest \(Format.number(month.longest, decimals: 1)) km")
                .font(Theme.text(14)).foregroundStyle(Color(hex: 0xE3E8F7))
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20).padding(.vertical, 18)
        .background(Theme.cobalt, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

struct RideRow: View {
    let ride: RideSummary

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text(Format.number(ride.summary.km, decimals: 1)).font(Theme.text(26, .semibold)).monospacedDigit()
                Text("km").font(Theme.text(13, .medium)).foregroundStyle(Theme.inkMuted)
            }
            .frame(width: 96, alignment: .leading)
            VStack(alignment: .leading, spacing: 3) {
                Text(ride.date.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated)))
                    .font(Theme.text(16, .semibold))
                details
                if let cut = ride.excluded?.first {
                    Text("\(Format.number(cut.km, decimals: 1)) km in a car left out")
                        .font(Theme.text(12)).foregroundStyle(Theme.heart)
                }
                if let hidden = ride.hidden {
                    MonoLabel(hidden == "empty" ? "Empty recording" : "False start")
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
        var parts = [ride.date.formatted(.dateTime.hour().minute()), Format.duration(hours: ride.summary.movingH)]
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

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    MonoLabel("\(ride.date.formatted(.dateTime.hour().minute())) · \(Format.sourceList(ride.sources))")
                    Text(ride.date.formatted(.dateTime.weekday(.wide).day().month(.wide)))
                        .font(Theme.heading(42)).foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.horizontal, 4)

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
        .task {
            if profile == nil, let trace = try? await APIClient().trace(ride.rideId) {
                profile = Profile(trace: trace, km: ride.summary.km)
            }
        }
    }

    private var secondary: String? {
        var parts: [String] = []
        if ride.summary.avgHr != nil, let v = ride.summary.avgKmh { parts.append("\(Format.number(v, decimals: 1)) km/h average") }
        if let v = ride.summary.avgPower { parts.append("\(Int(v.rounded())) W average") }
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

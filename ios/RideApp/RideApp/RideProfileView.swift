import SwiftUI
import UIKit

/// GET /v1/rides/{id}/profile (backend service.ride_profile): the ride page's profiles in 30-second steps.
struct RideProfile: Decodable {
    let stepS: Int
    let t: [Int]
    let km: [Double?]
    let s: [Double?]
    let h: [Double?]
    let p: [Double?]
    let c: [Double?]
    let e: [Double?]
    let cu: [Double?]
    let lat: [Double?]
    let lon: [Double?]
    let indoor: Bool
    let climbs: [Climb]
    let phases: [Phase]
    let reps: [Rep]
    let zone2: Zone2Split?
    let moments: [Moment]
    let avg: Avg
    let totals: Totals
    let focus: String

    struct Climb: Decodable, Hashable {
        let a: Int; let b: Int; let gainM: Double; let km: Double; let grade: Double; let minutes: Int
        let hr: Double?; let watts: Double?
    }
    struct Phase: Decodable { let kind: String; let a: Int; let b: Int }
    struct Rep: Decodable, Hashable {
        let name: String; let a: Int; let b: Int; let watts: Int; let minutes: Int?
        let thirds: [Int?]?; let target: [Int]?; let line: String?
    }
    struct Moment: Decodable, Hashable {
        let value: Double; let unit: String; let label: String; let at: Int?; let span: [Int]?; let focus: String
    }
    struct Avg: Decodable { let s: Double?; let h: Double?; let p: Double? }
    struct Totals: Decodable { let km: Double?; let ascentM: Double? }

    var count: Int { t.count }

    func series(_ k: String) -> [Double?] {
        switch k { case "p": return p; case "s": return s; case "h": return h; case "c": return c; default: return e }
    }
    func has(_ k: String) -> Bool { series(k).contains { $0 != nil } }
    func average(_ k: String) -> Double? {
        switch k {
        case "s": if let v = avg.s { return v }
        case "h": if let v = avg.h { return v }
        case "p": if let v = avg.p { return v }
        default: break
        }
        let v = series(k).compactMap { $0 }
        return v.isEmpty ? nil : v.reduce(0, +) / Double(v.count)
    }
    /// Climbing so far at a step, ending on the ride's own total.
    func climbed(_ i: Int?) -> Double {
        let i = i ?? (count - 1)
        return cu.indices.contains(i) ? (cu[i] ?? 0) : 0
    }
}

/// Where you are on the ride page: the step you've dragged to, the climb or rep you tapped, the big chart.
struct Scrub: Equatable {
    var idx: Int? = nil
    var span: ClosedRange<Int>? = nil
    var focus: String? = nil
}

enum ProfileChannel {
    struct Info { let key: String; let label: String; let unit: String; let color: Color; let none: String; let decimals: Int }
    static let all: [Info] = [
        Info(key: "p", label: "Power", unit: "W", color: Theme.cobalt, none: "no power meter", decimals: 0),
        Info(key: "s", label: "Speed", unit: "km/h", color: Color(hex: 0x2F7A3E), none: "no speed", decimals: 1),
        Info(key: "h", label: "Heart rate", unit: "bpm", color: Theme.heart, none: "no heart rate", decimals: 0),
        Info(key: "c", label: "Cadence", unit: "rpm", color: Theme.inkSoft, none: "no cadence sensor", decimals: 0),
        Info(key: "e", label: "Elevation", unit: "m", color: Theme.label, none: "no elevation", decimals: 0),
    ]
    static func info(_ k: String) -> Info { all.first { $0.key == k } ?? all[4] }
    static let gold = Color(hex: 0xC99A10)

    static func format(_ v: Double?, _ decimals: Int) -> String {
        guard let v else { return "–" }
        return decimals > 0 ? String(format: "%.\(decimals)f", v) : Format.number(v, decimals: 0)
    }
}

private func minutesLabel(_ step: Int, _ stepS: Int) -> String {
    let m = Int((Double(step * stepS) / 60).rounded())
    return m >= 60 ? "\(m / 60):\(String(format: "%02d", m % 60))" : "\(m) min"
}

// MARK: - Moments

/// The ride's moments, to scan before the charts: a tap jumps the charts and the map to it.
struct MomentsRow: View {
    let profile: RideProfile
    @Binding var scrub: Scrub

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                MonoLabel("The ride's moments")
                Spacer()
                MonoLabel("tap one", color: Theme.label.opacity(0.7))
            }
            .padding(.horizontal, 4)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(profile.moments, id: \.self) { m in
                        let on = isOn(m)
                        Button { tap(m) } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                HStack(alignment: .firstTextBaseline, spacing: 4) {
                                    Text(ProfileChannel.format(m.value, m.unit == "km/h" ? 1 : 0)).font(Theme.hero(26))
                                    Text(m.unit).font(Theme.mono(12))
                                }
                                Text(m.label.uppercased()).font(Theme.mono(10)).tracking(1).opacity(0.75)
                            }
                            .foregroundStyle(on ? Theme.surface : Theme.ink)
                            .padding(.horizontal, 12).padding(.vertical, 10)
                            .frame(minWidth: 112, alignment: .leading)
                            .background(on ? Theme.panel : Theme.surface, in: RoundedRectangle(cornerRadius: 16))
                            .overlay(RoundedRectangle(cornerRadius: 16).stroke(on ? Theme.panel : Theme.line))
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 16)
            }
            .padding(.horizontal, -16)
        }
    }

    private func isOn(_ m: RideProfile.Moment) -> Bool {
        guard scrub.focus == m.focus else { return false }
        if let sp = m.span { return scrub.span == sp[0]...sp[1] }
        return m.at != nil && scrub.idx == m.at && scrub.span == nil
    }

    private func tap(_ m: RideProfile.Moment) {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        withAnimation(.snappy) {
            scrub = Scrub(idx: m.at, span: m.span.map { $0[0]...$0[1] }, focus: m.focus)
        }
    }
}

// MARK: - Profiles

/// The profiles: one big dot-matrix chart (elevation leads outdoors, power indoors) with its number counting
/// from where your finger is, and the other channels as lines under it; tap one to make it the big one.
/// On elevation the number is your climbing so far, with a gold line rising to the ride's total.
struct ProfilesPanel: View {
    let profile: RideProfile
    @Binding var scrub: Scrub
    @State private var replaying: Task<Void, Never>?
    @State private var chartWidth: CGFloat = 300

    private var focus: String {
        let f = scrub.focus ?? profile.focus
        return profile.has(f) ? f : profile.focus
    }

    var body: some View {
        let info = ProfileChannel.info(focus)
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text("Profiles").font(Theme.heading(30)).foregroundStyle(Theme.ink)
                Spacer()
                Button(action: replay) {
                    Label("Replay", systemImage: "play.fill").font(Theme.text(13, .medium))
                        .padding(.horizontal, 12).frame(minHeight: 36)
                        .background(Theme.surfaceSelected, in: Capsule())
                }
                .buttonStyle(.plain).foregroundStyle(Theme.cobalt)
            }
            chips
            bigNumber(info)
            chart(info)
            strip
            sparks
            Text("Drag across the charts: the dot on the card's map follows you.")
                .font(Theme.text(12.5)).foregroundStyle(Theme.inkMuted)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard()
        .onDisappear { replaying?.cancel() }
    }

    private var chips: some View {
        FlowLayout(spacing: 6) {
            ForEach(ProfileChannel.all, id: \.key) { c in
                let has = profile.has(c.key)
                Button { if has { withAnimation(.snappy) { scrub.focus = c.key } } } label: {
                    HStack(spacing: 6) {
                        Circle().fill(has ? c.color : Theme.line).frame(width: 8, height: 8)
                        Text(has ? c.label : "\(c.label): \(c.none)")
                    }
                    .font(Theme.text(13, .medium))
                    .foregroundStyle(c.key == focus ? Theme.surface : has ? Theme.ink : Theme.label)
                    .padding(.horizontal, 12).frame(minHeight: 36)
                    .background(c.key == focus ? Theme.ink : Theme.surface, in: Capsule())
                    .overlay(Capsule().stroke(c.key == focus ? Theme.ink : Theme.line,
                                              style: StrokeStyle(lineWidth: 1, dash: has ? [] : [3, 3])))
                }
                .buttonStyle(.plain).disabled(!has)
            }
        }
    }

    private func bigNumber(_ info: ProfileChannel.Info) -> some View {
        let elevation = focus == "e"
        let at = scrub.idx
        let series = profile.series(focus)
        let label: String = elevation
            ? (at.map { "Climbed · \(minutesLabel($0, profile.stepS)) in" } ?? "Climbed · whole ride")
            : (at.map { "\(info.label) · \(minutesLabel($0, profile.stepS)) in" } ?? "\(info.label) · average")
        let value: Double? = elevation ? profile.climbed(at) : (at.flatMap { series.indices.contains($0) ? series[$0] : nil } ?? profile.average(focus))
        let maxV = series.compactMap { $0 }.max()
        let color = elevation ? ProfileChannel.gold : info.color
        return HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: 0) {
                Text(label.uppercased()).font(Theme.mono(11)).tracking(1.6).foregroundStyle(color)
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(ProfileChannel.format(value, info.decimals)).font(Theme.hero(46))
                        .contentTransition(.numericText()).monospacedDigit()
                    Text(info.unit).font(Theme.mono(14))
                }
                .foregroundStyle(color)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 3) {
                if elevation {
                    Text("OF \(Format.number(profile.totals.ascentM ?? profile.climbed(nil), decimals: 0)) M")
                    if let at, series.indices.contains(at), let v = series[at] {
                        Text("NOW AT \(Format.number(v, decimals: 0)) M")
                    } else if let maxV {
                        Text("HIGHEST \(Format.number(maxV, decimals: 0)) M")
                    }
                } else {
                    Text("AVG \(ProfileChannel.format(profile.average(focus), info.decimals)) \(info.unit.uppercased())")
                    Text("MAX \(ProfileChannel.format(maxV, info.decimals)) \(info.unit.uppercased()) · 30 S")
                }
            }
            .font(Theme.mono(11)).foregroundStyle(Theme.inkMuted).padding(.bottom, 4)
        }
        .animation(.snappy, value: value)
    }

    private func chart(_ info: ProfileChannel.Info) -> some View {
        let series = profile.series(focus)
        let n = profile.count
        let elevation = focus == "e"
        let spans: [ClosedRange<Int>] = !profile.reps.isEmpty ? profile.reps.map { $0.a...max($0.a, $0.b) }
            : profile.climbs.map { $0.a...max($0.a, $0.b) }
        return Canvas { ctx, size in
            guard n > 1 else { return }
            let w = size.width, h = size.height
            func x(_ i: Int) -> CGFloat { CGFloat(i) / CGFloat(n - 1) * w }
            // The climbs (or reps) behind the dots; the one you tapped stronger.
            for sp in spans {
                let r = CGRect(x: x(sp.lowerBound), y: 0, width: max(3, x(sp.upperBound) - x(sp.lowerBound)), height: h)
                let on = scrub.span == sp
                ctx.fill(Path(roundedRect: r, cornerRadius: 4), with: .color(Theme.sand.opacity(on ? 0.95 : 0.55)))
            }
            // Columns of dots, one every 4 points, as tall as the value.
            let vals = series.compactMap { $0 }.filter { focus != "p" || $0 > 0 }
            guard let hi = vals.max(), let lo0 = vals.min() else { return }
            let lo: Double = (focus == "p" || focus == "s") ? 0 : lo0 - (elevation ? 12 : 6)
            let cols = Int(w / 4), rows = Int((h - 4) / 4)
            var before = Path(), after = Path(), inSpan = Path()
            for j in 0..<cols {
                let a = j * n / cols, b = max(a + 1, (j + 1) * n / cols)
                let seg = series[a..<min(b, n)].compactMap { $0 }
                guard !seg.isEmpty else { continue }
                let v = seg.reduce(0, +) / Double(seg.count)
                let k = max(1, Int(((v - lo) / max(hi - lo, 1)) * Double(rows)))
                let cx = 2 + CGFloat(j) * 4, y0 = h - 2, y1 = y0 - CGFloat(k - 1) * 4
                var col = Path(); col.move(to: CGPoint(x: cx, y: y0)); col.addLine(to: CGPoint(x: cx, y: y1))
                let mid = (a + b) / 2
                if let sp = scrub.span, sp.contains(mid) { inSpan.addPath(col) }
                else if let i = scrub.idx, mid > i { after.addPath(col) }
                else { before.addPath(col) }
            }
            let dots = StrokeStyle(lineWidth: 2.9, lineCap: .round, dash: [0, 4])
            ctx.stroke(after, with: .color(Theme.line), style: dots)
            ctx.stroke(before, with: .color(info.color), style: dots)
            ctx.stroke(inSpan, with: .color(ProfileChannel.gold), style: dots)
            // Climbing so far: a gold line rising to the ride's total.
            if elevation {
                let total = max(profile.climbed(nil), 1)
                let stop = scrub.idx ?? (n - 1)
                func y(_ i: Int) -> CGFloat { h - 2 - CGFloat(profile.climbed(i) / total) * (h - 8) }
                var done = Path(), rest = Path()
                done.move(to: CGPoint(x: x(0), y: y(0)))
                for i in stride(from: 1, through: stop, by: 1) { done.addLine(to: CGPoint(x: x(i), y: y(i))) }
                if stop < n - 1 {
                    rest.move(to: CGPoint(x: x(stop), y: y(stop)))
                    for i in (stop + 1)..<n { rest.addLine(to: CGPoint(x: x(i), y: y(i))) }
                }
                ctx.stroke(rest, with: .color(ProfileChannel.gold.opacity(0.4)), style: StrokeStyle(lineWidth: 2, dash: [3, 3]))
                ctx.stroke(done, with: .color(ProfileChannel.gold), style: StrokeStyle(lineWidth: 2.6, lineJoin: .round))
                if scrub.idx != nil {
                    let p = CGPoint(x: x(stop), y: y(stop))
                    ctx.fill(Path(ellipseIn: CGRect(x: p.x - 4.5, y: p.y - 4.5, width: 9, height: 9)), with: .color(ProfileChannel.gold))
                }
            }
            if let i = scrub.idx {
                var line = Path(); line.move(to: CGPoint(x: x(i), y: 0)); line.addLine(to: CGPoint(x: x(i), y: h))
                ctx.stroke(line, with: .color(Theme.ink.opacity(0.7)), lineWidth: 1.2)
            }
        }
        .frame(height: 132)
        .contentShape(Rectangle())
        .background(GeometryReader { g in
            Color.clear.onAppear { chartWidth = g.size.width }.onChange(of: g.size.width) { _, w in chartWidth = w }
        })
        .gesture(drag)
        .revealOnFirstSeen(duration: 1.3)
        .accessibilityLabel(elevation ? "Elevation, with your climbing so far" : "\(info.label) through the ride")
        .accessibilityValue(elevation ? "\(Int(profile.climbed(scrub.idx))) metres climbed" : "")
    }

    /// The session's phases under the chart, with the reps or climbs marked.
    private var strip: some View {
        let n = max(profile.count - 1, 1)
        return VStack(alignment: .leading, spacing: 6) {
            Canvas { ctx, size in
                let w = size.width
                func r(_ a: Int, _ b: Int) -> CGRect {
                    CGRect(x: CGFloat(a) / CGFloat(n) * w, y: 0, width: max(2, CGFloat(b - a) / CGFloat(n) * w), height: size.height)
                }
                ctx.fill(Path(roundedRect: CGRect(origin: .zero, size: size), cornerRadius: 2), with: .color(Theme.strip))
                for p in profile.phases where p.kind != "riding" {
                    ctx.fill(Path(roundedRect: r(p.a, p.b), cornerRadius: 2), with: .color(PhaseStyle.color(p.kind)))
                }
                for c in profile.climbs { ctx.fill(Path(roundedRect: r(c.a, c.b), cornerRadius: 2), with: .color(Theme.stripes[3])) }
                for rep in profile.reps { ctx.fill(Path(roundedRect: r(rep.a, rep.b), cornerRadius: 2), with: .color(Theme.cobalt)) }
            }
            .frame(height: 12)
            HStack(spacing: 12) {
                ForEach(legend, id: \.0) { item in
                    HStack(spacing: 5) {
                        RoundedRectangle(cornerRadius: 2).fill(item.1).frame(width: 10, height: 6)
                        Text(item.0).font(Theme.mono(10))
                    }
                }
                Spacer(minLength: 0)
                Text("0 → \(minutesLabel(profile.count - 1, profile.stepS))").font(Theme.mono(10))
            }
            .foregroundStyle(Theme.inkMuted)
        }
    }

    private var legend: [(String, Color)] {
        var out: [(String, Color)] = [("RIDING", Theme.strip)]
        if profile.phases.contains(where: { $0.kind == "warm_up" }) { out.append(("WARM-UP", Theme.sand)) }
        if !profile.reps.isEmpty { out.append(("REPS", Theme.cobalt)) }
        if !profile.climbs.isEmpty { out.append(("CLIMBS", Theme.stripes[3])) }
        return out
    }

    private var sparks: some View {
        let others = ProfileChannel.all.filter { $0.key != focus && profile.has($0.key) }
        return VStack(alignment: .leading, spacing: 4) {
            ForEach(others, id: \.key) { c in
                Button { withAnimation(.snappy) { scrub.focus = c.key } } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(c.label).font(Theme.text(13, .semibold))
                            Spacer()
                            Text(sparkValue(c)).font(Theme.mono(11))
                        }
                        .foregroundStyle(c.color)
                        Spark(values: profile.series(c.key), at: scrub.idx, color: c.color, filled: c.key == "e")
                            .frame(height: 30)
                    }
                    .padding(.vertical, 3)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityHint("Makes \(c.label) the big chart")
            }
        }
        .padding(.top, 6)
        .overlay(alignment: .top) { Rectangle().fill(Theme.line).frame(height: 1) }
        .simultaneousGesture(drag)
    }

    private func sparkValue(_ c: ProfileChannel.Info) -> String {
        if c.key == "e" { return "↑ \(Format.number(profile.climbed(scrub.idx), decimals: 0)) m climbed" }
        let s = profile.series(c.key)
        if let i = scrub.idx, s.indices.contains(i), let v = s[i] { return "\(ProfileChannel.format(v, c.decimals)) \(c.unit)" }
        return "avg \(ProfileChannel.format(profile.average(c.key), c.decimals)) \(c.unit)"
    }

    private var drag: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { g in
                replaying?.cancel()
                // The charts and the lines under them are all as wide as the big chart.
                let f = min(1, max(0, g.location.x / max(1, chartWidth)))
                let i = Int((f * Double(profile.count - 1)).rounded())
                if scrub.idx != i { scrub.idx = i; scrub.span = nil }
            }
    }

    private func replay() {
        replaying?.cancel()
        let n = profile.count
        guard n > 1 else { return }
        replaying = Task { @MainActor in
            let step = max(1, n / 140)
            var i = 0
            scrub.span = nil
            while i < n - 1 && !Task.isCancelled {
                i = min(n - 1, i + step)
                scrub.idx = i
                try? await Task.sleep(for: .milliseconds(30))
            }
        }
    }
}

/// A small line of one channel, with a dot where you are.
private struct Spark: View {
    let values: [Double?]
    let at: Int?
    let color: Color
    let filled: Bool

    var body: some View {
        Canvas { ctx, size in
            let pts = values.enumerated().compactMap { i, v in v.map { (i, $0) } }
            guard pts.count > 1, let hi = pts.map(\.1).max(), let lo0 = pts.map(\.1).min() else { return }
            let lo = filled ? lo0 - 4 : lo0
            let n = max(values.count - 1, 1)
            func p(_ i: Int, _ v: Double) -> CGPoint {
                CGPoint(x: CGFloat(i) / CGFloat(n) * size.width, y: size.height - 2 - CGFloat((v - lo) / max(hi - lo, 1)) * (size.height - 4))
            }
            var line = Path()
            line.move(to: p(pts[0].0, pts[0].1))
            for q in pts.dropFirst() { line.addLine(to: p(q.0, q.1)) }
            if filled {
                var area = line
                area.addLine(to: CGPoint(x: p(pts.last!.0, 0).x, y: size.height))
                area.addLine(to: CGPoint(x: p(pts[0].0, 0).x, y: size.height))
                area.closeSubpath()
                ctx.fill(area, with: .color(color.opacity(0.18)))
            }
            ctx.stroke(line, with: .color(color), style: StrokeStyle(lineWidth: 1.5, lineJoin: .round))
            if let at, values.indices.contains(at) {
                let x = CGFloat(at) / CGFloat(n) * size.width
                var cur = Path(); cur.move(to: CGPoint(x: x, y: 0)); cur.addLine(to: CGPoint(x: x, y: size.height))
                ctx.stroke(cur, with: .color(Theme.ink.opacity(0.6)), lineWidth: 1)
                if let v = values[at] {
                    let c = p(at, v)
                    ctx.fill(Path(ellipseIn: CGRect(x: c.x - 3, y: c.y - 3, width: 6, height: 6)), with: .color(color))
                }
            }
        }
    }
}

// MARK: - Zone 2, climbs, reps

/// Where the heart was against zone 2: a hundred dots, below, in and above.
struct Zone2RidePanel: View {
    let zone: Zone2Split

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                MonoLabel("Where your heart was")
                Spacer()
                if zone.bpm.count == 2 { MonoLabel("zone 2 · \(zone.bpm[0])–\(zone.bpm[1])", color: Theme.label.opacity(0.75)) }
            }
            Canvas { ctx, size in
                let pitch = size.width / 50
                for i in 0..<100 {
                    let col = i % 50, row = i / 50
                    let color = i < zone.below ? Theme.cobaltSoft : i < zone.below + zone.in ? Color(hex: 0x3E9B4F) : Theme.heart
                    let c = CGPoint(x: pitch * (CGFloat(col) + 0.5), y: 6 + CGFloat(row) * 13)
                    ctx.fill(Path(ellipseIn: CGRect(x: c.x - 2.5, y: c.y - 2.5, width: 5, height: 5)), with: .color(color))
                }
            }
            .frame(height: 26)
            .accessibilityLabel("\(zone.below)% below zone 2, \(zone.in)% in it, \(zone.above)% above")
            HStack(alignment: .top) {
                figure("\(zone.below)", "below", Color(hex: 0x3352A6))
                figure("\(zone.in)", "in · \(Int((Double(zone.minutes * zone.in) / 100).rounded())) min", Color(hex: 0x2F7A3E))
                figure("\(zone.above)", "above", Theme.heart)
            }
            if let line = zone.line {
                Text(line).font(Theme.text(14)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard()
    }

    private func figure(_ v: String, _ label: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text(v).font(Theme.hero(26))
                Text("%").font(Theme.mono(13))
            }
            .foregroundStyle(color)
            Text(label.uppercased()).font(Theme.mono(10)).tracking(1).foregroundStyle(Theme.label)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The ride's climbs: tap one and it lights up on the chart and on the card's map.
struct ClimbsPanel: View {
    let profile: RideProfile
    @Binding var scrub: Scrub

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                MonoLabel("\(profile.climbs.count) climb\(profile.climbs.count == 1 ? "" : "s")")
                Spacer()
                MonoLabel("tap one", color: Theme.label.opacity(0.7))
            }
            .padding(.bottom, 8)
            ForEach(Array(profile.climbs.enumerated()), id: \.offset) { i, c in
                let on = scrub.span == c.a...max(c.a, c.b)
                Button {
                    UIImpactFeedbackGenerator(style: .light).impactOccurred()
                    withAnimation(.snappy) { scrub = Scrub(idx: c.a, span: c.a...max(c.a, c.b), focus: "e") }
                } label: {
                    HStack(spacing: 12) {
                        Text("\(i + 1)").font(Theme.hero(22)).foregroundStyle(ProfileChannel.gold).frame(width: 24)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\(Format.number(c.gainM, decimals: 0)) m over \(Format.number(c.km, decimals: 1)) km")
                                .font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
                            Text(sub(c)).font(Theme.mono(11)).foregroundStyle(Theme.inkMuted)
                        }
                        Spacer(minLength: 0)
                        Spark(values: Array(profile.e[c.a...min(max(c.a, c.b), profile.count - 1)]), at: nil,
                              color: ProfileChannel.gold, filled: true)
                            .frame(width: 72, height: 26)
                    }
                    .padding(.vertical, 10).padding(.horizontal, 6)
                    .background(on ? Theme.sand.opacity(0.6) : .clear, in: RoundedRectangle(cornerRadius: 10))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .overlay(alignment: .top) { Rectangle().fill(Theme.line).frame(height: 1) }
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard()
    }

    private func sub(_ c: RideProfile.Climb) -> String {
        var parts = ["\(Format.number(c.grade, decimals: 1))%", "\(c.minutes) MIN"]
        if let w = c.watts { parts.append("\(Int(w)) W") }
        if let hr = c.hr { parts.append("♥ \(Int(hr))") }
        return parts.joined(separator: " · ")
    }
}

/// A steady set's reps, each by thirds against the target.
struct RepsPanel: View {
    let profile: RideProfile
    @Binding var scrub: Scrub

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                MonoLabel("The reps")
                Spacer()
                if let t = profile.reps.first?.target, t.count == 2 {
                    MonoLabel("aim \(t[0])–\(t[1]) W", color: Color(hex: 0x2F7A3E))
                }
            }
            ForEach(profile.reps, id: \.self) { r in
                let on = scrub.span == r.a...max(r.a, r.b)
                Button {
                    UIImpactFeedbackGenerator(style: .light).impactOccurred()
                    withAnimation(.snappy) { scrub = Scrub(idx: r.a, span: r.a...max(r.a, r.b), focus: "p") }
                } label: {
                    HStack(alignment: .top, spacing: 12) {
                        VStack(alignment: .leading, spacing: 3) {
                            HStack(alignment: .firstTextBaseline, spacing: 6) {
                                Text("\(r.watts)").font(Theme.hero(28))
                                Text("W").font(Theme.mono(13))
                                Text(r.name).font(Theme.text(15, .semibold))
                            }
                            .foregroundStyle(Theme.ink)
                            if let line = r.line {
                                Text(line).font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                                    .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        Spacer(minLength: 0)
                        thirds(r).frame(width: 120, height: 64)
                    }
                    .padding(10)
                    .background(on ? Theme.sand.opacity(0.6) : .clear, in: RoundedRectangle(cornerRadius: 12))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            Text("Each bar is a third of the rep.").font(Theme.text(12.5)).foregroundStyle(Theme.inkMuted)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard()
    }

    private func thirds(_ r: RideProfile.Rep) -> some View {
        let vals = (r.thirds ?? []).compactMap { $0 }
        let tgt = r.target ?? []
        let lo = Double(min(vals.min() ?? 100, tgt.first ?? 100) - 20)
        let hi = Double(max(vals.max() ?? 200, tgt.last ?? 200) + 6)
        return Canvas { ctx, size in
            func y(_ w: Double) -> CGFloat { size.height - CGFloat((w - lo) / max(hi - lo, 1)) * size.height }
            if tgt.count == 2 {
                let band = CGRect(x: 0, y: y(Double(tgt[1])), width: size.width, height: y(Double(tgt[0])) - y(Double(tgt[1])))
                ctx.fill(Path(band), with: .color(Color(hex: 0x3E9B4F).opacity(0.18)))
            }
            let bw = (size.width - 16) / 3
            for (i, v) in vals.enumerated() {
                let x = CGFloat(i) * (bw + 8)
                let rect = CGRect(x: x, y: y(Double(v)), width: bw, height: size.height - y(Double(v)))
                let under = tgt.count == 2 && v < tgt[0]
                ctx.fill(Path(roundedRect: rect, cornerRadius: 3), with: .color(under ? Theme.cobaltSoft : Theme.cobalt))
                ctx.draw(Text("\(v)").font(Theme.mono(10)).foregroundColor(Theme.ink), at: CGPoint(x: x + bw / 2, y: rect.minY - 7))
            }
        }
        .accessibilityLabel("\(r.name) by thirds: \(vals.map(String.init).joined(separator: ", ")) watts")
    }
}

// MARK: - The coach's read

/// Under the ride: what it counted as, what it did for the week, one thing to try and why the work works,
/// then the full note, or ask the coach about this ride.
struct CoachsRead: View {
    let rideId: String
    let label: String
    @State private var note: TrainNote?

    var body: some View {
        Group {
            if let n = note {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 8) {
                        CoachDisc(size: 22)
                        MonoLabel("Coach's read")
                    }
                    if let c = n.counted?.title ?? n.kindTitle { row("Counted as", c) }
                    if let t = n.toward?.line { row("Part of", t) }
                    if let a = n.against?.summary { row("Did", a) } else if let j = n.jobs?.summary { row("Did", j) }
                    if let tip = n.tips.first { row("Try", tip.title, Theme.cobalt) }
                    if let l = n.learn?.text { row("Why it works", l) }
                    HStack(spacing: 10) {
                        NavigationLink { CoachView(rideId: rideId, rideLabel: label) } label: {
                            Text("Ask about this ride").font(Theme.text(14, .medium)).foregroundStyle(.white)
                                .padding(.horizontal, 16).frame(minHeight: 44).background(Theme.cobalt, in: Capsule())
                        }
                        NavigationLink { RideNoteView(rideId: rideId, initial: n) } label: {
                            Text("The full read").font(Theme.text(14, .medium)).foregroundStyle(Theme.cobalt)
                                .padding(.horizontal, 12).frame(minHeight: 44)
                        }
                    }
                    .padding(.top, 2)
                }
                .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard()
            } else {
                Color.clear.frame(height: 0)
            }
        }
        .task(id: rideId) { note = try? await APIClient().rideNote(rideId) }
    }

    private func row(_ k: String, _ v: String, _ color: Color = Theme.label) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(k.uppercased()).font(Theme.mono(10.5)).tracking(1.4).foregroundStyle(color).frame(width: 86, alignment: .leading)
            Text(v).font(Theme.text(14)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
        }
    }
}

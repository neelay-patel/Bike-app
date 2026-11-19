import SwiftUI

/// The home loop on the You screen (rideengine/analysis/repeats.py finds it); opens its full history.
struct HomeLoopLink: View {
    let route: RouteRepeat
    let rides: [RideSummary]

    var body: some View {
        NavigationLink { RepeatDetailView(history: .route(route), rides: rides) } label: {
            HomeLoopCard(route: route)
        }
        .buttonStyle(.plain)
    }
}

/// Cobalt-edged card: laps of the home loop, the best and latest speed, and a sparkline.
private struct HomeLoopCard: View {
    let route: RouteRepeat

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                MonoLabel("Home loop · \(Format.number(route.km, decimals: 0)) km")
                Spacer()
                Image(systemName: "chevron.right").font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.label)
            }
            HStack(alignment: .firstTextBaseline, spacing: 18) {
                stat("\(route.count)", "laps")
                if let best = route.best?.kmh { stat(Format.number(best, decimals: 1), "km/h best") }
                if let last = route.last?.kmh { stat(Format.number(last, decimals: 1), "km/h last") }
            }
            Sparkline(values: route.laps.compactMap(\.kmh), higherIsBetter: true)
                .frame(height: 44)
        }
        .padding(16)
        .surfaceCard()
        .overlay(alignment: .leading) {
            UnevenRoundedRectangle(topLeadingRadius: 22, bottomLeadingRadius: 22, style: .continuous)
                .fill(Theme.cobalt).frame(width: 5)
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    private func stat(_ value: String, _ unit: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Text(value).font(Theme.text(24, .semibold)).monospacedDigit().foregroundStyle(Theme.ink)
            Text(unit).font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
        }
    }
}

/// Values in order, better upwards, the best one marked.
struct Sparkline: View {
    let values: [Double]
    let higherIsBetter: Bool

    var body: some View {
        Canvas { ctx, size in
            guard values.count > 1, let lo = values.min(), let hi = values.max() else { return }
            let span = max(hi - lo, 1e-6)
            func y(_ v: Double) -> CGFloat {
                let f = (v - lo) / span
                return 4 + CGFloat(higherIsBetter ? 1 - f : f) * (size.height - 8)
            }
            let step = (size.width - 8) / CGFloat(values.count - 1)
            let pts = values.enumerated().map { CGPoint(x: 4 + CGFloat($0.offset) * step, y: y($0.element)) }
            var line = Path()
            line.addLines(pts)
            ctx.stroke(line, with: .color(Theme.cobaltSoft), lineWidth: 1.5)
            for p in pts {
                ctx.fill(Path(ellipseIn: CGRect(x: p.x - 2, y: p.y - 2, width: 4, height: 4)), with: .color(Theme.inkMuted))
            }
            let bestIndex = higherIsBetter ? values.indices.max { values[$0] < values[$1] }! : values.indices.min { values[$0] < values[$1] }!
            let b = pts[bestIndex]
            ctx.fill(Path(ellipseIn: CGRect(x: b.x - 4.5, y: b.y - 4.5, width: 9, height: 9)), with: .color(Theme.cobalt))
        }
        .accessibilityHidden(true)
    }
}

// MARK: - History

enum RepeatHistory {
    case route(RouteRepeat)
    case climb(ClimbRepeat)

    struct Entry: Identifiable {
        let id: Int
        let rideId: String
        let date: Date
        let value: Double
        let avgHr: Double?
    }

    var kind: RepeatKind { if case .route = self { .route } else { .climb } }

    var id: String {
        switch self {
        case .route(let r): r.id
        case .climb(let c): c.id
        }
    }

    var isCustom: Bool {
        switch self {
        case .route(let r): r.custom ?? false
        case .climb(let c): c.custom ?? false
        }
    }

    var title: String {
        switch self {
        case .route(let r): r.name
        case .climb(let c): c.name
        }
    }

    var subtitle: String {
        switch self {
        case .route(let r): "\(Format.number(r.km, decimals: 1)) km · \(r.count) laps · compared on average speed"
        case .climb(let c): "\(Format.number(c.lengthM / 1000, decimals: 1)) km · \(Format.number(c.gainM, decimals: 0)) m up · \(Format.number(c.grade, decimals: 1))% · timed start to top, stops included"
        }
    }

    var higherIsBetter: Bool { if case .route = self { true } else { false } }

    var entries: [Entry] {
        switch self {
        case .route(let r):
            r.laps.enumerated().compactMap { i, l in
                l.kmh.map { Entry(id: i, rideId: l.rideId, date: Date(timeIntervalSince1970: l.start), value: $0, avgHr: l.avgHr) }
            }
        case .climb(let c):
            c.attempts.enumerated().map { i, a in
                Entry(id: i, rideId: a.rideId, date: Date(timeIntervalSince1970: a.start), value: a.seconds, avgHr: a.avgHr)
            }
        }
    }

    func format(_ v: Double) -> String {
        higherIsBetter ? "\(Format.number(v, decimals: 1)) km/h" : Format.clock(v)
    }
}

/// Every lap or attempt: a dot chart over time (better is up), then the list, newest first.
struct RepeatDetailView: View {
    let history: RepeatHistory
    let rides: [RideSummary]
    @EnvironmentObject var model: AppModel
    @State private var name: String?
    @State private var renaming = false
    @State private var draft = ""

    var body: some View {
        let entries = history.entries
        let best = history.higherIsBetter ? entries.max { $0.value < $1.value } : entries.min { $0.value < $1.value }
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    MonoLabel(history.higherIsBetter ? "Route" : "Climb")
                    Text(name ?? history.title).font(Theme.heading(38)).foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(history.subtitle).font(Theme.text(14)).foregroundStyle(Theme.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.horizontal, 4)

                VStack(alignment: .leading, spacing: 10) {
                    if let best {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            MonoLabel("Best", color: Theme.panelLabel)
                            Text(history.format(best.value)).font(Theme.text(22, .semibold)).monospacedDigit()
                            Text(best.date.formatted(.dateTime.day().month(.abbreviated).year()))
                                .font(Theme.mono(12)).foregroundStyle(Theme.panelLabel)
                        }
                    }
                    TimeDots(entries: entries, higherIsBetter: history.higherIsBetter, bestId: best?.id)
                        .frame(height: 150)
                }
                .foregroundStyle(.white)
                .padding(16)
                .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))

                LazyVStack(spacing: 8) {
                    ForEach(entries.reversed()) { e in
                        if let ride = rides.first(where: { $0.rideId == e.rideId }) {
                            NavigationLink { RideDetailView(ride: ride) } label: { row(e, isBest: e.id == best?.id) }
                                .buttonStyle(.plain)
                        } else {
                            row(e, isBest: e.id == best?.id)
                        }
                    }
                }
            }
            .padding(.horizontal, 16).padding(.bottom, 24)
        }
        .background(Theme.ground.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("Rename") {
                    draft = name ?? history.title
                    renaming = true
                }
                .font(Theme.text(15, .medium))
            }
        }
        .alert("Name this \(history.kind == .route ? "route" : "climb")", isPresented: $renaming) {
            TextField("Name", text: $draft)
            Button("Save") { save(draft) }
            if history.isCustom || name != nil {
                Button("Use the automatic name", role: .destructive) { save(nil) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Only you see this name.")
        }
    }

    private func save(_ newName: String?) {
        let trimmed = newName?.trimmingCharacters(in: .whitespacesAndNewlines)
        let value = (trimmed?.isEmpty ?? true) ? nil : trimmed
        if let value { name = value }  // show it straight away; the refresh confirms it
        Task {
            await model.run("Couldn't rename it") { try await APIClient().rename(history.kind, id: history.id, to: value) }
            name = value ?? (model.you.flatMap { you in
                history.kind == .route ? you.routes?.first { $0.id == history.id }?.name
                                       : you.climbs?.first { $0.id == history.id }?.name
            })
        }
    }

    private func row(_ e: RepeatHistory.Entry, isBest: Bool) -> some View {
        HStack(spacing: 12) {
            if isBest {
                Image(systemName: "star.fill").font(.system(size: 11)).foregroundStyle(Theme.cobalt).frame(width: 14)
            } else {
                Color.clear.frame(width: 14, height: 1)
            }
            Text(e.date.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated).year()))
                .font(Theme.text(15)).foregroundStyle(Theme.ink)
            Spacer()
            if let hr = e.avgHr {
                Text("♥ \(Int(hr.rounded()))").font(Theme.mono(12)).foregroundStyle(Theme.heart)
            }
            Text(history.format(e.value)).font(Theme.text(16, isBest ? .semibold : .regular)).monospacedDigit()
                .foregroundStyle(Theme.ink)
        }
        .padding(.horizontal, 14).padding(.vertical, 11)
        .surfaceCard(radius: 14)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }
}

/// Dots placed by date, better upwards; the best one larger, in white.
private struct TimeDots: View {
    let entries: [RepeatHistory.Entry]
    let higherIsBetter: Bool
    let bestId: Int?

    var body: some View {
        Canvas { ctx, size in
            guard let first = entries.first?.date, let last = entries.last?.date,
                  let lo = entries.map(\.value).min(), let hi = entries.map(\.value).max() else { return }
            let axis: CGFloat = 16
            let plotH = size.height - axis
            let span = max(last.timeIntervalSince(first), 1)
            let vspan = max(hi - lo, 1e-6)
            for e in entries {
                let x = 6 + CGFloat(e.date.timeIntervalSince(first) / span) * (size.width - 12)
                let f = (e.value - lo) / vspan
                let y = 22 + CGFloat(higherIsBetter ? 1 - f : f) * (plotH - 28)  // top 16 pt for the label
                let r: CGFloat = e.id == bestId ? 5 : 3
                ctx.fill(Path(ellipseIn: CGRect(x: x - r, y: y - r, width: 2 * r, height: 2 * r)),
                         with: .color(e.id == bestId ? .white : Theme.panelLabel.opacity(0.8)))
            }
            ctx.fill(Path(CGRect(x: 0, y: plotH, width: size.width, height: 1)), with: .color(Theme.panelLine))
            ctx.draw(Text(first.formatted(.dateTime.month(.abbreviated).year())).font(Theme.mono(11))
                        .foregroundColor(Theme.panelLabel), at: CGPoint(x: 0, y: size.height - 6), anchor: .leading)
            ctx.draw(Text(last.formatted(.dateTime.month(.abbreviated).year())).font(Theme.mono(11))
                        .foregroundColor(Theme.panelLabel), at: CGPoint(x: size.width, y: size.height - 6), anchor: .trailing)
            ctx.draw(Text(higherIsBetter ? "FASTER ↑" : "QUICKER ↑").font(Theme.mono(10)).foregroundColor(Theme.panelLabel),
                     at: CGPoint(x: size.width, y: 4), anchor: .topTrailing)
        }
        .accessibilityLabel("\(entries.count) results over time")
    }
}

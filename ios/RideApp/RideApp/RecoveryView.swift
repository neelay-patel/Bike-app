import SwiftUI

/// Recovery on the You screen: how recovered you look (HRV and resting heart rate against your own
/// usual range), VO2 max, and heart-rate recovery after rides. From GET /v1/recovery; only ever
/// shown to the rider. Rule-based, and says it's not medical advice.
struct RecoverySection: View {
    let recovery: RecoverySummary

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Circle().fill(color(recovery.readiness.status)).frame(width: 9, height: 9)
                MonoLabel("Recovery")
            }
            Text(recovery.readiness.text)
                .font(Theme.text(16, .medium)).foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                MetricTile(trend: recovery.hrvSdnn, decimals: 0)
                MetricTile(trend: recovery.restingHr, decimals: 0)
                MetricTile(trend: recovery.vo2max, decimals: 1)
                RideRecoveryTile(recovery: recovery.rideRecovery)
            }
            if let note = recovery.vo2max.note, recovery.vo2max.latest != nil {
                Text(note).font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
            }
            Text(recovery.disclaimer).font(Theme.mono(11)).foregroundStyle(Theme.label)
        }
        .padding(16)
        .surfaceCard()
    }

    private func color(_ status: String) -> Color {
        switch status {
        case "good": Theme.cobalt
        case "watch": Color(hex: 0xB07A1E)
        case "strained": Theme.heart
        default: Theme.line
        }
    }
}

/// One reading: latest value, its usual range, and the last few months as a sparkline.
private struct MetricTile: View {
    let trend: RecoverySummary.Trend
    let decimals: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            MonoLabel(trend.label)
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(trend.latest.map { Format.number($0, decimals: decimals) } ?? "–")
                    .font(Theme.text(24, .semibold)).monospacedDigit().foregroundStyle(Theme.ink)
                Text(unit).font(Theme.text(11)).foregroundStyle(Theme.inkMuted)
            }
            Text(caption).font(Theme.text(12)).foregroundStyle(captionColor)
                .lineLimit(2).fixedSize(horizontal: false, vertical: true)
            if weekly.count > 1 {
                Sparkline(values: weekly, higherIsBetter: trend.higherIsBetter)
                    .frame(height: 28)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Theme.ground, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .accessibilityElement(children: .combine)
    }

    private var unit: String { trend.unit == "ml/kg/min" ? "ml/kg/min" : trend.unit }

    /// Daily readings are noisy: plot weekly averages when there are many.
    private var weekly: [Double] {
        let values = trend.series.map(\.value)
        guard values.count > 30 else { return values }
        return stride(from: 0, to: values.count, by: 7).map { start in
            let week = values[start..<min(start + 7, values.count)]
            return week.reduce(0, +) / Double(week.count)
        }
    }

    private var caption: String {
        if let change = trend.change90D {
            return "\(change >= 0 ? "+" : "")\(Format.number(change, decimals: 1)) in 90 days"
        }
        if let low = trend.low, let high = trend.high {
            let range = "usual \(Format.number(low, decimals: decimals))–\(Format.number(high, decimals: decimals))"
            switch trend.status {
            case "better": return "Better than usual · \(range)"
            case "worse": return (trend.higherIsBetter ? "Below usual · " : "Above usual · ") + range
            default: return range
            }
        }
        return trend.latest == nil ? "No readings yet" : "Learning your usual range"
    }

    private var captionColor: Color { trend.status == "worse" ? Theme.heart : Theme.inkMuted }
}

/// Heart rate fallen in the minute after a ride: the latest, the best, the trend.
private struct RideRecoveryTile: View {
    let recovery: RecoverySummary.RideRecovery

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            MonoLabel("After rides")
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(recovery.latest.map { "−\(Int($0.hrDrop60S.rounded()))" } ?? "–")
                    .font(Theme.text(24, .semibold)).monospacedDigit().foregroundStyle(Theme.ink)
                Text("bpm in 1 min").font(Theme.text(11)).foregroundStyle(Theme.inkMuted)
            }
            Text(caption).font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
                .lineLimit(2).fixedSize(horizontal: false, vertical: true)
            if recovery.series.count > 1 {
                Sparkline(values: recovery.series.map(\.value), higherIsBetter: true).frame(height: 28)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Theme.ground, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .accessibilityElement(children: .combine)
    }

    private var caption: String {
        guard let best = recovery.best else { return "Keep your watch on for 3 minutes after a ride" }
        let trend = recovery.trend.map { $0 == "faster" ? " · getting faster" : $0 == "slower" ? " · slower lately" : "" } ?? ""
        return "best −\(Int(best.hrDrop60S.rounded()))\(trend)"
    }
}

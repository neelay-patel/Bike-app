import ActivityKit
import SwiftUI
import WidgetKit

/// Kova's Live Activity: following a session with the phone locked (RideAlongAttributes).
@main
struct KovaLiveBundle: WidgetBundle {
    var body: some Widget { RideAlongLive() }
}

private let summit = Color(red: 0xF2 / 255, green: 0xC2 / 255, blue: 0x30 / 255)
private let panel = Color(red: 0x14 / 255, green: 0x11 / 255, blue: 0x13 / 255)
private let soft = Color(red: 0xBD / 255, green: 0xB4 / 255, blue: 0xB7 / 255)

struct RideAlongLive: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: RideAlongAttributes.self) { ctx in
            LockScreen(title: ctx.attributes.title, s: ctx.state)
                .activityBackgroundTint(panel)
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { ctx in
            let s = ctx.state
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(s.step).font(.system(size: 22, weight: .bold)).foregroundStyle(s.work ? summit : .white)
                        if let t = s.target { Text(t).font(.system(size: 14, weight: .medium)).foregroundStyle(.white) }
                    }
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Countdown(s: s).font(.system(size: 30, weight: .bold).monospacedDigit()).foregroundStyle(.white)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    if let n = s.next { Text(n).font(.system(size: 13)).foregroundStyle(soft) }
                }
            } compactLeading: {
                Text(s.step).font(.system(size: 13, weight: .bold)).foregroundStyle(s.work ? summit : .white)
            } compactTrailing: {
                Countdown(s: s).font(.system(size: 13, weight: .semibold).monospacedDigit()).frame(maxWidth: 48)
            } minimal: {
                Countdown(s: s).font(.system(size: 12, weight: .semibold).monospacedDigit())
            }
        }
    }
}

/// Counts down by itself (the app doesn't have to update it every second); still when paused.
private struct Countdown: View {
    let s: RideAlongAttributes.ContentState

    var body: some View {
        if s.paused {
            let m = Int(s.left) / 60, sec = Int(s.left) % 60
            Text(String(format: "%d:%02d", m, sec))
        } else {
            Text(timerInterval: s.starts...max(s.starts, s.ends), countsDown: true)
        }
    }
}

private struct LockScreen: View {
    let title: String
    let s: RideAlongAttributes.ContentState

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("KOVA · \(title.uppercased())").font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .foregroundStyle(soft)
                Spacer()
                Text(s.paused ? "PAUSED" : "\(s.index) OF \(s.count)")
                    .font(.system(size: 11, weight: .semibold, design: .monospaced)).foregroundStyle(soft)
            }
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(s.step).font(.system(size: 30, weight: .bold)).foregroundStyle(s.work ? summit : .white)
                    if let t = s.target { Text(t).font(.system(size: 17, weight: .semibold)).foregroundStyle(.white) }
                }
                Spacer()
                Countdown(s: s).font(.system(size: 44, weight: .bold).monospacedDigit()).foregroundStyle(.white)
                    .multilineTextAlignment(.trailing).frame(maxWidth: 140, alignment: .trailing)
            }
            if !s.paused {
                ProgressView(timerInterval: s.starts...max(s.starts, s.ends), countsDown: false) { EmptyView() } currentValueLabel: { EmptyView() }
                    .tint(s.work ? summit : soft)
            }
            if let n = s.next { Text(n).font(.system(size: 14)).foregroundStyle(soft) }
        }
        .padding(16)
    }
}

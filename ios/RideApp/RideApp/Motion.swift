import SwiftUI

// Motion (19 Nov 2026): dot-matrix numbers count up when you first see them, a new effort's card arrives
// with a little spring and a sheen, and when new rides have come in, your all-time tallies slide up from
// the bottom and count on to include them. Everything settles at once when Reduce Motion is on.

extension View {
    /// Runs once, the first time the view is at least partly on screen (scrolled into view, not merely laid out).
    func onFirstSeen(_ action: @escaping () -> Void) -> some View { modifier(OnFirstSeen(action: action)) }
}

private struct OnFirstSeen: ViewModifier {
    let action: () -> Void
    @State private var done = false

    func body(content: Content) -> some View {
        if #available(iOS 18, *) {
            content.onScrollVisibilityChange(threshold: 0.35) { visible in
                if visible && !done { done = true; action() }
            }
        } else {
            content.onAppear { if !done { done = true; action() } }
        }
    }
}

/// A band of light that passes once across a card when `run` turns true.
struct Sheen: View {
    let run: Bool
    var delay: Double = 0.3
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var x: CGFloat = -0.6

    var body: some View {
        GeometryReader { g in
            LinearGradient(colors: [.clear, .white.opacity(0.5), .clear], startPoint: .leading, endPoint: .trailing)
                .frame(width: g.size.width * 0.4, height: g.size.height * 1.4)
                .rotationEffect(.degrees(16))
                .offset(x: x * g.size.width, y: -g.size.height * 0.2)
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
        .onAppear(perform: start)
        .onChange(of: run) { _, _ in start() }
        .onTabVisit { replay({ x = -0.6 }, then: start) }
    }

    private func start() {
        guard run, !reduceMotion, x < 0 else { return }
        withAnimation(.easeInOut(duration: 1.2).delay(delay)) { x = 1.3 }
    }
}

/// New rides since you last looked: the all-time tallies slide up from the bottom and count on to include
/// them. Tap or swipe down to put it away; it goes on its own after a few seconds.
struct NewRideMoment: View {
    let rides: [RideSummary]
    let you: YouSummary
    let done: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var counted = false

    private var addedKm: Double { rides.reduce(0) { $0 + $1.summary.km } }
    private var addedHours: Double { rides.reduce(0) { $0 + $1.summary.movingH } }
    private var addedUp: Double { rides.reduce(0) { $0 + ($1.summary.ascentM ?? 0) } }
    /// Kilometres lead, a trainer's too (Zwift); a session with no distance at all leads with the hours.
    private var kmLead: Bool { addedKm >= 0.5 }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Image(systemName: "sparkles").symbolEffect(.bounce, value: counted)
                Text(rides.count == 1 ? "NEW RIDE ADDED" : "\(rides.count) NEW RIDES ADDED").font(Theme.mono(11)).tracking(1.4)
                Spacer()
                Button(action: done) {
                    Image(systemName: "xmark").font(.system(size: 12, weight: .semibold)).frame(width: 36, height: 32)
                }
                .accessibilityLabel("Close")
            }
            .foregroundStyle(Theme.cobalt)
            .padding(.leading, 16).padding(.trailing, 6).padding(.vertical, 4)
            .background(Theme.sand)

            VStack(alignment: .leading, spacing: 4) {
                MonoLabel(kmLead ? "All time" : "In the saddle, all time", color: Theme.cobaltSoft)
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    if kmLead {
                        CountingText(value: counted ? you.all.km : max(0, you.all.km - addedKm)).font(Theme.hero(56))
                        Text("km").font(Theme.text(16)).foregroundStyle(Theme.cobaltSoft)
                    } else {
                        CountingText(value: counted ? you.all.hours : max(0, you.all.hours - addedHours), decimals: 1)
                            .font(Theme.hero(56))
                        Text("h").font(Theme.text(16)).foregroundStyle(Theme.cobaltSoft)
                    }
                    Spacer(minLength: 4)
                    Text(kmLead ? "+\(Format.number(addedKm, decimals: 1)) km" : "+\(Format.duration(hours: addedHours)) h")
                        .font(Theme.mono(13)).foregroundStyle(Theme.ink)
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(Theme.sand, in: Capsule())
                        .opacity(counted ? 1 : 0)
                        .scaleEffect(counted ? 1 : 0.6)
                }
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 16).padding(.vertical, 14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.cobalt)

            HStack(alignment: .top, spacing: 12) {
                if kmLead {
                    stat("In the saddle", from: you.all.hours - addedHours, to: you.all.hours, unit: "h", decimals: 1)
                }
                stat("Rides", from: Double(you.all.rides - rides.count), to: Double(you.all.rides), unit: nil)
                if kmLead {
                    stat("Climbed", from: you.all.ascentM - addedUp, to: you.all.ascentM, unit: "m")
                } else {
                    stat("Streak", from: Double(you.streak.currentWeeks), to: Double(you.streak.currentWeeks),
                         unit: you.streak.currentWeeks == 1 ? "week" : "weeks")
                }
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 16).padding(.vertical, 14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.panel)
            Ribbon(height: 3)
        }
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .shadow(color: .black.opacity(0.22), radius: 20, y: 8)
        .contentShape(Rectangle())
        .onTapGesture(perform: done)
        .gesture(DragGesture(minimumDistance: 12).onEnded { if $0.translation.height > 30 { done() } })
        .sensoryFeedback(.success, trigger: counted)
        .task {
            guard !reduceMotion else { counted = true; return }
            try? await Task.sleep(for: .milliseconds(550))
            withAnimation(.easeOut(duration: 1.8)) { counted = true }
            try? await Task.sleep(for: .seconds(7))
            done()
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityText)
    }

    private func stat(_ label: String, from: Double, to: Double, unit: String?, decimals: Int = 0) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            MonoLabel(label, color: Theme.panelLabel)
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                CountingText(value: counted ? to : max(0, from), decimals: decimals).font(Theme.hero(26))
                if let unit { Text(unit).font(Theme.text(12, .medium)) }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var accessibilityText: String {
        let added = kmLead ? "\(Format.number(addedKm, decimals: 1)) kilometres" : "\(Format.duration(hours: addedHours)) hours"
        let total = kmLead ? "\(Format.number(you.all.km, decimals: 0)) kilometres" : "\(Format.number(you.all.hours, decimals: 1)) hours"
        return "\(rides.count == 1 ? "New ride" : "\(rides.count) new rides") added: \(added). All time: \(total), \(you.all.rides) rides."
    }
}

// MARK: - Bringing the tabs to life (21 Nov 2026)
// Cards arrive in turn, charts draw themselves in the way you'd ride them (left to right), routes trace their
// line, and a few calm loops say "this is live" or "this is next": a light running from today down to what's
// next, a ripple on the week's next session, a slow swell on a rest day. All quiet, all once unless it's a
// signpost, and all still when Reduce Motion is on.

private struct TabVisitKey: EnvironmentKey { static let defaultValue = 0 }

extension EnvironmentValues {
    /// Goes up each time the tab is opened again (ContentView): what arrives or draws in does it again.
    var tabVisit: Int {
        get { self[TabVisitKey.self] }
        set { self[TabVisitKey.self] = newValue }
    }
}

extension View {
    /// Runs `action` each time this view's tab is opened again (not the first time it appears: use onAppear).
    func onTabVisit(_ action: @escaping () -> Void) -> some View { modifier(OnTabVisit(action: action)) }
}

private struct OnTabVisit: ViewModifier {
    let action: () -> Void
    @Environment(\.tabVisit) private var visit
    func body(content: Content) -> some View { content.onChange(of: visit) { _, _ in action() } }
}

/// Sets `state` back without animating, then (a moment later) plays `again`: for replaying on a tab visit.
@MainActor func replay(_ reset: @escaping () -> Void, then again: @escaping () -> Void) {
    var t = Transaction()
    t.disablesAnimations = true
    withTransaction(t, reset)
    Task { @MainActor in
        try? await Task.sleep(for: .milliseconds(60))   // a frame or two with it reset, so the change shows
        again()
    }
}

extension View {
    /// Fades and rises into place when it appears (and each time its tab opens), `order` beats after the first.
    func arrive(_ order: Int = 0) -> some View { modifier(Arrive(order: order)) }

    /// Reveals from left to right the first time it's seen (and `ready`, for charts whose data loads later).
    func revealOnFirstSeen(ready: Bool = true, duration: Double = 1.1, delay: Double = 0.1) -> some View {
        modifier(Reveal(ready: ready, duration: duration, delay: delay))
    }

    /// A slow, calm swell for as long as it's on screen.
    func breathing(_ on: Bool = true, scale: CGFloat = 1.06, period: Double = 2.6) -> some View {
        modifier(Breathing(on: on, scale: scale, period: period))
    }
}

private struct Arrive: ViewModifier {
    let order: Int
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shown = false

    func body(content: Content) -> some View {
        let on = shown || reduceMotion
        content
            .opacity(on ? 1 : 0)
            .offset(y: on ? 0 : 26)
            .onAppear(perform: play)
            .onTabVisit { if !reduceMotion { replay({ shown = false }, then: play) } }
    }

    private func play() {
        guard !shown else { return }
        withAnimation(.spring(response: 0.7, dampingFraction: 0.84).delay(0.05 + Double(min(order, 8)) * 0.1)) {
            shown = true
        }
    }
}

private struct Reveal: ViewModifier {
    let ready: Bool
    let duration: Double
    let delay: Double
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var seen = false
    @State private var p: CGFloat = 0

    func body(content: Content) -> some View {
        content
            .mask(alignment: .leading) {
                GeometryReader { g in Rectangle().frame(width: g.size.width * (reduceMotion ? 1 : p)) }
            }
            .onFirstSeen { seen = true; start() }
            .onChange(of: ready) { _, _ in start() }
    }

    private func start() {
        guard seen, ready, p == 0 else { return }
        withAnimation(.easeInOut(duration: duration).delay(delay)) { p = 1 }
    }
}

private struct Breathing: ViewModifier {
    let on: Bool
    let scale: CGFloat
    let period: Double
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        if on && !reduceMotion {
            content.phaseAnimator([false, true]) { v, up in
                v.scaleEffect(up ? scale : 1).opacity(up ? 1 : 0.8)
            } animation: { _ in .easeInOut(duration: period / 2) }
        } else {
            content
        }
    }
}

/// From today to what's next: a short dotted thread, and now and then a light runs down it.
struct FlowThread: View {
    var dots = 4
    var color: Color = Theme.label
    var light: Color = Theme.cobalt
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private struct Value { var y: CGFloat = 0; var opacity: Double = 0; var scale: CGFloat = 0.6 }

    var body: some View {
        let step: CGFloat = 7
        let travel = CGFloat(dots - 1) * step
        ZStack(alignment: .top) {
            VStack(spacing: step - 3) {
                ForEach(0..<dots, id: \.self) { _ in Circle().fill(color.opacity(0.6)).frame(width: 3, height: 3) }
            }
            .padding(.top, 2.5)
            if !reduceMotion {
                Circle().fill(light).frame(width: 8, height: 8)
                    .shadow(color: light.opacity(0.6), radius: 5)
                    .keyframeAnimator(initialValue: Value(), repeating: true) { c, v in
                        c.scaleEffect(v.scale).offset(y: v.y).opacity(v.opacity)
                    } keyframes: { _ in
                        KeyframeTrack(\.y) {
                            LinearKeyframe(0, duration: 0.6)
                            CubicKeyframe(travel, duration: 1.2)
                            LinearKeyframe(travel, duration: 1.6)
                        }
                        KeyframeTrack(\.opacity) {
                            LinearKeyframe(0, duration: 0.6)
                            LinearKeyframe(1, duration: 0.3)
                            LinearKeyframe(1, duration: 0.6)
                            LinearKeyframe(0, duration: 0.5)
                            LinearKeyframe(0, duration: 1.4)
                        }
                        KeyframeTrack(\.scale) {
                            LinearKeyframe(0.6, duration: 0.6)
                            SpringKeyframe(1, duration: 0.4)
                            LinearKeyframe(1, duration: 0.8)
                            LinearKeyframe(0.6, duration: 1.6)
                        }
                    }
            }
        }
        .frame(width: 12, height: travel + 8, alignment: .top)
        .accessibilityHidden(true)
    }
}

/// A ring that widens and fades, now and then: "this one's next".
struct Ripple: View {
    var color: Color = Theme.cobalt
    var size: CGFloat = 16
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private struct Value { var scale: CGFloat = 1; var opacity: Double = 0 }

    var body: some View {
        if !reduceMotion {
            Circle().stroke(color, lineWidth: 2).frame(width: size, height: size)
                .keyframeAnimator(initialValue: Value(), repeating: true) { c, v in
                    c.scaleEffect(v.scale).opacity(v.opacity)
                } keyframes: { _ in
                    KeyframeTrack(\.scale) {
                        LinearKeyframe(1, duration: 0.8)
                        CubicKeyframe(2.7, duration: 1.5)
                        LinearKeyframe(2.7, duration: 1.0)
                    }
                    KeyframeTrack(\.opacity) {
                        LinearKeyframe(0, duration: 0.8)
                        LinearKeyframe(0.9, duration: 0.05)
                        CubicKeyframe(0, duration: 1.45)
                        LinearKeyframe(0, duration: 1.0)
                    }
                }
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
    }
}

/// Bars that grow up from their baseline in turn, left to right, the first time they appear.
struct GrowIn: ViewModifier {
    let index: Int
    let count: Int
    let grown: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        let on = grown || reduceMotion
        content
            .scaleEffect(x: 1, y: on ? 1 : 0.04, anchor: .bottom)
            .opacity(on ? 1 : 0.3)
            .animation(reduceMotion ? nil : .spring(response: 0.5, dampingFraction: 0.78)
                .delay(0.15 + 0.7 * Double(index) / Double(max(count, 1))), value: grown)
    }
}

/// A route's line drawing itself from start to finish, the first time it's seen.
struct DrawnRoute: View {
    let points: [[Double]]
    var color: Color = Theme.cobalt
    var lineWidth: CGFloat = 2
    var duration: Double = 1.4
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var drawn: CGFloat = 0

    var body: some View {
        RouteShape(points: points)
            .trim(from: 0, to: reduceMotion ? 1 : drawn)
            .stroke(color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round, lineJoin: .round))
            .onFirstSeen { withAnimation(.easeInOut(duration: duration).delay(0.15)) { drawn = 1 } }
    }
}

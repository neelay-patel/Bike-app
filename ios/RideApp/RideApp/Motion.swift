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
    }

    private func start() {
        guard run, !reduceMotion, x < 0 else { return }
        withAnimation(.easeInOut(duration: 1.1).delay(0.3)) { x = 1.3 }
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

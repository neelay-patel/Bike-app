import SwiftUI

// Kova (19-20 Nov 2026): the app's name, its mark and what it stands for. Finnish for strong; also
// Kilometres, Output, VO₂, Ascent, with Ascent in the summit's yellow. (Ascend was tried for a day; Neelay
// went back to Ascent.) The app icon is the same mark (scripts/make_icon.swift --no-ribbon).

private let summit = Theme.stripes[3]   // the ribbon's yellow: the summit dot, and Ascent

/// The mark: five columns of dots rising to a yellow summit. `shown` columns are drawn (for the opening
/// screen's build-up); all five by default.
struct KovaMark: View {
    var size: CGFloat = 112
    var color: Color = .white
    var shown = 5

    // The icon's grid: dots 19 across, 22 apart, in a 107-unit square.
    private var r: CGFloat { 9.5 * size / 107 }
    private var pitch: CGFloat { 22 * size / 107 }
    private func at(_ col: Int, _ row: Int) -> CGSize {
        CGSize(width: CGFloat(col) * pitch, height: size - 2 * r - CGFloat(row) * pitch)
    }

    var body: some View {
        let step = max(shown - 1, 0)   // where the yellow dot is: the top of the newest column
        ZStack(alignment: .topLeading) {
            // The white dots. The one under the yellow dot is held back until the yellow moves on, so the
            // yellow leaves a trail of white behind it.
            ForEach(0..<5, id: \.self) { col in
                ForEach(0...col, id: \.self) { row in
                    let on = col < shown && !(col == step && row == col)
                    Circle()
                        .fill(color)
                        .frame(width: 2 * r, height: 2 * r)
                        .offset(at(col, row))
                        .opacity(on ? 1 : 0)
                        .scaleEffect(on ? 1 : 0.4)
                }
            }
            // One yellow dot that travels: as each column appears it slides up to the top of it, step by step
            // to the summit. Drawn whole, it is the summit.
            Circle()
                .fill(summit)
                .frame(width: 2 * r, height: 2 * r)
                .offset(at(step, step))
                .opacity(shown > 0 ? 1 : 0)
        }
        .frame(width: size, height: size, alignment: .topLeading)
        .accessibilityHidden(true)
    }
}

/// The opening screen: the climb builds column by column, then the name arrives letter by letter, each one
/// rising and sharpening out of a soft blur, held long enough to take in (about 4 s in all; Neelay found 2 s
/// too quick), then it fades into the app. A tap skips it. On graphite, like the launch screen underneath,
/// so there's no flash. (The KILOMETRES. OUTPUT. VO₂. ASCENT. line under the name was dropped 21 Nov 2026;
/// the meaning lives in Settings › About Kova.)
struct KovaOpening: View {
    let done: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shown = 0
    @State private var letters = 0          // how many of K, O, V, A are in
    @State private var finished = false
    @State private var leaving = false
    @State private var gone = false

    private static let name = Array("KOVA")

    /// Leaving in two steps so it doesn't feel sudden: the mark and name lift and fade first, then the
    /// graphite fades slowly to show the app, with the status bar coming back as it goes. The fade is done
    /// here, on the view's own opacity: a removal transition from the App's state jumped in one frame.
    /// `done` removes the screen once it's invisible.
    private func finish() {
        guard !finished else { return }
        finished = true
        withAnimation(.easeIn(duration: 0.35)) { leaving = true }
        Task {
            try? await Task.sleep(for: .milliseconds(200))
            withAnimation(.easeInOut(duration: 0.8)) { gone = true }
            try? await Task.sleep(for: .milliseconds(850))
            done()
        }
    }

    var body: some View {
        ZStack {
            Theme.panel.ignoresSafeArea().opacity(gone ? 0 : 1)
            VStack(spacing: 30) {
                KovaMark(size: 112, shown: shown)
                HStack(spacing: 0) {
                    ForEach(Array(Self.name.enumerated()), id: \.offset) { i, ch in
                        let on = i < letters
                        Text(String(ch))
                            .font(Theme.hero(80)).foregroundStyle(.white)
                            .opacity(on ? 1 : 0)
                            .blur(radius: on ? 0 : 10)
                            .offset(y: on ? 0 : 14)
                            .scaleEffect(on ? 1 : 0.92, anchor: .bottom)
                    }
                }
            }
            .scaleEffect(leaving ? 1.06 : 1)
            .opacity(leaving ? 0 : 1)
        }
        .statusBarHidden(!leaving)   // the app's status bar is dark-on-light; on graphite it would vanish
        .contentShape(Rectangle())
        .onTapGesture(perform: finish)
        .allowsHitTesting(!leaving)   // once it's going, taps reach the app underneath
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Kova")
        .accessibilityAddTraits(.isButton)
        .accessibilityHint("Opens the app")
        .task {
            if reduceMotion {
                shown = 5
                letters = Self.name.count
                try? await Task.sleep(for: .milliseconds(2500))
            } else {
                try? await Task.sleep(for: .milliseconds(350))   // let iOS's own launch zoom finish first
                for col in 1...5 {
                    try? await Task.sleep(for: .milliseconds(320))   // slower, so the yellow dot's climb reads
                    withAnimation(.spring(response: 0.5, dampingFraction: 0.65)) { shown = col }
                }
                try? await Task.sleep(for: .milliseconds(380))   // the summit dot settles first
                for i in 1...Self.name.count {
                    withAnimation(.easeOut(duration: 0.7)) { letters = i }
                    try? await Task.sleep(for: .milliseconds(110))
                }
                try? await Task.sleep(for: .milliseconds(1900))
            }
            finish()
        }
    }
}

/// Settings › About Kova: the name and the four things it stands for.
struct AboutKovaView: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .center, spacing: 14) {
                    KovaMark(size: 40, color: Theme.ink)
                    Text("About Kova").font(Theme.heading(42)).foregroundStyle(Theme.ink)
                }
                .padding(.top, 8)
                Text("Kova is Finnish for strong. It also stands for the four things we will help you build:")
                    .font(Theme.text(15)).foregroundStyle(Theme.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
                VStack(spacing: 10) {
                    row("K", "Kilometres", "Ride further.")
                    row("O", "Output", "More power.")
                    row("V", "VO₂", "A bigger engine.")
                    ascent
                }
                Text("Every ride from every device, merged into one, and read for what makes you stronger.")
                    .font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 6)
            }
            .padding(.horizontal, 20).padding(.bottom, 32)
        }
        .background(Theme.ground.ignoresSafeArea())
        .toolbar(.visible, for: .navigationBar)
        .navigationBarTitleDisplayMode(.inline)
    }

    private func row(_ letter: String, _ word: String, _ line: String) -> some View {
        HStack(spacing: 16) {
            Text(letter).font(Theme.hero(40)).foregroundStyle(Theme.cobalt).frame(width: 34)
            VStack(alignment: .leading, spacing: 1) {
                Text(word).font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                Text(line).font(Theme.text(14)).foregroundStyle(Theme.inkMuted)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .surfaceCard(radius: 16)
        .accessibilityElement(children: .combine)
    }

    /// The last letter: on graphite, in the summit's yellow.
    private var ascent: some View {
        HStack(spacing: 16) {
            Text("A").font(Theme.hero(40)).foregroundStyle(summit).frame(width: 34)
            VStack(alignment: .leading, spacing: 1) {
                Text("Ascent").font(Theme.text(16, .semibold)).foregroundStyle(summit)
                Text("Rise to the climb.").font(Theme.text(14)).foregroundStyle(Theme.panelLabel)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

/// The About Kova row in Settings.
struct AboutKovaRow: View {
    var body: some View {
        NavigationLink {
            AboutKovaView()
        } label: {
            HStack(spacing: 14) {
                KovaMark(size: 30, color: Theme.ink)
                Text("About Kova").font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                Spacer(minLength: 0)
                Image(systemName: "chevron.right").foregroundStyle(Theme.label)
            }
            .padding(14)
            .surfaceCard(radius: 16)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

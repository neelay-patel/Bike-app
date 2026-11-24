import SwiftUI

// Zone 2 (24 Nov 2026, docs/train-method.md "Zone 2"): the easy, aerobic riding most of a week should be. One key
// number everywhere: the share of moving time in zone 2, with how much was above and below. The range is worked
// out from heart rate reserve until the rider sets their own; the latest steady ride checks it.

private let above = Theme.heart
private let inside = Theme.cobalt
private let below = Theme.cobaltSoft

/// Below, in, above, as one bar.
struct Zone2Bar: View {
    let split: Zone2Split
    var height: CGFloat = 12

    var body: some View {
        GeometryReader { g in
            HStack(spacing: 2) {
                seg(below, split.below, g.size.width)
                seg(inside, split.in, g.size.width)
                seg(above, split.above, g.size.width)
            }
        }
        .frame(height: height)
        .clipShape(Capsule())
        .accessibilityElement()
        .accessibilityLabel("\(split.in)% in zone 2, \(split.above)% above, \(split.below)% below")
    }

    @ViewBuilder private func seg(_ c: Color, _ pct: Int, _ w: CGFloat) -> some View {
        if pct > 0 { c.frame(width: max(3, (w - 4) * CGFloat(pct) / 100)) }
    }
}

/// The key number and the bar: "52% in zone 2 · 31% above · 17% below".
struct Zone2Numbers: View {
    let split: Zone2Split
    var big: CGFloat = 34
    /// The range beside the key, where it isn't already shown.
    var showRange = true

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text("\(split.in)%").font(Theme.hero(big)).foregroundStyle(Theme.ink)
                Text("in zone 2").font(Theme.text(15, .medium)).foregroundStyle(Theme.ink)
            }
            Zone2Bar(split: split)
            HStack(spacing: 14) {
                key(below, "\(split.below)% below")
                key(above, "\(split.above)% above")
                Spacer()
                if showRange {
                    Text("\(split.bpm.first ?? 0)–\(split.bpm.last ?? 0) bpm").font(Theme.mono(11)).foregroundStyle(Theme.label)
                }
            }
        }
    }

    private func key(_ c: Color, _ t: String) -> some View {
        HStack(spacing: 5) {
            Circle().fill(c).frame(width: 8, height: 8)
            Text(t).font(Theme.text(13)).foregroundStyle(Theme.inkSoft)
        }
    }
}

/// After a ride: the split, and the one line where zone 2 was the point.
struct Zone2RideCard: View {
    let split: Zone2Split

    var body: some View {
        NavigationLink { Zone2View() } label: {
            VStack(alignment: .leading, spacing: 10) {
                MonoLabel("Zone 2")
                Zone2Numbers(split: split)
                if let l = split.line {
                    Text(l).font(Theme.text(14)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
                }
                if let w = split.watts {
                    Text("\(w) W on average while in zone 2.").font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                }
            }
            .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
        }
        .buttonStyle(.plain)
    }
}

/// On Train: this week's zone 2 in one line, opening the zone 2 page.
struct Zone2WeekCard: View {
    @EnvironmentObject var model: AppModel
    @State private var z: TrainZone2?

    var body: some View {
        NavigationLink { Zone2View() } label: {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    MonoLabel("Zone 2 this week")
                    Spacer()
                    if let r = z?.range { Text("\(r[0])–\(r[1]) bpm").font(Theme.mono(11)).foregroundStyle(Theme.label) }
                    Image(systemName: "chevron.right").font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.label)
                }
                if let w = z?.week {
                    Zone2Numbers(split: w, big: 28, showRange: false)
                    if let l = w.line {
                        Text(l).font(Theme.text(13)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
                    }
                } else if z?.range != nil {
                    Text("No riding with heart rate yet this week.").font(Theme.text(14)).foregroundStyle(Theme.inkMuted)
                } else if let why = z?.why {
                    Text(why).font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
        }
        .buttonStyle(.plain)
        .opacity(z == nil ? 0 : 1)
        .task(id: model.today?.latest?.rideId) { z = try? await APIClient().zone2() }
    }
}

/// Zone 2 in one place: the range and where it came from, the check from a steady ride, this week, and watts at
/// zone 2 by month (it rising is the proof the easy riding works).
struct Zone2View: View {
    @EnvironmentObject var model: AppModel
    @State private var z: TrainZone2?
    @State private var setting = false
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Zone 2").font(Theme.heading(40)).foregroundStyle(Theme.ink).padding(.horizontal, 4)
                if let z {
                    range(z)
                    if let c = z.check {
                        card {
                            VStack(alignment: .leading, spacing: 6) {
                                MonoLabel("Checked from your riding")
                                Text(c.line).font(Theme.text(14)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    if let w = z.week {
                        card {
                            VStack(alignment: .leading, spacing: 10) {
                                MonoLabel("This week")
                                Zone2Numbers(split: w, showRange: false)
                                if let l = w.line {
                                    Text(l).font(Theme.text(14)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                    }
                    if let t = z.trend, !t.isEmpty { trend(t) }
                    why
                } else if let error {
                    Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart)
                } else {
                    ProgressView().padding(40)
                }
            }
            .padding(16)
        }
        .background(Theme.ground.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .task { await load() }
        .sheet(isPresented: $setting) {
            Zone2RangeSheet(own: z?.own, worked: z?.source == "yours" ? nil : z?.range) { await load() }
        }
    }

    private func load() async {
        do { z = try await APIClient().zone2() } catch { self.error = error.localizedDescription }
    }

    private func range(_ z: TrainZone2) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            MonoLabel("Your zone 2", color: Theme.panelLabel)
            if let r = z.range {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("\(r[0])–\(r[1])").font(Theme.hero(44)).foregroundStyle(.white)
                    Text("bpm").font(Theme.text(16, .medium)).foregroundStyle(Theme.panelLabel)
                }
                if let t = z.talk { Text(t).font(Theme.text(15)).foregroundStyle(.white) }
                if let how = z.how {
                    Text(z.source == "yours" ? "From \(how)." : "Worked out from \(how).")
                        .font(Theme.text(13)).foregroundStyle(Theme.panelLabel).fixedSize(horizontal: false, vertical: true)
                }
            } else if let why = z.why {
                Text(why).font(Theme.text(14)).foregroundStyle(.white).fixedSize(horizontal: false, vertical: true)
            }
            Button(z.source == "yours" ? "Change your range" : "Set your own range") { setting = true }
                .font(Theme.text(14, .semibold)).foregroundStyle(Theme.sand).padding(.top, 4)
        }
        .padding(18).frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    /// Watts at zone 2, month by month: bars, the latest in cobalt. One month: the number, and the trend to come.
    private func trend(_ t: [TrainZone2.Month]) -> some View {
        let top = Double(t.map(\.watts).max() ?? 1)
        let low = Double(t.map(\.watts).min() ?? 0) * 0.8
        return card {
            VStack(alignment: .leading, spacing: 10) {
                MonoLabel("Watts at zone 2")
                if t.count == 1, let m = t.first {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text("\(m.watts)").font(Theme.hero(34)).foregroundStyle(Theme.ink)
                        Text("W in \(month(m.month, long: true))").font(Theme.text(15, .medium)).foregroundStyle(Theme.ink)
                    }
                    Text("The power you hold at an easy zone 2 heart rate. Next month's number starts the trend: it rising is your base growing.")
                        .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                } else {
                    Text("The power you hold at the same easy heart rate. It rising is your base growing.")
                        .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                    HStack(alignment: .bottom, spacing: 10) {
                        ForEach(Array(t.enumerated()), id: \.element.id) { i, m in
                            VStack(spacing: 4) {
                                Text("\(m.watts)").font(Theme.mono(11)).foregroundStyle(Theme.ink)
                                RoundedRectangle(cornerRadius: 4)
                                    .fill(i == t.count - 1 ? inside : below)
                                    .frame(width: 40, height: max(8, 90 * (Double(m.watts) - low) / max(1, top - low)))
                                Text(month(m.month)).font(Theme.mono(10)).foregroundStyle(Theme.label)
                            }
                            .frame(maxWidth: .infinity)
                        }
                    }
                    .frame(height: 130, alignment: .bottom)
                }
                Text("Rides with power only (the trainer, for now).").font(Theme.text(12)).foregroundStyle(Theme.label)
            }
        }
    }

    private var why: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: "lightbulb").font(.system(size: 14)).foregroundStyle(Theme.cobalt)
            VStack(alignment: .leading, spacing: 4) {
                MonoLabel("Why it works")
                Text("Hours in zone 2 grow the small blood vessels and the energy factories in your legs, so the same pace costs less. Keeping easy days easy is also what lets the hard days be truly hard.")
                    .font(Theme.text(15)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
    }

    private func month(_ m: String, long: Bool = false) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM"
        f.locale = Locale(identifier: "en_US_POSIX")
        guard let d = f.date(from: m) else { return m }
        return d.formatted(.dateTime.month(long ? .wide : .abbreviated))
    }

    private func card<C: View>(@ViewBuilder _ content: () -> C) -> some View {
        content().padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
    }
}

/// Your own range: from a lab test, or the zones on your Watch or Edge. Clear it to have it worked out again.
private struct Zone2RangeSheet: View {
    @Environment(\.dismiss) private var dismiss
    let own: String?
    let worked: [Int]?
    let saved: () async -> Void
    @State private var lo = ""
    @State private var hi = ""
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack {
                        TextField("From", text: $lo).keyboardType(.numberPad)
                        Text("–")
                        TextField("To", text: $hi).keyboardType(.numberPad)
                        Text("bpm").foregroundStyle(Theme.inkMuted)
                    }
                } footer: {
                    Text("From a lab test, or the zone 2 your Watch or Edge shows (on the Watch: Settings › Workout › Heart Rate Zones). Every ride and session follows it.")
                }
                if own != nil {
                    Section {
                        Button("Work it out for me again", role: .destructive) { Task { await save(nil) } }
                    }
                }
                if let error { Text(error).foregroundStyle(Theme.heart) }
            }
            .navigationTitle("Your zone 2")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save("\(lo)-\(hi)") } }.disabled(lo.isEmpty || hi.isEmpty)
                }
            }
            .onAppear {
                let parts = (own ?? "").split(separator: "-").map(String.init)
                if parts.count == 2 { lo = parts[0]; hi = parts[1] }
                else if let w = worked, w.count == 2 { lo = "\(w[0])"; hi = "\(w[1])" }
            }
        }
        .presentationDetents([.medium])
    }

    private func save(_ range: String?) async {
        do {
            _ = try await APIClient().setZone2(range)
            await saved()
            dismiss()
        } catch { self.error = error.localizedDescription }
    }
}

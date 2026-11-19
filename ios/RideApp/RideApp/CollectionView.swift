import SwiftUI

// The Efforts tab's pieces (18 Nov 2026): new efforts first as their full card, this month as one slim
// line, then your collection: every effort's card by month (older years folded), holo for personal bests,
// empty slots for the weeks you didn't ride, or the same as a list.

/// Ride cards drawn so far on this screen, one per ride, kept while you swipe between them.
@MainActor
final class CardStore: ObservableObject {
    private var cards: [String: CardRenderer] = [:]
    /// Each card's size once drawn (indoor cards are shorter), so the pager can fit the one showing.
    @Published private(set) var sizes: [String: CGSize] = [:]

    func renderer(_ rideId: String) -> CardRenderer {
        if let r = cards[rideId] { return r }
        let r = CardRenderer()
        r.onResize = { [weak self] size in self?.sizes[rideId] = size }
        cards[rideId] = r
        return r
    }

    func size(_ rideId: String) -> CGSize { sizes[rideId] ?? CardRenderer.size }
}

/// The newest efforts as their full ride card: the ones that arrived since you last looked ("New"), else
/// the latest one. Swipe between them; tap a card for everything about the ride.
struct EffortHero: View {
    let rides: [RideSummary]        // newest first
    let isNew: Bool
    let since: Date?
    @StateObject private var cards = CardStore()
    @State private var page = 0
    @State private var bounce = 0
    @State private var confirmShare = false
    @State private var shareImage: UIImage?

    private var ride: RideSummary { rides[min(page, rides.count - 1)] }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                if isNew {
                    HStack(spacing: 4) {
                        Image(systemName: "sparkles").symbolEffect(.bounce, value: bounce)
                        Text("NEW").font(Theme.mono(11))
                    }
                    .foregroundStyle(Theme.cobalt)
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(Theme.sand, in: Capsule())
                }
                MonoLabel(title, color: isNew ? Theme.cobalt : Theme.label)
                Spacer()
                if rides.count > 1 { MonoLabel("\(page + 1) of \(rides.count)") }
            }
            .padding(.horizontal, 4)

            if rides.count > 1 {
                TabView(selection: $page) {
                    ForEach(Array(rides.enumerated()), id: \.element.id) { i, r in
                        card(r).padding(.horizontal, 2).frame(maxHeight: .infinity, alignment: .top).tag(i)
                    }
                }
                .tabViewStyle(.page(indexDisplayMode: .never))
                .aspectRatio(cards.size(ride.rideId).width / cards.size(ride.rideId).height, contentMode: .fit)
                .frame(maxWidth: CardRenderer.size.width).frame(maxWidth: .infinity)
                dots
            } else {
                card(ride)
            }

            if let top = ride.notes?.first {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: top.pb ? "star.fill" : "sparkle").font(.system(size: 14)).foregroundStyle(Theme.cobalt)
                    Text(top.text).font(Theme.heading(26)).foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.horizontal, 4)
                .id(ride.rideId)
                .transition(.opacity)
            }
            HStack(spacing: 8) {
                Button {
                    if ride.use["share"]?.allowed ?? false { Task { await share() } } else { confirmShare = true }
                } label: {
                    Label("Share card", systemImage: "square.and.arrow.up")
                }
                .buttonStyle(PrimaryButton())
                .disabled(!cards.renderer(ride.rideId).isLoaded)
                NavigationLink { RideDetailView(ride: ride) } label: {
                    Label("What you did", systemImage: "waveform.path.ecg")
                }
                .buttonStyle(SecondaryButton())
                Spacer(minLength: 0)
            }
        }
        .animation(.easeInOut(duration: 0.2), value: page)
        .onAppear { if isNew { bounce += 1 } }
        .onChange(of: rides.map(\.rideId)) { _, _ in page = 0 }
        .confirmationDialog("Share this card?", isPresented: $confirmShare, titleVisibility: .visible) {
            Button("Share anyway") { Task { await share() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            let names = (ride.use["share"]?.blockedBy ?? []).map(Format.sourceName)
            Text("This ride uses data from \(names.isEmpty ? "a source" : names.joined(separator: " and ")), whose terms on showing data to other people haven't been reviewed yet. Fine to keep for yourself; check before posting.")
        }
        .sheet(isPresented: Binding(get: { shareImage != nil }, set: { if !$0 { shareImage = nil } })) {
            if let shareImage { ShareSheet(items: [shareImage]).presentationDetents([.medium, .large]) }
        }
    }

    private var title: String {
        if isNew, let since {
            let days = Calendar.current.dateComponents([.day], from: since, to: .now).day ?? 0
            let when = days < 7 ? since.formatted(.dateTime.weekday(.wide)) : since.formatted(.dateTime.day().month(.abbreviated))
            return "Since \(when)"
        }
        return isNew ? "Just in" : "Latest · \(ride.date.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated)))"
    }

    private func card(_ r: RideSummary) -> some View {
        NavigationLink { RideDetailView(ride: r) } label: {
            // Keyed to the ride: when a new ride takes the spot, its card is drawn (not the old one's loader kept).
            RideCard(renderer: cards.renderer(r.rideId), rideId: r.rideId, entrance: isNew)
                .id(r.rideId)
                .allowsHitTesting(false)   // the web page would take the tap
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Card for the ride on \(r.date.formatted(date: .abbreviated, time: .shortened)). Opens the ride.")
    }

    private var dots: some View {
        HStack(spacing: 6) {
            ForEach(0..<rides.count, id: \.self) { i in
                Circle().fill(i == page ? Theme.cobalt : Theme.line).frame(width: 7, height: 7)
            }
        }
        .frame(maxWidth: .infinity)
        .accessibilityHidden(true)
    }

    private func share() async {
        shareImage = await cards.renderer(ride.rideId).image()
    }
}

/// This month in one line: distance (or time, when it's all been indoors), efforts and climbing. The numbers
/// count up the first time you see it, and count on when a new ride adds to them.
struct MonthStrip: View {
    let month: MonthTotal
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// The numbers as shown: zero until first seen, then counted to the month's. Animated only in their own
    /// transactions, so the strip moving down the page (a new card above it) doesn't drag them along.
    @State private var shown: [Double] = [0, 0, 0]
    @State private var seen = false

    private var values: [Double] {
        [month.km < 0.5 ? month.hours : month.km, month.climbed, Double(month.rides)]
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            MonoLabel(month.title, color: Theme.cobaltSoft)
            Spacer(minLength: 4)
            if month.km < 0.5 {
                stat(0, "indoors") { Format.duration(hours: $0) }
            } else {
                stat(0, "km")
                stat(1, "m")
            }
            stat(2, month.rides == 1 ? "effort" : "efforts")
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 16).padding(.vertical, 12)
        .background(Theme.cobalt, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .accessibilityElement(children: .combine)
        .onFirstSeen { seen = true; count(after: 0.1, duration: 1.2) }
        .onChange(of: values) { _, _ in if seen { count(after: 0.5, duration: 1.4) } }   // a new ride counts on
    }

    private func count(after delay: Double, duration: Double) {
        let target = values
        for i in target.indices {
            if reduceMotion {
                shown[i] = target[i]
            } else {
                withAnimation(.easeOut(duration: duration).delay(delay + Double(i) * 0.12)) { shown[i] = target[i] }
            }
        }
    }

    private func stat(_ i: Int, _ unit: String, format: ((Double) -> String)? = nil) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 3) {
            CountingText(value: shown[i], format: format ?? { Format.number($0, decimals: 0) })
                .font(Theme.text(17, .semibold))
            Text(unit).font(Theme.text(12)).foregroundStyle(Theme.cobaltSoft)
        }
    }
}

/// Every effort, newest first: this year's months, then one row per earlier year. The latest is open;
/// tap any other to open it. Cards (the binder) or a list with dates and numbers.
struct EffortCollection: View {
    @EnvironmentObject var model: AppModel
    let efforts: [RideSummary]
    /// Every recording, false starts too: always a list.
    let showingHidden: Bool
    let folded: (RideSummary) -> (falseStarts: Int, parts: Int)
    let delete: (RideSummary) -> Void
    @AppStorage("efforts.asList") private var asList = false
    /// Groups opened or closed by hand (flipped from their default: only the latest is open).
    @State private var flipped: Set<String> = []

    struct Group: Identifiable {
        let id: String
        let title: String
        let rides: [RideSummary]
        let gaps: [String]
        var km: Double { rides.reduce(0) { $0 + ($1.noDistance ? 0 : $1.summary.km) } }
        var hours: Double { rides.reduce(0) { $0 + $1.summary.movingH } }
    }

    private var cardsById: [String: CollectionSummary.BinderCard] {
        Dictionary((model.collection?.binder ?? []).flatMap(\.cards).map { ($0.rideId, $0) }, uniquingKeysWith: { a, _ in a })
    }

    private var list: Bool { asList || showingHidden || model.collection == nil }

    private var groups: [Group] {
        let cal = Calendar.current
        let thisYear = cal.component(.year, from: .now)
        let gaps = (model.collection?.binder ?? []).flatMap(\.gaps)
        func key(_ d: Date) -> String {
            let c = cal.dateComponents([.year, .month], from: d)
            return c.year == thisYear ? String(format: "%04d-%02d", c.year ?? 0, c.month ?? 0) : String(c.year ?? 0)
        }
        var order: [String] = []
        var byKey: [String: [RideSummary]] = [:]
        for r in efforts {
            let k = key(r.date)
            if byKey[k] == nil { order.append(k) }
            byKey[k, default: []].append(r)
        }
        var gapsByKey: [String: [String]] = [:]
        for g in gaps { if let d = YouView.day(g) { gapsByKey[key(d), default: []].append(g) } }
        return order.map { k in
            let first = byKey[k]![0].date
            let title = k.count == 4 ? k : first.formatted(.dateTime.month(.wide))
            return Group(id: k, title: title, rides: byKey[k]!, gaps: gapsByKey[k] ?? [])
        }
    }

    var body: some View {
        let groups = groups
        let cards = cardsById
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .lastTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    SectionTitle("Your collection").padding(.horizontal, -4)
                    MonoLabel(subtitle(cards))
                }
                Spacer()
                if !showingHidden && model.collection != nil {
                    Picker("Show as", selection: $asList) {
                        Image(systemName: "square.grid.3x3.fill").tag(false).accessibilityLabel("Cards")
                        Image(systemName: "list.bullet").tag(true).accessibilityLabel("List")
                    }
                    .pickerStyle(.segmented).frame(width: 100)
                }
            }
            .padding(.horizontal, 4)

            ForEach(Array(groups.enumerated()), id: \.element.id) { i, g in
                let open = (i == 0) != flipped.contains(g.id)
                Button {
                    withAnimation(.snappy) { if flipped.contains(g.id) { flipped.remove(g.id) } else { flipped.insert(g.id) } }
                } label: {
                    header(g, open: open, cards: cards)
                }
                .buttonStyle(.plain)
                if open {
                    if list { rows(g) } else { grid(g, cards: cards) }
                }
            }
        }
    }

    private func subtitle(_ cards: [String: CollectionSummary.BinderCard]) -> String {
        let holo = efforts.filter { cards[$0.rideId]?.holo == true }.count
        return "\(efforts.count) card\(efforts.count == 1 ? "" : "s")" + (holo > 0 ? " · \(holo) holo" : "")
    }

    private func header(_ g: Group, open: Bool, cards: [String: CollectionSummary.BinderCard]) -> some View {
        let holo = g.rides.filter { cards[$0.rideId]?.holo == true }.count
        return HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(g.title).font(Theme.text(17, .semibold)).foregroundStyle(Theme.ink)
            if holo > 0 { Text("★ \(holo)").font(Theme.mono(11)).foregroundStyle(Theme.cobalt) }
            Spacer()
            Text("\(g.rides.count) effort\(g.rides.count == 1 ? "" : "s") · " + (g.km < 0.5 ? "\(Format.duration(hours: g.hours)) h" : "\(Format.number(g.km, decimals: 0)) km"))
                .font(Theme.mono(12)).foregroundStyle(Theme.inkMuted)
            Image(systemName: "chevron.right").font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.label)
                .rotationEffect(.degrees(open ? 90 : 0))
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .surfaceCard(radius: 14)
        .contentShape(Rectangle())
        .accessibilityHint(open ? "Folds it away" : "Opens its cards")
    }

    private func rows(_ g: Group) -> some View {
        LazyVStack(spacing: 8) {
            ForEach(g.rides) { ride in
                NavigationLink { RideDetailView(ride: ride) } label: {
                    RideRow(ride: ride, folded: showingHidden ? (0, 0) : folded(ride))
                }
                .buttonStyle(.plain)
                .contextMenu { Button("Delete ride", systemImage: "trash", role: .destructive) { delete(ride) } }
            }
        }
    }

    private struct Slot: Identifiable {
        let id: String
        let at: Double
        let ride: RideSummary?
        let card: CollectionSummary.BinderCard?
    }

    private func grid(_ g: Group, cards: [String: CollectionSummary.BinderCard]) -> some View {
        let rides = g.rides.map { r in Slot(id: r.rideId, at: r.summary.start, ride: r, card: cards[r.rideId]) }
        let gaps = g.gaps.map { w in
            Slot(id: "gap-\(w)", at: (YouView.day(w)?.timeIntervalSince1970 ?? 0) + 3.5 * 86400, ride: nil, card: nil)
        }
        let slots = (rides + gaps).sorted { $0.at > $1.at }
        return LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
            ForEach(slots) { slot in
                if let ride = slot.ride {
                    NavigationLink { RideDetailView(ride: ride) } label: {
                        MiniCard(card: slot.card ?? Self.placeholder(ride), hours: ride.summary.movingH)
                    }
                    .buttonStyle(.plain)
                    .contextMenu { Button("Delete ride", systemImage: "trash", role: .destructive) { delete(ride) } }
                } else {
                    GapSlot(week: String(slot.id.dropFirst(4)))
                }
            }
        }
    }

    /// A ride that arrived after the collection was last worked out: a plain card until it is.
    static func placeholder(_ r: RideSummary) -> CollectionSummary.BinderCard {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withFullDate]
        f.timeZone = .current
        return .init(rideId: r.rideId, start: r.summary.start, date: f.string(from: r.date), number: 0, name: nil,
              km: r.noDistance ? 0 : r.summary.km, ascentM: r.summary.ascentM, holo: false, headline: nil,
              shape: [], week: "")
    }
}

import SwiftUI
import WebKit

/// The fun bucket: your rider card at the front, the badges you've earned (and how close the rest
/// are), and the season binder: every ride's card in order, shiny holo cards for personal bests,
/// empty slots for the weeks you didn't ride. From GET /v1/collection.
struct BinderView: View {
    @EnvironmentObject var model: AppModel
    @State private var collection: CollectionSummary?
    @State private var error: String?
    @State private var year: Int?
    @State private var builder: BuilderMode?
    @AppStorage("avatar.askedOnce") private var askedOnce = false
    @StateObject private var riderCard = CardRenderer()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    VStack(alignment: .leading, spacing: 4) {
                        if let c = collection {
                            MonoLabel("\(c.rider.badgesEarned) of \(c.rider.badgesTotal) badges · \(c.binder.first?.cards.count ?? 0) cards this season")
                        }
                        Text("Binder").font(Theme.heading(44)).foregroundStyle(Theme.ink)
                    }
                    .padding(.horizontal, 4).padding(.top, 8)

                    if let error { Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart) }

                    if let c = collection, c.rider.avatar == nil {
                        MakeAvatarPrompt { builder = .quick }
                    }
                    CardFrame(renderer: riderCard)
                    HStack {
                        Button(collection?.rider.avatar == nil ? "Make your avatar" : "Edit avatar") {
                            builder = collection?.rider.avatar == nil ? .quick : .full
                        }
                        .buttonStyle(SecondaryButton())
                        Spacer()
                        if let c = collection {
                            Text("\(c.rider.type) · \(c.rider.overall) overall")
                                .font(Theme.mono(12)).foregroundStyle(Theme.inkMuted)
                        }
                    }

                    if let c = collection {
                        BadgeGrid(badges: c.badges, rides: model.rides)
                        if !c.binder.isEmpty {
                            BinderPages(pages: c.binder, year: $year, rides: model.rides)
                        }
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 24)
            }
            .background(Theme.ground.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
            .refreshable { await load(force: true) }
            .task { await load(force: false) }
            .sheet(item: $builder, onDismiss: { Task { await load(force: true) } }) { mode in
                AvatarBuilder(quick: mode == .quick)
            }
        }
    }

    enum BuilderMode: String, Identifiable {
        case quick, full
        var id: String { rawValue }
    }

    private func load(force: Bool) async {
        do {
            collection = try await APIClient().collection()
            error = nil
            // First visit without an avatar: ask the few quick questions, once.
            if collection?.rider.avatar == nil && !askedOnce {
                askedOnce = true
                builder = .quick
            }
        } catch {
            self.error = error.localizedDescription
        }
        await riderCard.load(force: force) { try await APIClient().riderCardHTML() }
    }
}

// MARK: - Badges

private struct BadgeGrid: View {
    let badges: [CollectionSummary.Badge]
    let rides: [RideSummary]
    @State private var showAll = false

    var body: some View {
        let earned = badges.filter(\.earned).sorted { ($0.date ?? "") > ($1.date ?? "") }
        let next = badges.filter { !$0.earned }.sorted { $0.progress.value / $0.progress.target > $1.progress.value / $1.progress.target }
        VStack(alignment: .leading, spacing: 8) {
            MonoLabel("Badges").padding(.horizontal, 4).padding(.top, 6)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 104), spacing: 8)], spacing: 8) {
                ForEach(showAll ? earned + next : earned + next.prefix(3)) { badge in
                    if let rid = badge.rideId, let ride = rides.first(where: { $0.rideId == rid }) {
                        NavigationLink { RideDetailView(ride: ride) } label: { BadgeTile(badge: badge) }.buttonStyle(.plain)
                    } else {
                        BadgeTile(badge: badge)
                    }
                }
            }
            if next.count > 3 {
                Button(showAll ? "Show fewer" : "Show all \(badges.count) badges") { showAll.toggle() }
                    .font(Theme.text(14, .medium)).tint(Theme.cobalt).padding(.horizontal, 4)
            }
        }
    }
}

private struct BadgeTile: View {
    let badge: CollectionSummary.Badge

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ZStack {
                Circle().fill(badge.earned ? Theme.cobalt : Theme.surfaceSelected)
                Image(systemName: icon).font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(badge.earned ? Theme.sand : Theme.label)
            }
            .frame(width: 36, height: 36)
            Text(badge.title).font(Theme.text(14, .semibold)).foregroundStyle(badge.earned ? Theme.ink : Theme.inkMuted)
                .lineLimit(2).fixedSize(horizontal: false, vertical: true)
            if badge.earned, let date = badge.date {
                Text(Self.day(date)).font(Theme.mono(11)).foregroundStyle(Theme.label)
            } else {
                ProgressView(value: min(badge.progress.value, badge.progress.target), total: badge.progress.target)
                    .tint(Theme.cobalt)
                Text(badge.description).font(Theme.text(11)).foregroundStyle(Theme.inkMuted)
                    .lineLimit(2).fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .padding(10)
        .surfaceCard(radius: 14)
        .opacity(badge.earned ? 1 : 0.85)
        .accessibilityElement(children: .combine)
    }

    private var icon: String {
        switch badge.group {
        case "Distance": "road.lanes"
        case "Climbing": "mountain.2.fill"
        case "Tally": "sum"
        case "Consistency": "calendar"
        case "Speed": "hare.fill"
        case "Routes": "arrow.triangle.turn.up.right.circle.fill"
        default: "sunrise.fill"
        }
    }

    static func day(_ iso: String) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: iso)?.formatted(.dateTime.day().month(.abbreviated).year()) ?? iso
    }
}

// MARK: - Binder

private struct BinderPages: View {
    let pages: [CollectionSummary.BinderPage]
    @Binding var year: Int?
    let rides: [RideSummary]

    var body: some View {
        let page = pages.first { $0.year == year } ?? pages[0]
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                MonoLabel("Season binder")
                Spacer()
                if pages.count > 1 {
                    Picker("Year", selection: Binding(get: { page.year }, set: { year = $0 })) {
                        ForEach(pages) { Text(String($0.year)).tag($0.year) }
                    }
                    .pickerStyle(.segmented).frame(maxWidth: 180)
                }
            }
            .padding(.horizontal, 4).padding(.top, 6)
            Text("\(page.cards.count) rides · \(page.holo) holo · \(page.gaps.count) week\(page.gaps.count == 1 ? "" : "s") missed")
                .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).padding(.horizontal, 4)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
                ForEach(slots(page)) { slot in
                    switch slot.kind {
                    case .card(let card):
                        if let ride = rides.first(where: { $0.rideId == card.rideId }) {
                            NavigationLink { RideDetailView(ride: ride) } label: { MiniCard(card: card) }.buttonStyle(.plain)
                        } else {
                            MiniCard(card: card)
                        }
                    case .gap(let week):
                        GapSlot(week: week)
                    }
                }
            }
        }
    }

    struct Slot: Identifiable {
        enum Kind { case card(CollectionSummary.BinderCard), gap(String) }
        let id: String
        let kind: Kind
    }

    /// Cards and empty weeks together, in week order.
    private func slots(_ page: CollectionSummary.BinderPage) -> [Slot] {
        let cards = page.cards.map { Slot(id: $0.rideId, kind: .card($0)) }
        let gaps = page.gaps.map { Slot(id: "gap-\($0)", kind: .gap($0)) }
        func key(_ s: Slot) -> String {
            switch s.kind {
            case .card(let c): return c.week + "-" + String(format: "%012.0f", c.start)
            case .gap(let w): return w
            }
        }
        return (cards + gaps).sorted { key($0) < key($1) }
    }
}

/// A ride's card in miniature: number, the route's outline, distance. Holo cards shimmer.
private struct MiniCard: View {
    let card: CollectionSummary.BinderCard
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var phase: CGFloat = 0

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("No. \(card.number)").font(Theme.mono(9)).tracking(0.8)
                Spacer()
                if card.holo { Text("★ PB").font(Theme.mono(9)) }
            }
            .foregroundStyle(card.holo ? Theme.ink : .white)
            .padding(.horizontal, 7).frame(height: 18)
            .background { header }
            RouteShape(points: card.shape)
                .stroke(.white, style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round))
                .padding(10)
                .overlay {
                    if card.shape.isEmpty {
                        Image(systemName: "figure.indoor.cycle").font(.system(size: 22)).foregroundStyle(Theme.cobaltSoft)
                    }
                }
                .frame(maxWidth: .infinity).aspectRatio(1, contentMode: .fit)
                .background(Theme.cobalt)
            VStack(alignment: .leading, spacing: 1) {
                Text(card.name ?? BadgeTile.day(card.date)).font(Theme.text(10, .semibold)).lineLimit(1)
                Text(card.km < 0.05 ? "indoor" : "\(Format.number(card.km, decimals: 1)) km").font(Theme.mono(9)).foregroundStyle(Theme.inkSoft)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 7).padding(.vertical, 5)
            .background(Theme.sand)
        }
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay {
            if card.holo {
                RoundedRectangle(cornerRadius: 8, style: .continuous).strokeBorder(holoGradient, lineWidth: 2)
            }
        }
        .onAppear {
            guard card.holo, !reduceMotion else { return }
            withAnimation(.linear(duration: 6).repeatForever(autoreverses: false)) { phase = 1 }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Ride \(card.number), \(Format.number(card.km, decimals: 1)) km\(card.holo ? ", personal best" : "")")
    }

    @ViewBuilder private var header: some View {
        if card.holo { holoGradient } else { Theme.strip }
    }

    private var holoGradient: LinearGradient {
        let colors = [Color(hex: 0xF7D6E6), Color(hex: 0xC9ECFF), Color(hex: 0xFFF2B8), Color(hex: 0xD9CCFF),
                      Color(hex: 0xBFF5DD), Color(hex: 0xF7D6E6)]
        return LinearGradient(colors: colors, startPoint: UnitPoint(x: -1 + 2 * phase, y: 0),
                              endPoint: UnitPoint(x: 1 + 2 * phase, y: 1))
    }
}

/// The route's outline from the binder's shape (unit square, x east, y south).
private struct RouteShape: Shape {
    let points: [[Double]]

    func path(in rect: CGRect) -> Path {
        var p = Path()
        let pts = points.filter { $0.count == 2 }.map { CGPoint(x: rect.minX + $0[0] * rect.width, y: rect.minY + $0[1] * rect.height) }
        guard let first = pts.first else { return p }
        p.move(to: first)
        p.addLines(Array(pts.dropFirst()))
        return p
    }
}

/// A week with no ride: an empty slot in the binder, the same shape as a card.
private struct GapSlot: View {
    let week: String

    var body: some View {
        VStack(spacing: 0) {
            Color.clear.frame(height: 18)
            Color.clear.frame(maxWidth: .infinity).aspectRatio(1, contentMode: .fit)
            VStack(spacing: 1) {
                Text("x").font(Theme.text(10, .semibold))
                Text("x").font(Theme.mono(9))
            }
            .hidden().padding(.vertical, 5)
        }
        .overlay {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Theme.line, style: StrokeStyle(lineWidth: 1.5, dash: [4, 4]))
        }
        .overlay {
            VStack(spacing: 2) {
                Text("Week of").font(Theme.mono(9)).foregroundStyle(Theme.label)
                Text(BadgeTile.day(week)).font(Theme.mono(9)).foregroundStyle(Theme.label)
                    .multilineTextAlignment(.center)
            }
            .padding(4)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("No ride in the week of \(BadgeTile.day(week))")
    }
}

// MARK: - Avatar builder

/// Pick your avatar's parts; the preview is drawn by the server, exactly as it appears on your cards.
/// "Make your avatar": shown above the rider card until the rider has one.
private struct MakeAvatarPrompt: View {
    let action: () -> Void

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: "person.crop.circle.badge.plus").font(.system(size: 30)).foregroundStyle(Theme.cobalt)
            VStack(alignment: .leading, spacing: 2) {
                Text("Make your avatar").font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                Text("Four quick questions. It goes on your rider card and behind your ride cards.")
                    .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").foregroundStyle(Theme.label)
        }
        .padding(14).surfaceCard(radius: 16)
        .contentShape(Rectangle())
        .onTapGesture(perform: action)
        .accessibilityAddTraits(.isButton)
    }
}

/// Pick your avatar's parts; the preview is drawn by the server, exactly as it appears on your cards.
/// quick: the first time, a few questions one at a time (skin, hair, beard, helmet or cap, name);
/// "More options" opens every part.
struct AvatarBuilder: View {
    var quick = false
    @Environment(\.dismiss) private var dismiss
    @State private var step = 0
    @State private var showAll = false
    @State private var options: AvatarOptions?
    @State private var spec: [String: String] = [:]
    @State private var name = ""
    @State private var svg = ""
    @State private var error: String?
    @State private var saving = false

    private let order: [(key: String, label: String)] = [
        ("skin", "Skin"), ("face", "Face"), ("hair", "Hair"), ("hair_color", "Hair colour"), ("beard", "Beard"),
        ("moustache", "Moustache"), ("glasses", "Glasses"), ("headwear", "On your head"), ("helmet_color", "Helmet or cap colour"),
        ("jersey", "Jersey"), ("accent", "Jersey stripe"), ("pattern", "Jersey pattern"), ("bike", "Bike"),
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    SVGView(svg: svg)
                        .frame(width: 200, height: 240)
                        .frame(maxWidth: .infinity)
                        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                    if quick && !showAll {
                        quickStep
                    } else {
                        TextField("Your name on the rider card", text: $name)
                            .textFieldStyle(.roundedBorder).font(Theme.text(16))
                            .submitLabel(.done)
                        if let options {
                            ForEach(order, id: \.key) { item in row(item.key, item.label, options: options) }
                        }
                    }
                    if let error { Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart) }
                }
                .padding(16)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Theme.ground.ignoresSafeArea())
            .navigationTitle(quick && !showAll ? "Make your avatar" : "Your avatar")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }.disabled(saving || options == nil)
                }
            }
            .task { await start() }
            .task(id: spec) { await preview() }
        }
    }

    /// The first-time questions, one screen each.
    private var steps: [(title: String, keys: [(String, String)])] {
        [("What's your skin tone?", [("skin", "Skin")]),
         ("And your hair?", [("hair", "Style"), ("hair_color", "Colour")]),
         ("Beard or moustache?", [("beard", "Beard"), ("moustache", "Moustache")]),
         ("Helmet or cap?", [("headwear", "On your head"), ("helmet_color", "Colour")]),
         ("What should your rider card say?", [])]
    }

    @ViewBuilder private var quickStep: some View {
        let current = steps[min(step, steps.count - 1)]
        VStack(alignment: .leading, spacing: 14) {
            MonoLabel("\(step + 1) of \(steps.count)")
            Text(current.title).font(Theme.heading(30)).foregroundStyle(Theme.ink)
            if current.keys.isEmpty {
                TextField("Your name", text: $name)
                    .textFieldStyle(.roundedBorder).font(Theme.text(17)).submitLabel(.done)
            } else if let options {
                ForEach(current.keys, id: \.0) { key, label in row(key, label, options: options) }
            }
            HStack {
                if step > 0 { Button("Back") { step -= 1 }.buttonStyle(SecondaryButton()) }
                Spacer()
                if step < steps.count - 1 {
                    Button("Next") { step += 1 }.buttonStyle(PrimaryButton())
                } else {
                    Button("Done") { Task { await save() } }.buttonStyle(PrimaryButton()).disabled(saving)
                }
            }
            Button("More options: face, glasses, jersey") { showAll = true }
                .font(Theme.text(14, .medium)).tint(Theme.cobalt)
        }
    }

    @ViewBuilder
    private func row(_ key: String, _ label: String, options: AvatarOptions) -> some View {
        if let choices = options.options[key] {
            VStack(alignment: .leading, spacing: 6) {
                MonoLabel(label)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(choices, id: \.self) { choice in chip(key, choice, options: options) }
                    }
                    .padding(.vertical, 2)
                }
            }
        }
    }

    @ViewBuilder
    private func chip(_ key: String, _ choice: String, options: AvatarOptions) -> some View {
        let selected = spec[key] == choice
        let hex: String? = key == "skin" ? options.colors.skin[choice]
            : key == "hair_color" ? options.colors.hairColor[choice]
            : ["helmet_color", "jersey", "accent"].contains(key) ? options.colors.kit[choice] : nil
        Button { spec[key] = choice } label: {
            if let hex, let value = UInt32(hex.dropFirst(), radix: 16) {
                Circle().fill(Color(hex: value)).frame(width: 30, height: 30)
                    .overlay(Circle().stroke(selected ? Theme.cobalt : Theme.line, lineWidth: selected ? 3 : 1))
                    .accessibilityLabel(choice)
            } else {
                Text(choice.replacingOccurrences(of: "_", with: " ").capitalized)
                    .font(Theme.text(14, selected ? .semibold : .regular))
                    .padding(.horizontal, 12).padding(.vertical, 6)
                    .background(selected ? Theme.cobalt : Theme.surface, in: Capsule())
                    .foregroundStyle(selected ? .white : Theme.ink)
                    .overlay(Capsule().stroke(Theme.line, lineWidth: selected ? 0 : 1))
            }
        }
        .buttonStyle(.plain)
    }

    private func start() async {
        do {
            async let o = APIClient().avatarOptions()
            async let m = APIClient().me()
            let (opts, me) = try await (o, m)
            options = opts
            spec = me.avatar ?? opts.defaults
            name = me.name == "Rider" ? "" : me.name
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func preview() async {
        guard !spec.isEmpty else { return }
        try? await Task.sleep(for: .milliseconds(120))  // a quick run of taps draws once
        if Task.isCancelled { return }
        if let drawn = try? await APIClient().avatarPreview(spec) { svg = drawn }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            _ = try await APIClient().updateMe(name: name, avatar: spec)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// An SVG string, drawn by WebKit.
private struct SVGView: UIViewRepresentable {
    let svg: String

    func makeUIView(context: Context) -> WKWebView {
        let view = WKWebView()
        view.isOpaque = false
        view.backgroundColor = .clear
        view.scrollView.isScrollEnabled = false
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        guard context.coordinator.shown != svg else { return }
        context.coordinator.shown = svg
        // Fit the drawing to the view, whatever size the SVG says it is.
        let fitted = svg.replacingOccurrences(of: #"width="\d+" height="\d+""#, with: #"width="100%" height="100%""#,
                                              options: .regularExpression)
        if context.coordinator.loaded {
            // Swap the drawing in place: reloading the page each tap made the preview flash.
            let js = (try? String(data: JSONEncoder().encode(fitted), encoding: .utf8)) ?? "\"\""
            view.evaluateJavaScript("document.getElementById('a').innerHTML = \(js)")
        } else {
            context.coordinator.loaded = true
            view.loadHTMLString("<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
                                + "<body style='margin:0;height:100vh;background:transparent'>"
                                + "<div id='a' style='height:100%'>\(fitted)</div></body></html>", baseURL: nil)
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }
    final class Coordinator { var shown = ""; var loaded = false }
}

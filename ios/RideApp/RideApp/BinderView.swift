import SwiftUI
import WebKit

/// The top of You: your rider card (top trumps: five ratings out of 99 from your last 12 months, the
/// overall and your rider type), with Share, your avatar and your bike. Numbers from GET /v1/collection,
/// the card drawn by the server (GET /v1/rider-card).
struct RiderCardSection: View {
    @EnvironmentObject var model: AppModel
    @State private var builder: BuilderMode?
    @State private var showBike = false
    @State private var editAfterBike = false
    @State private var shareImage: UIImage?
    @StateObject private var riderCard = CardRenderer()

    private var hasAvatar: Bool { model.collection?.rider.avatar != nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if model.collection != nil, !hasAvatar {
                MakeAvatarPrompt { builder = .quick }
            }
            CardFrame(renderer: riderCard)
            HStack(spacing: 8) {
                Button { Task { shareImage = await riderCard.image() } } label: {
                    Label("Share", systemImage: "square.and.arrow.up")
                }
                .disabled(!riderCard.isLoaded)
                Button(hasAvatar ? "Edit avatar" : "Make avatar") { builder = hasAvatar ? .full : .quick }
                Button { showBike = true } label: { Label("Your bike", systemImage: "bicycle") }
            }
            .buttonStyle(SecondaryButton())
            .lineLimit(1)
            .frame(maxWidth: .infinity)
        }
        // Redraw when new rides change the ratings.
        .task(id: model.collection?.rider.rides) { await load(force: riderCard.isLoaded) }
        .sheet(item: $builder, onDismiss: { Task { await model.refresh(); await load(force: true) } }) { mode in
            AvatarBuilder(quick: mode == .quick).environmentObject(model)
        }
        .sheet(isPresented: $showBike, onDismiss: {
            if editAfterBike { editAfterBike = false; builder = .full }
        }) {
            VStack(spacing: 14) {
                YourBike(spec: model.bike) { editAfterBike = true; showBike = false }
                Button("Change your bike") { editAfterBike = true; showBike = false }.buttonStyle(PrimaryButton())
            }
                .padding(16)
                .presentationDetents([.medium])
                .presentationBackground(Theme.ground)
        }
        .sheet(isPresented: Binding(get: { shareImage != nil }, set: { if !$0 { shareImage = nil } })) {
            if let shareImage { ShareSheet(items: [shareImage]).presentationDetents([.medium, .large]) }
        }
    }

    enum BuilderMode: String, Identifiable {
        case quick, full
        var id: String { rawValue }
    }

    private func load(force: Bool) async {
        await riderCard.load(force: force) { try await APIClient().riderCardHTML() }
    }
}

// MARK: - Badges

struct BadgeGrid: View {
    let badges: [CollectionSummary.Badge]
    let rides: [RideSummary]
    @State private var showAll = false

    var body: some View {
        let earned = badges.filter(\.earned).sorted { ($0.date ?? "") > ($1.date ?? "") }
        let next = badges.filter { !$0.earned }.sorted { $0.progress.value / $0.progress.target > $1.progress.value / $1.progress.target }
        VStack(alignment: .leading, spacing: 8) {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 104), spacing: 8)], spacing: 8) {
                // The latest three earned and the three closest; the rest behind "Show all".
                ForEach(showAll ? earned + next : Array(earned.prefix(3)) + Array(next.prefix(3))) { badge in
                    if let rid = badge.rideId, let ride = rides.first(where: { $0.rideId == rid }) {
                        NavigationLink { RideDetailView(ride: ride) } label: { BadgeTile(badge: badge) }.buttonStyle(.plain)
                    } else {
                        BadgeTile(badge: badge)
                    }
                }
            }
            if earned.count > 3 || next.count > 3 {
                Button(showAll ? "Show fewer" : "Show all \(badges.count) badges") { showAll.toggle() }
                    .font(Theme.text(14, .medium)).tint(Theme.cobalt).padding(.horizontal, 4)
            }
        }
    }
}

struct BadgeTile: View {
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

// MARK: - Cards in miniature (Efforts: your collection)

/// A ride's card in miniature: number, the route's outline, distance. Holo cards shimmer.
struct MiniCard: View {
    static let indoorSymbol = "figure.indoor.cycle"
    let card: CollectionSummary.BinderCard
    var hours: Double? = nil     // moving time, the indoor card's number
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var phase: CGFloat = 0

    private var indoor: Bool { card.indoor == true || card.km < 0.05 }

    // The big card in small (19 Nov 2026): name strip, the route on blue (outdoors), the number in
    // dot-matrix on graphite (indoors with the indoor icon), the colour ribbon, then name and date on sand.
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(card.number > 0 ? "No. \(card.number)" : "NEW").font(Theme.mono(9)).tracking(0.8)
                Spacer()
                if card.holo { Text("★ PB").font(Theme.mono(9)) }
            }
            .foregroundStyle(card.holo ? Theme.ink : .white)
            .padding(.horizontal, 7).frame(height: 18)
            .background { header }
            Group {
                if indoor {
                    IndoorPicture(card: card)
                } else {
                    RouteShape(points: card.shape)
                        .stroke(.white, style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round))
                        .padding(9)
                        .background(Theme.cobalt)
                }
            }
            .frame(maxWidth: .infinity).aspectRatio(1.3, contentMode: .fit)
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(number).font(Theme.hero(19)).lineLimit(1).minimumScaleFactor(0.6)
                Text(unit).font(Theme.mono(9))
                Spacer(minLength: 0)
                if indoor {
                    Image(systemName: Self.indoorSymbol).font(.system(size: 13)).foregroundStyle(Theme.cobaltSoft)
                        .alignmentGuide(.firstTextBaseline) { $0[.bottom] - 2 }
                }
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 7).padding(.vertical, 5)
            .background(Theme.panel)
            Ribbon(height: 1.2)
            VStack(alignment: .leading, spacing: 1) {
                Text(card.name ?? fallbackName).font(Theme.text(10, .semibold)).lineLimit(1)
                Text(BadgeTile.day(card.date)).font(Theme.mono(9)).foregroundStyle(Theme.inkSoft).lineLimit(1)
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
        .accessibilityLabel("Ride \(card.number), \(indoor ? "indoors, \(number)" : "\(Format.number(card.km, decimals: 1)) km")\(card.holo ? ", personal best" : "")")
    }

    private var number: String {
        if indoor { return hours.map { Format.duration(hours: $0) } ?? "–" }
        return Format.hero(card.km, decimals: card.km < 100 ? 1 : 0)
    }

    private var unit: String { indoor ? "h" : "km" }

    /// As the big card names a ride with no route name: "Saturday ride", "Wednesday indoor ride".
    private var fallbackName: String {
        let day = Date(timeIntervalSince1970: card.start).formatted(.dateTime.weekday(.wide))
        return card.start > 0 ? "\(day) \(indoor ? "indoor " : "")ride" : "Ride"
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

/// An indoor card's picture, on wine where the outdoor ones are on blue: the ride game's virtual route
/// (Zwift sends made-up GPS) with its world's name, else the session's shape over time (power, else heart
/// rate), else just the indoor icon. The small icon sits in the black strip, by the time.
private struct IndoorPicture: View {
    let card: CollectionSummary.BinderCard

    var body: some View {
        ZStack {
            Theme.heart
            if !card.shape.isEmpty {
                RouteShape(points: card.shape)
                    .stroke(.white, style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round))
                    .padding(.horizontal, 12).padding(.top, 20).padding(.bottom, 9)  // clear of the world's name
            } else if let trace = card.trace, trace.count > 1 {
                ZStack {
                    TraceShape(values: trace, closed: true)
                        .fill(LinearGradient(colors: [.white.opacity(0.38), .white.opacity(0.04)],
                                             startPoint: .top, endPoint: .bottom))
                    TraceShape(values: trace)
                        .stroke(.white, style: StrokeStyle(lineWidth: 1.4, lineCap: .round, lineJoin: .round))
                }
                .padding(.top, 20).padding(.bottom, 4)
            } else {
                Image(systemName: MiniCard.indoorSymbol).font(.system(size: 24)).foregroundStyle(.white.opacity(0.85))
            }
        }
        .overlay(alignment: .topLeading) {
            if let label {
                Text(label).font(Theme.mono(7)).tracking(0.8).foregroundStyle(.white.opacity(0.8))
                    .lineLimit(1).padding(.horizontal, 6).padding(.top, 7)
            }
        }
    }

    private var label: String? {
        if let world = card.world { return world.uppercased() }
        guard card.shape.isEmpty, (card.trace?.count ?? 0) > 1 else { return nil }
        return card.traceKind == "power" ? "POWER" : "♥ RATE"
    }
}

/// A series scaled 0..1 drawn left to right (high values at the top); closed fills down to the bottom.
struct TraceShape: Shape {
    let values: [Double]
    var closed = false

    func path(in rect: CGRect) -> Path {
        var p = Path()
        guard values.count > 1 else { return p }
        let step = rect.width / CGFloat(values.count - 1)
        let pts = values.enumerated().map { CGPoint(x: rect.minX + CGFloat($0.offset) * step,
                                                    y: rect.maxY - CGFloat($0.element) * rect.height) }
        p.move(to: pts[0])
        // Smooth through the points (midpoint curves), so 48 steps read as a line, not a staircase.
        for i in 1..<pts.count {
            let mid = CGPoint(x: (pts[i - 1].x + pts[i].x) / 2, y: (pts[i - 1].y + pts[i].y) / 2)
            p.addQuadCurve(to: mid, control: pts[i - 1])
        }
        p.addLine(to: pts[pts.count - 1])
        if closed {
            p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
            p.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
            p.closeSubpath()
        }
        return p
    }
}

/// A week with no ride: an empty slot in the collection, the same shape as a card.
struct GapSlot: View {
    let week: String

    var body: some View {
        // An invisible card underneath gives the slot exactly a card's shape.
        MiniCard(card: .init(rideId: "", start: 0, date: week, number: 1, name: "x", km: 1, ascentM: nil, holo: false,
                             headline: nil, shape: [], week: week))
            .hidden()
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

/// The colour ribbon from the ride card (design/tokens.json "stripes").
struct Ribbon: View {
    var height: CGFloat = 4
    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(Theme.stripes.enumerated()), id: \.offset) { _, c in c.frame(height: height) }
        }
        .accessibilityHidden(true)
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
                Text("Five quick questions, your bike included. It goes on your rider card and behind your ride cards.")
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
    @EnvironmentObject var model: AppModel
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
        ("jersey", "Jersey"), ("accent", "Jersey stripe"), ("pattern", "Jersey pattern"),
    ]
    private let bikeOrder: [(key: String, label: String)] = [
        ("bike", "Bike"), ("bike_color", "Frame"), ("bike_accent", "Bar tape and details"), ("tyres", "Tyres"),
    ]
    private var bike: BikeSpec { BikeSpec(avatar: spec) }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if quick && !showAll && steps[min(step, steps.count - 1)].keys.contains(where: { $0.0 == "bike" }) {
                        bikePreview
                    } else {
                        SVGView(svg: svg)
                            .frame(width: 200, height: 240)
                            .frame(maxWidth: .infinity)
                            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                    }
                    if quick && !showAll {
                        quickStep
                    } else {
                        TextField("Your name on the rider card", text: $name)
                            .textFieldStyle(.roundedBorder).font(Theme.text(16))
                            .submitLabel(.done)
                        if let options {
                            ForEach(order, id: \.key) { item in row(item.key, item.label, options: options) }
                            Text("Your bike").font(Theme.heading(28)).foregroundStyle(Theme.ink).padding(.top, 8)
                            bikePreview
                            ForEach(bikeOrder, id: \.key) { item in row(item.key, item.label, options: options) }
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
         ("What do you ride?", [("bike", "Bike"), ("bike_color", "Frame")]),
         ("What should your rider card say?", [])]
    }

    /// The bike, drawn on the phone as you pick (no server round trip).
    private var bikePreview: some View {
        BikeArt(spec: bike)
            .frame(height: 210)
            .padding(.horizontal, 14).padding(.vertical, 18)
            .frame(maxWidth: .infinity)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            .animation(.easeInOut(duration: 0.2), value: bike)
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
            Button("More options: face, glasses, jersey, bike") { showAll = true }
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
            : ["helmet_color", "jersey", "accent", "bike_accent"].contains(key) ? options.colors.kit[choice]
            : key == "bike_color" ? (options.colors.frame?[choice] ?? BikePalette.frame[choice].map { String(format: "#%06X", $0) })
            : key == "tyres" ? (options.colors.tyres?[choice] ?? BikePalette.tyres[choice].map { String(format: "#%06X", $0) })
            : nil
        Button { spec[key] = choice } label: {
            if let hex, let value = UInt32(hex.dropFirst(), radix: 16) {
                Circle().fill(Color(hex: value)).frame(width: 30, height: 30)
                    .overlay(Circle().stroke(selected ? Theme.cobalt : Theme.line, lineWidth: selected ? 3 : 1))
                    .accessibilityLabel(choice)
            } else {
                Text(["mtb": "Mountain", "indoor": "Indoor trainer"][choice] ?? choice.replacingOccurrences(of: "_", with: " ").capitalized)
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
            spec = opts.defaults.merging(me.avatar ?? [:]) { _, mine in mine }
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
            let me = try await APIClient().updateMe(name: name, avatar: spec)
            model.bike = BikeSpec(avatar: me.avatar)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Your bike (from You, under the rider card). Tap to change it.
struct YourBike: View {
    let spec: BikeSpec
    let edit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                MonoLabel("Your bike")
                Spacer()
                Text(spec.label).font(Theme.mono(12)).foregroundStyle(Theme.inkMuted)
            }
            BikeArt(spec: spec).frame(height: 190).frame(maxWidth: .infinity)
        }
        .padding(16).surfaceCard(radius: 22)
        .contentShape(Rectangle())
        .onTapGesture(perform: edit)
        .accessibilityAddTraits(.isButton)
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

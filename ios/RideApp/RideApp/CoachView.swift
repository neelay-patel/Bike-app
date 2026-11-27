import SwiftUI

// The coach you can ask anything (docs/train-tab.md step 6; backend/coach_chat.py; mock-up 24 Nov 2026). Advice
// first: the one thing it's working on with you leads, with how it's going (the engine checks after every ride),
// then what it watches, then the conversation. Charts under an answer are the engine's numbers, drawn here.

private let summit = Theme.stripes[3]

/// On Train: the coach's door, with the one thing it's working on with you.
struct CoachCard: View {
    @State private var home: CoachHome?

    var body: some View {
        VStack(spacing: 0) {
            if let h = home, h.on {
                NavigationLink { CoachView() } label: {
                    HStack(alignment: .center, spacing: 12) {
                        CoachMark(size: 36)
                        VStack(alignment: .leading, spacing: 3) {
                            MonoLabel(h.oneThing == nil ? "Your coach" : "The one thing")
                            Text(h.oneThing?.title ?? "Ask me anything about your riding")
                                .font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
                                .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                            if let s = h.oneThing?.statusLabel {
                                Text(s).font(Theme.mono(11)).foregroundStyle(Theme.cobalt)
                            }
                        }
                        Spacer(minLength: 0)
                        Image(systemName: "chevron.right").font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.label)
                    }
                    .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
                }
                .buttonStyle(.plain)
            } else {
                Color.clear.frame(height: 0)      // something on screen, so the task below runs
            }
        }
        .task { home = try? await APIClient().coachHome() }
    }
}

struct CoachView: View {
    /// Opened from a ride: questions are about that ride.
    var rideId: String? = nil
    var rideLabel: String? = nil
    /// A question to ask straight away (typed in the Coach tab's ask bar, or one of its ideas).
    var initial: String? = nil

    @State private var home: CoachHome?
    @State private var messages: [CoachChatMessage] = []
    @State private var draft = ""
    @State private var asking = false
    @State private var error: String?
    @State private var showKnows = false
    @State private var showUsage = false
    @FocusState private var typing: Bool
    private let api = APIClient()

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let h = home, !h.on {
                        Text(h.why ?? "The coach is off.").font(Theme.text(15)).foregroundStyle(Theme.inkMuted)
                            .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 16)
                    } else if let h = home {
                        if rideId == nil {
                            if let a = h.oneThing { OneThingCard(advice: a, onChange: reload) }
                            ForEach(h.workingOn ?? []) { AdviceRow(advice: $0, onChange: reload) }
                            if let w = h.watching, !w.isEmpty { WatchingCard(items: w) }
                        }
                        ForEach(messages) { m in
                            CoachMessageView(message: m).id(m.id)
                        }
                        if !asking, !limited, messages.isEmpty { ideas(h) }
                        if let error { Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart) }
                        Text("Training guidance from your own data, not medical advice.")
                            .font(Theme.mono(11)).foregroundStyle(Theme.label).padding(.horizontal, 4)
                        Color.clear.frame(height: 1).id("end")
                    } else {
                        ProgressView().frame(maxWidth: .infinity).padding(40)
                    }
                }
                .padding(.horizontal, 16).padding(.vertical, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: messages) { _, _ in withAnimation { proxy.scrollTo("end", anchor: .bottom) } }
        }
        .background(Theme.ground.ignoresSafeArea())
        .safeAreaInset(edge: .bottom) { if home?.on == true { inputBar } }
        .navigationTitle(rideId == nil ? "Coach" : "About this ride")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button { showKnows = true } label: { Label("What your coach knows", systemImage: "person.text.rectangle") }
                    Button { showUsage = true } label: { Label("Coaching usage", systemImage: "gauge.with.dots.needle.33percent") }
                    Button { Task { await newConversation() } } label: { Label("New conversation", systemImage: "square.and.pencil") }
                } label: { Image(systemName: "ellipsis.circle") }
                .accessibilityLabel("Coach options")
            }
        }
        .navigationDestination(isPresented: $showKnows) { CoachKnowsView() }
        .navigationDestination(isPresented: $showUsage) { CoachUsageView() }
        .task {
            await load()
            if let q = initial, !q.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !askedInitial {
                askedInitial = true
                await send(q)
            }
        }
    }

    @State private var askedInitial = false

    // MARK: Asking

    private var limited: Bool { home?.usage?.limited == true }

    private var inputBar: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let line = home?.usage?.line {
                Button { showUsage = true } label: {
                    HStack(spacing: 6) {
                        Image(systemName: limited ? "pause.circle" : "gauge.with.dots.needle.67percent").font(.system(size: 12))
                        Text(line).font(Theme.text(12)).multilineTextAlignment(.leading)
                    }
                    .foregroundStyle(limited ? Theme.heart : Theme.inkMuted)
                }
                .buttonStyle(.plain)
            }
            if !limited { field }
        }
        .padding(.horizontal, 16).padding(.vertical, 8)
        .background(Theme.ground.opacity(0.97))
    }

    private var field: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField(rideId == nil ? "Ask your coach" : "Ask about this ride", text: $draft, axis: .vertical)
                .font(Theme.text(16)).lineLimit(1...5).focused($typing)
                .padding(.horizontal, 14).padding(.vertical, 10)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Theme.line, lineWidth: 1))
            Button { Task { await send(draft) } } label: {
                Image(systemName: asking ? "ellipsis" : "arrow.up")
                    .font(.system(size: 16, weight: .bold)).foregroundStyle(.white)
                    .frame(width: 40, height: 40)
                    .background(canSend ? Theme.cobalt : Theme.label.opacity(0.5), in: Circle())
            }
            .disabled(!canSend)
            .accessibilityLabel("Send")
        }
    }

    private var canSend: Bool { !asking && !limited && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    private func ideas(_ h: CoachHome) -> some View {
        let list = rideId == nil ? (h.ideas ?? []) :
            ["Why did this ride feel the way it did?", "What should I do differently next time?", "What did this ride do for my goal?"]
        return VStack(alignment: .leading, spacing: 8) {
            if messages.isEmpty { MonoLabel(rideId == nil ? "Ask me" : (rideLabel ?? "About this ride")) }
            ForEach(list, id: \.self) { q in
                Button { Task { await send(q) } } label: {
                    HStack {
                        Text(q).font(Theme.text(14)).foregroundStyle(Theme.cobalt).multilineTextAlignment(.leading)
                        Spacer(minLength: 0)
                        Image(systemName: "arrow.up.right").font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.cobalt)
                    }
                    .padding(.horizontal, 14).padding(.vertical, 11)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Theme.line, lineWidth: 1))
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func load() async {
        do {
            let h = try await api.coachHome()
            home = h
            // From a ride, only what's asked there shows (the whole conversation is on the Coach screen).
            if rideId == nil { messages = h.messages ?? [] }
        } catch { self.error = error.localizedDescription }
    }

    private func reload() { Task { await load() } }

    private func merge(_ new: [CoachChatMessage]) {
        var byId = Dictionary(uniqueKeysWithValues: messages.map { ($0.id, $0) })
        for m in new { byId[m.id] = m }
        messages = byId.values.sorted { $0.id < $1.id }
    }

    private func send(_ text: String) async {
        let q = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !asking else { return }
        asking = true
        error = nil
        draft = ""
        typing = false
        defer { asking = false }
        do {
            let r = try await api.coachAsk(q, rideId: rideId)
            merge(r.messages)
            for _ in 0..<120 {           // up to three minutes
                try await Task.sleep(for: .seconds(1.5))
                let new = try await api.coachMessages(after: r.question - 1)
                merge(rideId == nil ? new : new.filter { $0.id >= r.question })
                if let a = new.first(where: { $0.id == r.answer }), a.status != "working" { break }
            }
            if let h = try? await api.coachHome() { home = h }
        } catch {
            self.error = error.localizedDescription
            draft = q
            if (error as? APIError)?.status == 429, let h = try? await api.coachHome() { home = h }
        }
    }

    private func newConversation() async {
        do {
            try await api.coachNewConversation()
            messages = []
            await load()
        } catch { self.error = error.localizedDescription }
    }
}

// MARK: - The one thing, and the rest of the advice

private struct OneThingCard: View {
    let advice: CoachAdvice
    let onChange: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                MonoLabel("The one thing", color: Theme.cobaltSoft)
                Spacer()
                if let s = advice.statusLabel { StatusPill(text: s, status: advice.status, dark: true) }
            }
            Text(advice.title).font(Theme.heading(30)).foregroundStyle(.white).fixedSize(horizontal: false, vertical: true)
            Text(advice.do).font(Theme.text(15)).foregroundStyle(.white.opacity(0.92)).fixedSize(horizontal: false, vertical: true)
            if let c = advice.check {
                Text(.init(c)).font(Theme.text(14)).foregroundStyle(Theme.cobaltSoft).fixedSize(horizontal: false, vertical: true)
            } else {
                Text("I'll check after your next ride.").font(Theme.text(13)).foregroundStyle(Theme.cobaltSoft)
            }
        }
        .padding(18).frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.cobalt, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .contextMenu { AdviceMenu(id: advice.id, onChange: onChange) }
    }
}

private struct AdviceRow: View {
    let advice: CoachAdvice
    let onChange: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                MonoLabel("Also working on")
                Spacer()
                if let s = advice.statusLabel { StatusPill(text: s, status: advice.status) }
            }
            Text(advice.title).font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
            if let c = advice.check {
                Text(c).font(Theme.text(13)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 16)
        .contextMenu { AdviceMenu(id: advice.id, onChange: onChange) }
    }
}

private struct AdviceMenu: View {
    let id: Int
    let onChange: () -> Void

    var body: some View {
        Button { set("done") } label: { Label("Done with this", systemImage: "checkmark") }
        Button(role: .destructive) { set("dropped") } label: { Label("Drop it", systemImage: "xmark") }
    }

    private func set(_ s: String) {
        Task {
            try? await APIClient().coachSetAdvice(id, status: s)
            onChange()
        }
    }
}

private struct StatusPill: View {
    let text: String
    let status: String?
    var dark = false

    var body: some View {
        Text(text.uppercased())
            .font(Theme.mono(10)).tracking(10 * 0.16)
            .foregroundStyle(fg)
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(bg, in: Capsule())
    }

    private var fg: Color {
        if dark { return status == "working" ? Theme.ink : .white }
        return status == "working" ? Theme.ink : Theme.inkSoft
    }

    private var bg: Color {
        if status == "working" { return summit }
        return dark ? .white.opacity(0.16) : Theme.surfaceSelected
    }
}

private struct WatchingCard: View {
    let items: [CoachWatch]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            MonoLabel("What I'm watching")
            ForEach(items, id: \.self) { w in
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(w.label).font(Theme.text(14, .medium)).foregroundStyle(Theme.ink)
                        if let d = w.detail {
                            Text(d).font(Theme.text(12)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    Spacer(minLength: 12)
                    HStack(alignment: .firstTextBaseline, spacing: 3) {
                        Text(w.value).font(Theme.text(17, .semibold)).foregroundStyle(Theme.ink)
                        if !w.unit.isEmpty { Text(w.unit).font(Theme.mono(11)).foregroundStyle(Theme.label) }
                    }
                }
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
    }
}

// MARK: - The conversation

private struct CoachMessageView: View {
    let message: CoachChatMessage

    var body: some View {
        if message.role == "rider" {
            HStack {
                Spacer(minLength: 48)
                Text(message.text).font(Theme.text(15)).foregroundStyle(Theme.ink)
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(Theme.surfaceSelected, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .fixedSize(horizontal: false, vertical: true)
            }
        } else {
            HStack(alignment: .top, spacing: 10) {
                CoachMark(size: 28)
                VStack(alignment: .leading, spacing: 12) {
                    if message.status == "working" {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            Text((message.progress ?? "Thinking") + "…").font(Theme.text(14)).foregroundStyle(Theme.inkMuted)
                        }
                        .padding(.top, 4)
                    } else {
                        Text(markdown(message.text)).font(Theme.text(15)).foregroundStyle(message.status == "failed" ? Theme.inkMuted : Theme.ink)
                            .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                        ForEach(Array((message.charts ?? []).enumerated()), id: \.offset) { _, c in CoachChartView(chart: c) }
                        ForEach(message.actions ?? []) { CoachActionCard(action: $0) }
                        ForEach(message.advice ?? []) { a in
                            Label("I'll follow up: \(a.title)", systemImage: "arrow.triangle.2.circlepath")
                                .font(Theme.mono(11)).foregroundStyle(Theme.cobalt)
                        }
                    }
                }
                Spacer(minLength: 0)
            }
        }
    }

    private func markdown(_ s: String) -> AttributedString {
        (try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(s)
    }
}

private struct CoachActionCard: View {
    @State var action: CoachAction
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            MonoLabel("Change to your plan")
            Text(action.preview).font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
            if let w = action.why {
                Text(w).font(Theme.text(13)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
            }
            switch action.status {
            case "open":
                HStack(spacing: 10) {
                    Button { decide(true) } label: {
                        Text("OK, change it").font(Theme.text(14, .semibold)).foregroundStyle(.white)
                            .padding(.horizontal, 16).padding(.vertical, 9).background(Theme.cobalt, in: Capsule())
                    }
                    Button { decide(false) } label: {
                        Text("Not now").font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
                            .padding(.horizontal, 14).padding(.vertical, 9)
                    }
                }
                .disabled(busy).buttonStyle(.plain)
            case "accepted":
                Label("Changed", systemImage: "checkmark").font(Theme.mono(11)).foregroundStyle(Theme.cobalt)
            case "failed":
                Text("Couldn't change it: \(action.whyNot ?? "the plan has moved on").").font(Theme.text(13)).foregroundStyle(Theme.heart)
            default:
                Text("Left as it was").font(Theme.mono(11)).foregroundStyle(Theme.label)
            }
            if let error { Text(error).font(Theme.text(12)).foregroundStyle(Theme.heart) }
        }
        .padding(14).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 16)
    }

    private func decide(_ yes: Bool) {
        busy = true
        Task {
            defer { busy = false }
            do { action = try await APIClient().coachDecide(action.id, accept: yes) }
            catch { self.error = error.localizedDescription }
        }
    }
}

// MARK: - Charts (the engine's numbers, drawn here)

struct CoachChartView: View {
    let chart: CoachChart

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            MonoLabel(chart.title)
            switch chart.type {
            case "aim": aim
            case "ride": ride
            default: trend
            }
        }
        .padding(14).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 16)
    }

    private var unit: String { chart.unit ?? "" }

    private func fmt(_ v: Double) -> String {
        let s = v == v.rounded() ? String(Int(v)) : String(format: "%.1f", v)
        return unit == "%" ? s + "%" : unit.isEmpty ? s : "\(s) \(unit)"
    }

    // Bars over time; a shaded band where there's one to aim for (cadence 85–95). Distance, time, shares and counts
    // start from zero; heart rate, watts and cadence from a little under the lowest, so the change shows.
    private var trend: some View {
        let pts = chart.points ?? []
        let vals = pts.map(\.value) + (chart.band ?? [])
        let fromZero = ["%", "km", "h", "m", ""].contains(unit)
        let hi = (vals.max() ?? 1) * 1.05
        let lo = fromZero ? 0 : max(0, (vals.min() ?? 0) * 0.85)
        let h: CGFloat = 120
        func y(_ v: Double) -> CGFloat { hi > lo ? CGFloat((v - lo) / (hi - lo)) * h : 0 }
        return VStack(alignment: .leading, spacing: 6) {
            ZStack(alignment: .bottomLeading) {
                if let b = chart.band, b.count == 2 {
                    Rectangle().fill(Theme.cobaltSoft.opacity(0.45))
                        .frame(height: max(2, y(b[1]) - y(b[0])))
                        .offset(y: -y(b[0]))
                }
                HStack(alignment: .bottom, spacing: pts.count > 10 ? 3 : 6) {
                    ForEach(Array(pts.enumerated()), id: \.offset) { i, p in
                        VStack(spacing: 3) {
                            if i == pts.count - 1 || i == 0 {
                                Text(fmt(p.value)).font(Theme.mono(9)).foregroundStyle(i == pts.count - 1 ? Theme.ink : Theme.label)
                                    .lineLimit(1).fixedSize()
                            }
                            RoundedRectangle(cornerRadius: 3, style: .continuous)
                                .fill(i == pts.count - 1 ? Theme.cobalt : Theme.cobalt.opacity(0.35))
                                .frame(height: max(2, y(p.value)))
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
            }
            .frame(height: h + 16, alignment: .bottom)
            HStack {
                Text(pts.first?.label ?? "").font(Theme.mono(10)).foregroundStyle(Theme.label)
                Spacer()
                if let b = chart.band, b.count == 2 {
                    Text("aim \(Int(b[0]))–\(Int(b[1]))").font(Theme.mono(10)).foregroundStyle(Theme.cobalt)
                    Spacer()
                }
                Text(pts.last?.label ?? "").font(Theme.mono(10)).foregroundStyle(Theme.label)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(chart.title): from \(pts.first.map { fmt($0.value) } ?? "") to \(pts.last.map { fmt($0.value) } ?? "")")
    }

    // Then, now and the aim on one line.
    private var aim: some View {
        let s = chart.start ?? chart.current ?? 0, c = chart.current ?? 0, t = chart.target ?? c
        let lo = min(s, c, t), hi = max(s, c, t)
        func x(_ v: Double, _ w: CGFloat) -> CGFloat { hi > lo ? CGFloat((v - lo) / (hi - lo)) * (w - 24) + 12 : w / 2 }
        return VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(c == c.rounded() ? String(Int(c)) : String(format: "%.1f", c)).font(Theme.hero(30)).foregroundStyle(Theme.ink)
                Text(unit).font(Theme.mono(12)).foregroundStyle(Theme.label)
                if chart.target != nil { Text("aim \(fmt(t))").font(Theme.text(14)).foregroundStyle(Theme.inkMuted) }
            }
            GeometryReader { g in
                let w = g.size.width
                ZStack(alignment: .leading) {
                    Capsule().fill(Theme.line).frame(height: 4)
                    Capsule().fill(Theme.cobalt).frame(width: max(4, abs(x(c, w) - x(s, w))), height: 4)
                        .offset(x: min(x(s, w), x(c, w)))
                    Circle().fill(Theme.label).frame(width: 10, height: 10).offset(x: x(s, w) - 5)
                    Circle().stroke(summit, lineWidth: 3).background(Circle().fill(Theme.surface)).frame(width: 14, height: 14).offset(x: x(t, w) - 7)
                    Circle().fill(Theme.cobalt).frame(width: 14, height: 14).offset(x: x(c, w) - 7)
                }
                .frame(height: 16)
            }
            .frame(height: 16)
            HStack {
                if chart.start != nil { Text("from \(fmt(s))").font(Theme.mono(10)).foregroundStyle(Theme.label) }
                Spacer()
                Text("now").font(Theme.mono(10)).foregroundStyle(Theme.cobalt)
                Spacer()
                if chart.target != nil { Text("aim").font(Theme.mono(10)).foregroundStyle(Theme.label) }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(chart.title): \(fmt(c)) now" + (chart.target != nil ? ", aim \(fmt(t))" : ""))
    }

    private var ride: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text([chart.date, chart.where == "indoor" ? "indoors" : "outdoors"].compactMap { $0 }.joined(separator: " · "))
                .font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
            HStack(spacing: 14) {
                if let m = chart.minutes { stat("\(m)", "min") }
                if let k = chart.km, k > 0 { stat(k == k.rounded() ? "\(Int(k))" : String(format: "%.1f", k), "km") }
                if let hr = chart.avgHr { stat("\(Int(hr))", "bpm") }
                if let p = chart.avgPower { stat("\(Int(p))", "W") }
            }
            if let z = chart.zone2 { Zone2Numbers(split: z, big: 26) }
        }
    }

    private func stat(_ v: String, _ u: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 3) {
            Text(v).font(Theme.text(17, .semibold)).foregroundStyle(Theme.ink)
            Text(u).font(Theme.mono(11)).foregroundStyle(Theme.label)
        }
    }
}

// MARK: - What the coach knows

struct CoachKnowsView: View {
    @State private var knows: CoachKnows?
    @State private var error: String?
    private let api = APIClient()

    var body: some View {
        ScrollView {
            if let k = knows {
                VStack(alignment: .leading, spacing: 14) {
                    section("What it reads") {
                        ForEach(k.reads, id: \.self) { r in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(r.what).font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
                                Text(r.detail).font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        Text("Never: \(k.never)").font(Theme.text(13)).foregroundStyle(Theme.inkSoft)
                    }
                    section("What it remembers about you") {
                        if k.memory.isEmpty {
                            Text("Nothing yet. Tell your coach about your bike, the days you can ride or an event, and it keeps a note.")
                                .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                        }
                        ForEach(k.memory) { n in
                            HStack(alignment: .top) {
                                Text(n.note).font(Theme.text(14)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
                                Spacer(minLength: 8)
                                Button { Task { await forget(n.id) } } label: {
                                    Image(systemName: "xmark").font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.label)
                                        .frame(width: 32, height: 32)
                                }
                                .accessibilityLabel("Forget this")
                            }
                        }
                    }
                    if !k.advice.isEmpty {
                        section("Advice so far") {
                            ForEach(k.advice) { a in
                                VStack(alignment: .leading, spacing: 2) {
                                    HStack {
                                        Text(a.title).font(Theme.text(14, .semibold)).foregroundStyle(Theme.ink)
                                        Spacer()
                                        Text((a.closed == "open" ? (a.statusLabel ?? "Open") : (a.closed ?? "")).capitalized)
                                            .font(Theme.mono(10)).foregroundStyle(Theme.label)
                                    }
                                    if let c = a.check { Text(c).font(Theme.text(12)).foregroundStyle(Theme.inkMuted) }
                                }
                            }
                        }
                    }
                    Text(k.disclaimer).font(Theme.mono(11)).foregroundStyle(Theme.label).padding(.horizontal, 4)
                }
                .padding(16)
            } else if let error {
                Text(error).font(Theme.text(14)).foregroundStyle(Theme.heart).padding(16)
            } else {
                ProgressView().padding(40)
            }
        }
        .background(Theme.ground.ignoresSafeArea())
        .navigationTitle("What your coach knows")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func section<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            MonoLabel(title)
            content()
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
    }

    private func load() async {
        do { knows = try await api.coachKnows() } catch { self.error = error.localizedDescription }
    }

    private func forget(_ id: Int) async {
        try? await api.coachForget(id)
        await load()
    }
}

// MARK: - Coaching usage (like Claude's own usage meter: a share used and when it resets, never money)

struct CoachUsageView: View {
    @State private var usage: CoachUsage?
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let u = usage {
                    VStack(alignment: .leading, spacing: 18) {
                        meter("Today", u.day)
                        Divider().overlay(Theme.line)
                        meter("This week", u.week)
                    }
                    .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 22)
                    if let l = u.line {
                        Text(l).font(Theme.text(14)).foregroundStyle(u.limited ? Theme.heart : Theme.ink).padding(.horizontal, 4)
                    }
                    Text("Each question to your coach uses some of your coaching. Longer questions, and ones that look at a lot of your riding, use more. Ride stories, the morning brief and the Sunday review don't count.")
                        .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, 4)
                } else if let error {
                    Text(error).font(Theme.text(14)).foregroundStyle(Theme.heart)
                } else {
                    ProgressView().frame(maxWidth: .infinity).padding(40)
                }
            }
            .padding(16)
        }
        .background(Theme.ground.ignoresSafeArea())
        .navigationTitle("Coaching usage")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            do { usage = try await APIClient().coachUsage() } catch { self.error = error.localizedDescription }
        }
    }

    private func meter(_ title: String, _ m: CoachUsage.Meter) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(title).font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
                Spacer()
                Text("\(m.usedPct)% used").font(Theme.text(14)).foregroundStyle(m.usedPct >= 100 ? Theme.heart : Theme.inkSoft)
            }
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(Theme.surfaceSelected)
                    Capsule().fill(m.usedPct >= 100 ? Theme.heart : Theme.cobalt)
                        .frame(width: max(m.usedPct > 0 ? 6 : 0, g.size.width * CGFloat(min(m.usedPct, 100)) / 100))
                }
            }
            .frame(height: 8)
            Text("Resets \(resets(m))").font(Theme.mono(11)).foregroundStyle(Theme.label)
        }
        .accessibilityElement(children: .combine)
    }

    /// "at midnight", or "Monday at 12:00 AM", read in the phone's own time format.
    private func resets(_ m: CoachUsage.Meter) -> String {
        if m.resets == "Monday", let d = try? Date(m.resetsAt, strategy: .iso8601) {
            return d.formatted(.dateTime.weekday(.wide)) + " at " + d.formatted(date: .omitted, time: .shortened)
        }
        return m.resets
    }
}

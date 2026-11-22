import MapKit
import SwiftUI
import UniformTypeIdentifiers

/// GPX files opened in the app (Share → Ride) are uploaded here; the Routes list reloads when one lands.
@MainActor
final class RouteInbox: ObservableObject {
    static let shared = RouteInbox()
    @Published var added = 0
    @Published var error: String?
    @Published var busy = false

    func add(_ url: URL) async {
        busy = true
        defer { busy = false }
        do {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            _ = try await APIClient().addCourse(gpx: try Data(contentsOf: url), name: nil)
            added += 1
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Routes: bring in a route you found (Ride with GPS, Komoot...), see what it's really like (surface,
/// singletrack, where to stop, busy roads, climbs, your time), then send it to the Edge.
struct RoutesView: View {
    @State private var courses: [Course] = []
    @State private var importing = false
    @State private var error: String?
    @State private var uploading = false
    @State private var deleting: Course?
    @ObservedObject private var inbox = RouteInbox.shared

    private var checking: Bool { courses.contains { $0.status == "checking" } }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    // No big title (20 Nov 2026): describing a ride leads.
                    PlanBox { made in
                        Task { await load() }
                        _ = made
                    }

                    Button { importing = true } label: {
                        HStack(spacing: 10) {
                            Image(systemName: uploading || inbox.busy ? "hourglass" : "square.and.arrow.down")
                            VStack(alignment: .leading, spacing: 2) {
                                Text(uploading || inbox.busy ? "Reading the route…" : "Route Enhancer").font(Theme.text(16, .semibold))
                                Text("Bring a GPX from Ride with GPS, Komoot or anywhere. In seconds: its surfaces, busy roads, where to stop and your time. Then tune it and send it to your Edge.")
                                    .font(Theme.text(13)).foregroundStyle(.white.opacity(0.8))
                                    .multilineTextAlignment(.leading)
                            }
                            Spacer(minLength: 0)
                        }
                        .foregroundStyle(.white)
                        .padding(16)
                        .background(Theme.cobalt, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .disabled(uploading)

                    if let error {
                        Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart)
                    }
                    if courses.isEmpty && error == nil {
                        Text("No routes yet. In Ride with GPS, open a route, choose Export → GPX Track, and share it to Kova (or pick the file here).")
                            .font(Theme.text(15)).foregroundStyle(Theme.inkMuted).padding(.vertical, 16)
                    }
                    LazyVStack(spacing: 8) {
                        ForEach(courses) { c in
                            NavigationLink { CourseDetailView(courseId: c.id, onChange: { Task { await load() } }) } label: {
                                CourseRow(course: c)
                            }
                            .buttonStyle(.plain)
                            .disabled(c.status != "ready")
                            .contextMenu {
                                if c.status == "failed" {
                                    Button("Check again", systemImage: "arrow.clockwise") { Task { await recheck(c) } }
                                }
                                Button("Delete route", systemImage: "trash", role: .destructive) { deleting = c }
                            }
                        }
                    }
                }
                .padding(16)
            }
            .background(Theme.ground.ignoresSafeArea())
            .scrollDismissesKeyboard(.interactively)  // drag down to put the keyboard away
            .refreshable { await load() }
            .task { await load() }
            .task(id: inbox.added) { await load() }
            .onChange(of: inbox.error) { _, e in if let e { error = e } }
            .task(id: checking) {
                // The check runs on the server (the map lookup can take a minute): look again until it's done.
                while checking && !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(4))
                    await load()
                }
            }
            .fileImporter(isPresented: $importing, allowedContentTypes: Self.gpxTypes) { result in
                Task { await add(result) }
            }
            .confirmationDialog("Delete this route?", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
                                titleVisibility: .visible, presenting: deleting) { c in
                Button("Delete \(c.name)", role: .destructive) { Task { await delete(c) } }
            } message: { _ in Text("The route and its check are deleted from the server. Your original file isn't touched.") }
        }
    }

    static var gpxTypes: [UTType] {
        [UTType(filenameExtension: "gpx"), .xml].compactMap { $0 }
    }

    private func load() async {
        guard ServerConfig.isConfigured else { error = "Add the server address and token in Settings."; return }
        do {
            courses = try await APIClient().courses()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func add(_ result: Result<URL, Error>) async {
        uploading = true
        defer { uploading = false }
        do {
            let url = try result.get()
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            let data = try Data(contentsOf: url)
            _ = try await APIClient().addCourse(gpx: data, name: nil)
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func recheck(_ c: Course) async {
        do { try await APIClient().recheckCourse(c.id) } catch { self.error = error.localizedDescription }
        await load()
    }

    private func delete(_ c: Course) async {
        do { try await APIClient().deleteCourse(c.id) } catch { self.error = error.localizedDescription }
        await load()
    }
}

// MARK: - Surface colours

/// Route surfaces. Gravel is cobalt (what this rider goes looking for); singletrack is the warning red.
enum SurfaceColor {
    static func light(_ cls: String) -> Color {
        switch cls {
        case "paved": return Theme.inkSoft
        case "gravel": return Theme.cobalt
        case "rough": return Color(hex: 0x8C6A2F)
        case "trail": return Color(hex: 0xB0587A)
        case "singletrack": return Theme.heart
        default: return Color(hex: 0xB9B0B3)
        }
    }

    /// On the dark panel.
    static func dark(_ cls: String) -> Color {
        switch cls {
        case "paved": return Theme.panelLabel
        case "gravel": return Color(hex: 0x7F9BEA)
        case "rough": return Theme.sand
        case "trail": return Color(hex: 0xE59AB4)
        case "singletrack": return Color(hex: 0xE0607F)
        default: return Theme.label
        }
    }
}

// MARK: - List row

struct CourseRow: View {
    let course: Course

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            DrawnRoute(points: course.shape)
                .frame(width: 52, height: 52)
                .padding(6)
                .background(Theme.ground, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 5) {
                Text(course.name).font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink).lineLimit(2)
                switch course.status {
                case "checking":
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.mini)
                        Text("Checking the map along the route…").font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                    }
                case "failed":
                    Text("Couldn't check it: \(course.error ?? "map lookup failed"). Press and hold to try again.")
                        .font(Theme.text(13)).foregroundStyle(Theme.heart)
                default:
                    Text(facts).font(Theme.mono(12)).foregroundStyle(Theme.inkMuted)
                    if let plan = course.plan, !plan.why.isEmpty {
                        Text(plan.why.joined(separator: " · "))
                            .font(Theme.text(13)).foregroundStyle(Theme.cobalt)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    ForEach(course.verdict.prefix(2), id: \.self) { v in VerdictLine(verdict: v, compact: true) }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .surfaceCard(radius: 18)
    }

    private var facts: String {
        var parts: [String] = []
        if let km = course.km { parts.append("\(Format.number(km, decimals: 1)) km") }
        if let m = course.ascentM { parts.append("\(Int(m)) m") }
        if let g = course.gravelShare { parts.append("\(Int((g * 100).rounded()))% off-road") }
        if let t = course.timeS { parts.append("~" + Format.duration(hours: t / 3600)) }
        return parts.joined(separator: " · ").uppercased()
    }
}

/// A route's outline in a unit square (x east, y south, from the server), scaled to fit. Also the binder's.
struct RouteShape: Shape {
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

struct VerdictLine: View {
    let verdict: Course.Verdict
    var compact = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: icon).font(.system(size: compact ? 11 : 13, weight: .semibold)).foregroundStyle(color)
            Text(verdict.text).font(Theme.text(compact ? 13 : 15)).foregroundStyle(compact ? Theme.inkSoft : Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var icon: String {
        switch verdict.tone {
        case "good": return "checkmark.circle.fill"
        case "warn": return "exclamationmark.triangle.fill"
        default: return "circle.fill"
        }
    }

    private var color: Color {
        switch verdict.tone {
        case "good": return Theme.cobalt
        case "warn": return Theme.heart
        default: return Theme.label
        }
    }
}

// MARK: - Detail

struct CourseDetailView: View {
    let courseId: Int
    var onChange: () -> Void = {}
    @Environment(\.dismiss) private var dismiss
    @State private var course: Course?
    @State private var error: String?
    @State private var shareURL: URL?
    @State private var allCues = false
    @State private var allStops = false
    @State private var renaming = false
    @State private var newName = ""
    @State private var tuning = false
    @State private var tuneError: String?
    @State private var options: CourseOptions?
    @State private var choosing: TuneChoice?
    @State private var pickingStart = false
    @State private var picked: CLLocationCoordinate2D?

    enum TuneSheet: String { case stop, start }
    /// The sheet carries its options, so it never shows a stale (empty) copy.
    struct TuneChoice: Identifiable { let which: TuneSheet; let options: CourseOptions; var id: String { which.rawValue } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let c = course, let r = c.report {
                    header(c, r)
                    if pickingStart { pickBanner }
                    RouteMap(report: r, onPick: pickingStart ? { picked = $0 } : nil, picked: picked)
                        .id("\(c.changes?.count ?? 0)-\(c.km ?? 0)")
                        .frame(height: 300)
                        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous)
                            .stroke(pickingStart ? Theme.cobalt : .clear, lineWidth: 3))
                    RoutePanel(report: r)
                    SurfaceBar(report: r).revealOnFirstSeen(duration: 1.0)
                    section("What to know") {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(r.verdict, id: \.self) { VerdictLine(verdict: $0) }
                        }
                    }
                    tuneCard(c)
                    exportCard(c)
                    if !r.stops.filter({ !$0.view }).isEmpty { stops(r) }
                    if !r.climbs.isEmpty { climbs(r) }
                    cues(r)
                    Text("\(r.credit)\(r.osmDate.map { ", as of " + String($0.prefix(10)) } ?? ""). Surfaces are only as good as the map: "
                         + "\(Format.number(r.unknownKm, decimals: 1)) km has no surface on it and \(Format.number(r.assumedKm, decimals: 1)) km "
                         + "is judged from the kind of road. Your time is an estimate from your own rides.")
                        .font(Theme.text(12)).foregroundStyle(Theme.label).padding(.horizontal, 4)
                } else if let error {
                    Text(error).font(Theme.text(14)).foregroundStyle(Theme.heart)
                } else {
                    ProgressView().frame(maxWidth: .infinity).padding(40)
                }
            }
            .padding(16)
        }
        .background(Theme.ground.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button("Rename", systemImage: "pencil") { newName = course?.name ?? ""; renaming = true }
                    if let link = course?.link, let url = URL(string: link) {
                        Link(destination: url) { Label("Open original", systemImage: "safari") }
                    }
                    Button("Delete route", systemImage: "trash", role: .destructive) { Task { await delete() } }
                } label: { Image(systemName: "ellipsis.circle") }
            }
        }
        .alert("Rename route", isPresented: $renaming) {
            TextField("Name", text: $newName)
            Button("Save") { Task { await rename() } }
            Button("Cancel", role: .cancel) {}
        }
        .sheet(isPresented: Binding(get: { shareURL != nil }, set: { if !$0 { shareURL = nil } })) {
            if let shareURL { ShareSheet(items: [shareURL]).presentationDetents([.medium, .large]) }
        }
        .sheet(item: $choosing) { choice in
            TuneChoices(which: choice.which, options: choice.options, onStop: { s in
                choosing = nil
                Task { await tune(["op": "stop", "lat": s.lat, "lon": s.lon, "name": s.name]) }
            }, onStart: { s in
                choosing = nil
                Task { await tune(["op": "start", "lat": s.lat, "lon": s.lon, "label": s.name]) }
            }, onPickOnMap: {
                choosing = nil
                picked = nil
                pickingStart = true
            })
            .presentationDetents([.medium, .large])
        }
        .overlay {
            if tuning {
                VStack(spacing: 10) {
                    ProgressView().tint(.white)
                    Text("Finding roads…").font(Theme.text(14, .medium)).foregroundStyle(.white)
                }
                .padding(22)
                .background(Theme.panel.opacity(0.92), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            }
        }
        .task { await load() }
    }

    // MARK: Tuning

    private var pickBanner: some View {
        HStack(spacing: 10) {
            Image(systemName: "hand.tap.fill").foregroundStyle(Theme.cobalt)
            Text(picked == nil ? "Tap the map where you want to start." : "Start at the flag?")
                .font(Theme.text(14, .medium)).foregroundStyle(Theme.ink)
            Spacer()
            if let p = picked {
                Button("Start here") {
                    pickingStart = false
                    Task { await tune(["op": "start", "lat": p.latitude, "lon": p.longitude, "label": "the point you picked"]) }
                    picked = nil
                }
                .font(Theme.text(14, .semibold)).foregroundStyle(Theme.cobalt)
            }
            Button("Cancel") { pickingStart = false; picked = nil }
                .font(Theme.text(14)).foregroundStyle(Theme.inkMuted)
        }
        .padding(12)
        .surfaceCard(radius: 14)
    }

    private func tuneCard(_ c: Course) -> some View {
        section("Tune it") {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Shorter or longer, keeping the roads you like").font(Theme.text(14)).foregroundStyle(Theme.inkMuted)
                    HStack(spacing: 6) {
                        ForEach([-20, -10, -5, 5, 10, 20], id: \.self) { km in
                            Button { Task { await tune(["op": "length", "km": km]) } } label: {
                                Text(km > 0 ? "+\(km)" : "−\(-km)")
                                    .font(Theme.text(14, .semibold)).frame(maxWidth: .infinity).padding(.vertical, 9)
                                    .foregroundStyle(Theme.cobalt)
                                    .background(Theme.cobaltSoft.opacity(0.45), in: Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    Text("KM").font(Theme.mono(10)).foregroundStyle(Theme.label)
                }
                HStack(spacing: 8) {
                    tuneButton("Add a stop", icon: "cup.and.saucer") { Task { await openChoices(.stop) } }
                    tuneButton("Start elsewhere", icon: "flag") { Task { await openChoices(.start) } }
                }
                if let tuneError {
                    Text(tuneError).font(Theme.text(13)).foregroundStyle(Theme.heart)
                }
                if let changes = c.changes, !changes.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        MonoLabel("Changes")
                        ForEach(changes, id: \.self) { ch in
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text("\(ch.n)").font(Theme.mono(11)).foregroundStyle(Theme.label)
                                Text(ch.change).font(Theme.text(14)).foregroundStyle(Theme.ink)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        Button { Task { await undo() } } label: {
                            Label("Undo the last change", systemImage: "arrow.uturn.backward")
                                .font(Theme.text(14, .medium)).foregroundStyle(Theme.cobalt)
                        }
                        .buttonStyle(.plain)
                        .padding(.top, 2)
                    }
                }
            }
        }
        .disabled(tuning)
    }

    private func tuneButton(_ title: String, icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: icon).font(Theme.text(14, .semibold))
                .frame(maxWidth: .infinity).padding(.vertical, 11)
                .foregroundStyle(Theme.cobalt).overlay(Capsule().stroke(Theme.cobalt, lineWidth: 1.5))
        }
        .buttonStyle(.plain)
    }

    private func openChoices(_ which: TuneSheet) async {
        if options == nil {
            do { options = try await APIClient().courseOptions(courseId) } catch { tuneError = error.localizedDescription; return }
        }
        if let options { choosing = TuneChoice(which: which, options: options) }
    }

    private func tune(_ op: [String: Any]) async {
        tuning = true
        defer { tuning = false }
        do {
            course = try await APIClient().tuneCourse(courseId, op)
            tuneError = nil
            options = nil          // the stops near the route have moved with it
            onChange()
        } catch {
            tuneError = error.localizedDescription
        }
    }

    private func undo() async {
        tuning = true
        defer { tuning = false }
        do { course = try await APIClient().undoCourse(courseId); options = nil; onChange() }
        catch { tuneError = error.localizedDescription }
    }

    private func header(_ c: Course, _ r: CourseReport) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            MonoLabel([sourceLabel(c.source), r.loop ? "Loop" : "Point to point"].compactMap { $0 }.joined(separator: " · "))
            Text(c.name).font(Theme.heading(36)).foregroundStyle(Theme.ink).lineLimit(3)
        }
        .padding(.horizontal, 4)
    }

    private func sourceLabel(_ s: String?) -> String? {
        switch s {
        case "ridewithgps": return "From Ride with GPS"
        case "komoot": return "From Komoot"
        case "garmin": return "From Garmin"
        case "ride": return "From your ride"
        default: return "From a GPX"
        }
    }

    private func section<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            MonoLabel(title)
            content()
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .surfaceCard()
    }

    private func exportCard(_ c: Course) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            MonoLabel("Ride it")
            HStack(spacing: 8) {
                Button { Task { await export(c, kind: "fit") } } label: {
                    Label("Send to Edge", systemImage: "paperplane.fill").font(Theme.text(15, .semibold))
                        .frame(maxWidth: .infinity).padding(.vertical, 12)
                        .foregroundStyle(.white).background(Theme.cobalt, in: Capsule())
                }
                Button { Task { await export(c, kind: "gpx") } } label: {
                    Text("GPX").font(Theme.text(15, .semibold)).padding(.vertical, 12).padding(.horizontal, 18)
                        .foregroundStyle(Theme.cobalt).overlay(Capsule().stroke(Theme.cobalt, lineWidth: 1.5))
                }
            }
            .buttonStyle(.plain)
            Text("A FIT course with your stops and climbs, which the Edge shows in Up Ahead and ClimbPro. Share it to Garmin "
                 + "Connect, or save it to Files and import it at connect.garmin.com under Training → Courses.")
                .font(Theme.text(12)).foregroundStyle(Theme.label)
        }
        .padding(16)
        .surfaceCard()
    }

    /// Where to stop: a few sensible places (by riding time, local cafés first, the last food before a long
    /// gap), not every café in town; everything near the route is a tap away.
    private func stops(_ r: CourseReport) -> some View {
        let all = r.stops.filter { !$0.view }
        return section(r.rest == nil ? "Stops along the way" : "Where to stop") {
            VStack(alignment: .leading, spacing: 0) {
                if let rest = r.rest {
                    if rest.isEmpty {
                        Text(r.timeS < 5400 ? "A short ride: no stop needed." : "No good place to stop on the map near this route.")
                            .font(Theme.text(14)).foregroundStyle(Theme.inkMuted).padding(.vertical, 6)
                    }
                    ForEach(rest) { p in
                        HStack(alignment: .top, spacing: 12) {
                            Text("KM \(Format.number(p.km, decimals: 0))").font(Theme.mono(11))
                                .foregroundStyle(p.rest ? Theme.cobalt : Theme.label)
                                .frame(width: 54, alignment: .leading)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(p.name).font(Theme.text(15, p.rest ? .semibold : .medium)).foregroundStyle(Theme.ink)
                                Text([p.place, p.why.prefix(1).uppercased() + p.why.dropFirst()].compactMap { $0 }.joined(separator: " · "))
                                    .font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
                                    .fixedSize(horizontal: false, vertical: true)
                                if !p.also.isEmpty {
                                    Text("Also here: " + p.also.joined(separator: ", ")).font(Theme.text(12)).foregroundStyle(Theme.label)
                                }
                                if !p.hours.isEmpty { Text(p.hours).font(Theme.mono(11)).foregroundStyle(Theme.label) }
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 9)
                        Divider().overlay(Theme.line)
                    }
                    if !all.isEmpty {
                        Button {
                            withAnimation(.easeInOut(duration: 0.2)) { allStops.toggle() }
                        } label: {
                            HStack {
                                Text(allStops ? "Hide the full list" : "All \(all.count) places near the route")
                                    .font(Theme.text(14, .medium))
                                Spacer()
                                Image(systemName: allStops ? "chevron.up" : "chevron.down").font(.system(size: 12, weight: .semibold))
                            }
                            .foregroundStyle(Theme.cobalt).padding(.vertical, 10).contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                if r.rest == nil || allStops {
                    ForEach(all) { s in
                        HStack(alignment: .top, spacing: 12) {
                            Text("KM \(Format.number(s.km, decimals: 1))").font(Theme.mono(11)).foregroundStyle(Theme.label)
                                .frame(width: 64, alignment: .leading)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(s.items.first?.name ?? "Stop").font(Theme.text(15, .medium)).foregroundStyle(Theme.ink)
                                Text(stopLine(s)).font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
                                if let h = s.items.first?.hours, !h.isEmpty {
                                    Text(h).font(Theme.mono(11)).foregroundStyle(Theme.label)
                                }
                            }
                            Spacer(minLength: 0)
                            if r.rest == nil, r.midway?.km == s.km { MonoLabel("Halfway", color: Theme.cobalt) }
                        }
                        .padding(.vertical, 9)
                        if s.id != all.last?.id { Divider().overlay(Theme.line) }
                    }
                }
            }
        }
    }

    private func stopLine(_ s: CourseReport.Stop) -> String {
        var parts: [String] = []
        if let p = s.place { parts.append(p) }
        let kinds = [(s.food, "food"), (s.shop, "shop"), (s.water, "water"), (s.toilets, "toilets")].filter(\.0).map(\.1)
        parts.append(kinds.joined(separator: ", "))
        if let off = s.items.first?.offM, off >= 60 { parts.append("\(Int(off)) m off the route") }
        if s.items.count > 1 { parts.append("+\(s.items.count - 1) more") }
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private func climbs(_ r: CourseReport) -> some View {
        section("Climbs") {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(r.climbs, id: \.self) { c in
                    HStack {
                        Text("KM \(Format.number(c.km, decimals: 1))").font(Theme.mono(11)).foregroundStyle(Theme.label)
                            .frame(width: 64, alignment: .leading)
                        Text("\(Int(c.gainM)) m over \(Format.number(c.lengthM / 1000, decimals: 1)) km")
                            .font(Theme.text(15)).foregroundStyle(Theme.ink)
                        Spacer()
                        Text("\(Format.number(c.grade, decimals: 1))%").font(Theme.text(15, .semibold)).foregroundStyle(Theme.ink)
                    }
                }
            }
        }
    }

    private func cues(_ r: CourseReport) -> some View {
        let shown = allCues ? r.cues : Array(r.cues.prefix(12))
        return section("Cue sheet") {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(shown) { c in
                    HStack(alignment: .top, spacing: 10) {
                        Text(Format.number(c.km, decimals: 1)).font(Theme.mono(12)).foregroundStyle(Theme.label)
                            .frame(width: 44, alignment: .trailing)
                        Image(systemName: cueIcon(c.turn)).font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(c.turn == "stop" ? Theme.cobalt : Theme.inkSoft).frame(width: 18)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(c.text).font(Theme.text(14, c.turn == "stop" ? .medium : .regular)).foregroundStyle(Theme.ink)
                            if let s = c.surface, let f = c.forKm {
                                HStack(spacing: 5) {
                                    Circle().fill(SurfaceColor.light(s)).frame(width: 7, height: 7)
                                    Text("\(s.capitalized), \(Format.number(f, decimals: 1)) km").font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
                                }
                            }
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.vertical, 6)
                }
                if r.cues.count > 12 {
                    Button(allCues ? "Show fewer" : "Show all \(r.cues.count) cues") { allCues.toggle() }
                        .font(Theme.text(14, .medium)).foregroundStyle(Theme.cobalt).padding(.top, 8)
                }
            }
        }
    }

    private func cueIcon(_ turn: String) -> String {
        switch turn {
        case "start": return "flag"
        case "finish": return "flag.checkered"
        case "left": return "arrow.turn.up.left"
        case "right": return "arrow.turn.up.right"
        case "u-turn": return "arrow.uturn.down"
        case "stop": return "cup.and.saucer.fill"
        default: return "arrow.up"
        }
    }

    private func load() async {
        do { course = try await APIClient().course(courseId) } catch { self.error = error.localizedDescription }
    }

    private func export(_ c: Course, kind: String) async {
        do {
            let data = try await APIClient().courseFile(c.id, kind: kind)
            let safe = c.name.replacingOccurrences(of: "/", with: "-")
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(safe).\(kind)")
            try data.write(to: url)
            shareURL = url
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func rename() async {
        let name = newName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        do { try await APIClient().renameCourse(courseId, to: name); await load(); onChange() }
        catch { self.error = error.localizedDescription }
    }

    private func delete() async {
        do { try await APIClient().deleteCourse(courseId); onChange(); dismiss() }
        catch { self.error = error.localizedDescription }
    }
}

// MARK: - Tuning choices

struct TuneChoices: View {
    let which: CourseDetailView.TuneSheet
    let options: CourseOptions?
    var onStop: (CourseOptions.Stop) -> Void
    var onStart: (CourseOptions.Start) -> Void
    var onPickOnMap: () -> Void

    var body: some View {
        NavigationStack {
            List {
                if which == .stop {
                    let stops = options?.stops ?? []
                    let fill = stops.filter { $0.fillsGap == true }
                    if stops.isEmpty {
                        Text("No cafés, shops or water on the map within 3 km of the route.").font(Theme.text(14))
                    }
                    if let g = options?.gap, !fill.isEmpty {
                        Section("Fills the gap, km \(Int(g.fromKm))–\(Int(g.toKm))") {
                            ForEach(fill) { stopRow($0) }
                        }
                    }
                    Section(fill.isEmpty ? "" : "Elsewhere") {
                        ForEach(stops.filter { $0.fillsGap != true }) { stopRow($0) }
                    }
                } else {
                    Button(action: onPickOnMap) {
                        Label("Pick a point on the map", systemImage: "hand.tap").font(Theme.text(16, .medium))
                            .foregroundStyle(Theme.cobalt)
                    }
                    let starts = options?.starts ?? []
                    if !starts.isEmpty {
                        Section("On the route") {
                            ForEach(starts) { s in
                                Button { onStart(s) } label: {
                                    HStack {
                                        Image(systemName: s.kind == "cafe" ? "cup.and.saucer" : "house")
                                            .foregroundStyle(Theme.inkMuted).frame(width: 22)
                                        Text(s.name).font(Theme.text(15)).foregroundStyle(Theme.ink)
                                        Spacer()
                                        Text("km \(Format.number(s.km, decimals: 1))").font(Theme.mono(11)).foregroundStyle(Theme.label)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle(which == .stop ? "Add a stop" : "Start elsewhere")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private func stopRow(_ s: CourseOptions.Stop) -> some View {
        Button { onStop(s) } label: {
            VStack(alignment: .leading, spacing: 3) {
                Text(s.name).font(Theme.text(16, .medium)).foregroundStyle(Theme.ink)
                Text("Near km \(Format.number(s.km, decimals: 1)) · \(Format.number(s.offM / 1000, decimals: 1)) km off the route · "
                     + s.what.replacingOccurrences(of: "_", with: " "))
                    .font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
                if !s.hours.isEmpty { Text(s.hours).font(Theme.mono(11)).foregroundStyle(Theme.label) }
            }
        }
    }
}

// MARK: - Map

struct RouteMap: View {
    let report: CourseReport
    /// When set, a tap on the map picks a point (choosing a new start).
    var onPick: ((CLLocationCoordinate2D) -> Void)? = nil
    var picked: CLLocationCoordinate2D? = nil

    var body: some View {
        MapReader { proxy in
            map
                .onTapGesture { pt in
                    if let onPick, let c = proxy.convert(pt, from: .local) { onPick(c) }
                }
        }
    }

    private var map: some View {
        Map(initialPosition: .rect(rect)) {
            if let picked {
                Annotation("New start", coordinate: picked) {
                    Image(systemName: "flag.fill").font(.system(size: 12, weight: .bold)).foregroundStyle(.white)
                        .frame(width: 26, height: 26).background(Theme.cobalt, in: Circle())
                        .overlay(Circle().stroke(.white, lineWidth: 2))
                }
            }
            ForEach(Array(report.stretches.enumerated()), id: \.offset) { _, s in
                MapPolyline(coordinates: s.points.compactMap(coord))
                    .stroke(SurfaceColor.light(s.class), style: StrokeStyle(lineWidth: s.class == "paved" ? 3.5 : 4.5,
                                                                          lineCap: .round, lineJoin: .round))
            }
            if let rest = report.rest {        // where to stop, not every café in town
                ForEach(rest) { p in
                    Annotation("", coordinate: CLLocationCoordinate2D(latitude: p.lat, longitude: p.lon)) {
                        Image(systemName: p.kind == "water" ? "drop.fill" : "cup.and.saucer.fill")
                            .font(.system(size: 10, weight: .bold)).foregroundStyle(.white)
                            .frame(width: 20, height: 20)
                            .background(p.rest ? Theme.cobalt : Theme.inkSoft, in: Circle())
                            .overlay(Circle().stroke(.white, lineWidth: 1.5))
                    }
                }
            } else {
                ForEach(report.stops.filter { !$0.view && ($0.food || $0.shop || $0.water) }) { s in
                    Annotation("", coordinate: CLLocationCoordinate2D(latitude: s.lat, longitude: s.lon)) {
                        Image(systemName: s.food || s.shop ? "cup.and.saucer.fill" : "drop.fill")
                            .font(.system(size: 10, weight: .bold)).foregroundStyle(.white)
                            .frame(width: 20, height: 20)
                            .background(report.midway?.km == s.km ? Theme.cobalt : Theme.inkSoft, in: Circle())
                            .overlay(Circle().stroke(.white, lineWidth: 1.5))
                    }
                }
            }
            if let start = coord(report.start) {
                Annotation("Start", coordinate: start) {
                    Circle().fill(Theme.ink).frame(width: 14, height: 14).overlay(Circle().stroke(.white, lineWidth: 2.5))
                }
            }
        }
        .mapStyle(.standard(elevation: .flat, pointsOfInterest: .excludingAll))
        .accessibilityLabel("Map of the route, coloured by surface")
    }

    private func coord(_ p: [Double]) -> CLLocationCoordinate2D? {
        p.count >= 2 ? CLLocationCoordinate2D(latitude: p[0], longitude: p[1]) : nil
    }

    private var rect: MKMapRect {
        let b = report.bbox  // south, west, north, east
        let a = MKMapPoint(CLLocationCoordinate2D(latitude: b[2], longitude: b[1]))
        let c = MKMapPoint(CLLocationCoordinate2D(latitude: b[0], longitude: b[3]))
        let r = MKMapRect(x: min(a.x, c.x), y: min(a.y, c.y), width: abs(c.x - a.x), height: abs(c.y - a.y))
        return r.insetBy(dx: -r.width * 0.12, dy: -r.height * 0.12)
    }
}

// MARK: - Panel: profile coloured by surface, and the hero numbers

struct RoutePanel: View {
    let report: CourseReport

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SurfaceProfile(report: report).frame(height: 128).revealOnFirstSeen(duration: 1.3)
            Rectangle().fill(Theme.panelLine).frame(height: 1)
            LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)],
                      alignment: .leading, spacing: 12) {
                HeroStat(label: "Length", value: Format.number(report.km, decimals: 1), unit: "km")
                HeroStat(label: "Climbing", value: report.ascentM.map { Format.hero($0, decimals: 0) } ?? "–", unit: "m")
                HeroStat(label: "Off pavement", value: report.gravelShare.map { "\(Int(($0 * 100).rounded()))" } ?? "–", unit: "%")
                HeroStat(label: "Your time", value: Format.duration(hours: report.timeS / 3600), unit: nil)
            }
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 18).padding(.vertical, 16)
        .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }
}

/// Halftone elevation profile (as on rides), with a strip under it coloured by surface.
struct SurfaceProfile: View {
    let report: CourseReport

    var body: some View {
        Canvas { ctx, size in
            let strip: CGFloat = 6, axis: CGFloat = 16
            let plotH = size.height - axis - strip - 4
            let pts = report.profile
            let total = max(report.km, 0.1)
            guard pts.count > 1 else {
                ctx.draw(Text("No elevation in this file").font(Theme.mono(11)).foregroundColor(Theme.panelLabel),
                         at: CGPoint(x: size.width / 2, y: plotH / 2))
                return
            }
            let lo = pts.map(\.ele).min()!, hi = max(pts.map(\.ele).max()!, lo + 10)
            func at(_ km: Double, _ ele: Double) -> CGPoint {
                CGPoint(x: CGFloat(km / total) * size.width, y: 8 + CGFloat(1 - (ele - lo) / (hi - lo)) * (plotH - 12))
            }
            var line = Path()
            line.addLines(pts.map { at($0.km, $0.ele) })
            var area = line
            area.addLine(to: CGPoint(x: size.width, y: plotH))
            area.addLine(to: CGPoint(x: 0, y: plotH))
            area.closeSubpath()
            ctx.drawLayer { layer in
                layer.clip(to: area)
                var y: CGFloat = 2.5
                while y < plotH {
                    let alpha = 0.9 - 0.75 * Double(y / plotH)
                    var x: CGFloat = 2.5
                    while x < size.width {
                        layer.fill(Path(ellipseIn: CGRect(x: x - 1.1, y: y - 1.1, width: 2.2, height: 2.2)),
                                   with: .color(.white.opacity(alpha)))
                        x += 5
                    }
                    y += 5
                }
            }
            ctx.stroke(line, with: .color(.white), lineWidth: 1.6)
            // Surface strip.
            let sy = plotH + 3
            for s in report.stretches {
                let x0 = CGFloat(s.fromKm / total) * size.width, x1 = CGFloat(s.toKm / total) * size.width
                ctx.fill(Path(CGRect(x: x0, y: sy, width: max(1, x1 - x0), height: strip)), with: .color(SurfaceColor.dark(s.class)))
            }
            // Climb tops.
            for c in report.climbs where c.gainM >= 40 {
                let km = c.km + c.lengthM / 1000
                if let near = pts.min(by: { abs($0.km - km) < abs($1.km - km) }) {
                    let p = at(near.km, near.ele)
                    ctx.fill(Path(ellipseIn: CGRect(x: p.x - 3, y: p.y - 3, width: 6, height: 6)), with: .color(.white))
                }
            }
            ctx.draw(Text("0").font(Theme.mono(11)).foregroundColor(Theme.panelLabel),
                     at: CGPoint(x: 0, y: size.height - 6), anchor: .leading)
            ctx.draw(Text("\(Format.number(total, decimals: 1)) KM").font(Theme.mono(11)).foregroundColor(Theme.panelLabel),
                     at: CGPoint(x: size.width, y: size.height - 6), anchor: .trailing)
        }
        .accessibilityLabel("Elevation profile, with the surface along the route underneath")
    }
}

/// One bar: how much of the route is on each surface.
struct SurfaceBar: View {
    let report: CourseReport

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            MonoLabel("Surface")
            GeometryReader { geo in
                HStack(spacing: 2) {
                    ForEach(report.surfaces) { s in
                        Rectangle().fill(SurfaceColor.light(s.class))
                            .frame(width: max(2, geo.size.width * s.share - 2))
                    }
                }
            }
            .frame(height: 14)
            .clipShape(Capsule())
            LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)],
                      alignment: .leading, spacing: 8) {
                ForEach(report.surfaces) { s in
                    HStack(spacing: 6) {
                        Circle().fill(SurfaceColor.light(s.class)).frame(width: 9, height: 9)
                        Text(s.label).font(Theme.text(14, .medium)).foregroundStyle(Theme.ink)
                        Text("\(Format.number(s.km, decimals: 1)) km").font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .surfaceCard()
    }
}


// MARK: - Plan a ride from a description

/// Looks places up in Apple Maps as the rider types (addresses, cafés, towns), biased to southern Ontario.
@MainActor
final class PlaceSearch: NSObject, ObservableObject, MKLocalSearchCompleterDelegate {
    @Published var results: [MKLocalSearchCompletion] = []
    private let completer = MKLocalSearchCompleter()
    static let region = MKCoordinateRegion(center: .init(latitude: 44.0, longitude: -79.3),
                                           span: .init(latitudeDelta: 3, longitudeDelta: 4))

    override init() {
        super.init()
        completer.delegate = self
        completer.resultTypes = [.address, .pointOfInterest]
        completer.region = Self.region
    }

    func update(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespaces)
        if t.count < 3 { results = []; completer.cancel(); return }
        completer.queryFragment = t
    }

    nonisolated func completerDidUpdateResults(_ completer: MKLocalSearchCompleter) {
        let r = Array(completer.results.prefix(4))
        Task { @MainActor in self.results = r }
    }

    nonisolated func completer(_ completer: MKLocalSearchCompleter, didFailWithError error: Error) {}

    /// A suggestion, or typed words, to a place: ["name", "lat", "lon"].
    static func place(_ completion: MKLocalSearchCompletion) async -> [String: Any]? {
        await run(MKLocalSearch.Request(completion: completion), name: completion.title)
    }

    static func place(_ text: String) async -> [String: Any]? {
        let req = MKLocalSearch.Request()
        req.naturalLanguageQuery = text
        req.region = region
        return await run(req, name: nil)
    }

    private static func run(_ req: MKLocalSearch.Request, name: String?) async -> [String: Any]? {
        guard let item = try? await MKLocalSearch(request: req).start().mapItems.first else { return nil }
        let c = item.placemark.coordinate
        let label = name ?? item.name ?? item.placemark.title ?? "there"
        return ["name": label, "lat": c.latitude, "lon": c.longitude]
    }
}

/// "60–70 km gravel loop near Uxbridge, café halfway": what we understood as tags, a question for anything
/// missing, then three routes (saved as routes, checked like any other). POST /v1/courses/plan.
/// The description stays editable: change it and Find routes again; Start over clears it all.
struct PlanBox: View {
    var onMade: ([Course]) -> Void
    @State private var text = ""
    @State private var asked = ""            // the words the current result came from
    @State private var result: PlanResult?
    @State private var busy = false
    @State private var lookingUp = false     // asking Apple Maps where a place is
    @State private var error: String?
    @State private var placeText = ""
    @State private var made: [Course] = []
    @State private var work: Task<Void, Never>?
    @StateObject private var search = PlaceSearch()
    @FocusState private var focus: Field?

    enum Field { case words, place }

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Titled like the Route Enhancer below it, so it reads as a feature, not a disabled form (20 Nov 2026).
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Image(systemName: "wand.and.stars").foregroundStyle(Theme.cobalt)
                    .symbolEffect(.variableColor.iterative, isActive: busy)
                Text("Route Generator").font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                Spacer()
                if !text.isEmpty || result != nil || !made.isEmpty {
                    Button("Start over") { startOver() }
                        .font(Theme.text(13, .medium)).foregroundStyle(Theme.cobalt)
                        .buttonStyle(.plain)
                }
            }
            Text("Describe a ride: a loop, one way (from Uxbridge to Port Perry, or to an address) or there and back (40 km out and back from Goodwood).")
                .font(Theme.text(13)).foregroundStyle(Theme.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
            TextField("60–70 km gravel loop near Uxbridge, café halfway", text: $text, axis: .vertical)
                .font(Theme.text(16))
                .lineLimit(1...4)
                .submitLabel(.go)
                .focused($focus, equals: .words)
                .onChange(of: text) { _, new in
                    if new.contains("\n") {             // Return in a multi-line field: go
                        text = new.replacingOccurrences(of: "\n", with: " ")
                        go()
                    } else if result != nil, new.trimmingCharacters(in: .whitespacesAndNewlines) != asked {
                        result = nil                     // edited: what we understood no longer holds
                    }
                }
                .padding(12)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(focus == .words ? Theme.cobalt : Theme.line, lineWidth: focus == .words ? 1.5 : 1))
            if let result, !result.tags.isEmpty {
                FlowLayout(spacing: 6) {
                    ForEach(result.tags, id: \.self) { t in
                        Text(t).font(Theme.mono(11)).foregroundStyle(Theme.cobalt)
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background(Theme.cobaltSoft.opacity(0.45), in: Capsule())
                    }
                }
                ForEach(result.notes, id: \.self) { n in
                    Text(n).font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                }
            }
            if busy {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(lookingUp ? "Looking that up…" : "Finding routes on the map and checking each one…")
                        .font(Theme.text(14)).foregroundStyle(Theme.inkMuted)
                    Spacer()
                    Button("Cancel") { cancel() }
                        .font(Theme.text(14, .medium)).foregroundStyle(Theme.cobalt).buttonStyle(.plain)
                }
            } else if let q = result?.questions.first {
                question(q)
            } else {
                // Always solid: a faded button made the whole box look switched off. With nothing typed yet,
                // a tap puts you in the field instead.
                Button { trimmed.isEmpty ? (focus = .words) : go() } label: {
                    Label("Find routes", systemImage: "arrow.triangle.turn.up.right.diamond")
                        .font(Theme.text(16, .semibold)).foregroundStyle(.white)
                        .frame(maxWidth: .infinity).padding(.vertical, 12)
                        .background(Theme.cobalt, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                .buttonStyle(.plain)
            }
            if !made.isEmpty {
                Text("\(made.count) route\(made.count == 1 ? "" : "s") made: at the top of your routes, best first, each checked. Open one to tune it or send it to your Edge.")
                    .font(Theme.text(13)).foregroundStyle(Theme.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let error {
                Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart)
            }
        }
        .padding(16)
        .surfaceCard(radius: 18)
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Done") { focus = nil }
            }
        }
    }

    @ViewBuilder private func question(_ q: PlanResult.Question) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(q.text).font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
            if q.key == "start" || q.key == "end" || q.key == "via" {
                HStack(spacing: 8) {
                    TextField(q.hint ?? "A town", text: $placeText)
                        .font(Theme.text(15)).submitLabel(.go)
                        .focused($focus, equals: .place)
                        .autocorrectionDisabled()
                        .onSubmit { answerPlace(q.key, typed: placeText) }
                        .onChange(of: placeText) { _, t in search.update(t) }
                        .padding(10)
                        .background(Theme.ground, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    if result?.home == true, q.key != "via" {
                        chip(q.key == "start" ? "From home" : "Home") { answer([q.key: "home"]) }
                    }
                }
                .onAppear {
                    placeText = q.guess ?? ""
                    search.update(placeText)
                }
                .id(q.key + (q.guess ?? ""))
                ForEach(search.results, id: \.self) { c in
                    Button { answerPlace(q.key, completion: c) } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Image(systemName: "mappin").foregroundStyle(Theme.cobalt)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(c.title).font(Theme.text(15, .medium)).foregroundStyle(Theme.ink)
                                if !c.subtitle.isEmpty {
                                    Text(c.subtitle).font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
                                }
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 4)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            } else {
                if let hint = q.hint {
                    Text(hint).font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
                        .fixedSize(horizontal: false, vertical: true)
                }
                FlowLayout(spacing: 8) {
                    ForEach(Array(zip(q.choices, q.raw.indices)), id: \.0) { label, i in
                        chip(label.contains(" ") ? label : label.capitalized) { answer([q.key: q.raw[i]]) }
                    }
                }
            }
        }
    }

    private func chip(_ label: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label).font(Theme.text(14, .medium)).foregroundStyle(Theme.cobalt)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .overlay(Capsule().stroke(Theme.cobalt, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .disabled(busy)
    }

    private func go() {
        guard !trimmed.isEmpty else { return }
        focus = nil
        asked = trimmed
        run(text: trimmed, ask: nil, answers: [:])
    }

    private func answer(_ answers: [String: Any]) {
        focus = nil
        run(text: nil, ask: result?.ask, answers: answers)
    }

    /// A place the rider picked from Apple Maps' suggestions, or typed (looked up in Apple Maps first; our
    /// own list of Ontario places if Apple Maps doesn't know it).
    private func answerPlace(_ key: String, completion: MKLocalSearchCompletion? = nil, typed: String = "") {
        let words = typed.trimmingCharacters(in: .whitespaces)
        guard completion != nil || !words.isEmpty else { return }
        focus = nil
        busy = true
        lookingUp = true
        error = nil
        work = Task {
            let found: [String: Any]?
            if let completion { found = await PlaceSearch.place(completion) } else { found = await PlaceSearch.place(words) }
            if Task.isCancelled { return }
            busy = false
            lookingUp = false
            if let found {
                placeText = ""
                answer([key: found])
            } else if !words.isEmpty {
                answer([key: words])
            } else {
                error = "Apple Maps couldn't find that; try typing it."
            }
        }
    }

    private func run(text: String?, ask: [String: Any]?, answers: [String: Any]) {
        busy = true
        error = nil
        made = []
        work?.cancel()
        work = Task {
            do {
                let r = try await APIClient().planRoutes(text: text, ask: ask, answers: answers)
                if Task.isCancelled { return }
                result = r
                if !r.courses.isEmpty {
                    made = r.courses
                    onMade(r.courses)
                }
            } catch {
                if Task.isCancelled { return }
                self.error = error.localizedDescription
            }
            busy = false
        }
    }

    private func cancel() {
        work?.cancel()
        work = nil
        busy = false
        lookingUp = false
    }

    private func startOver() {
        cancel()
        text = ""
        asked = ""
        result = nil
        made = []
        error = nil
        placeText = ""
        focus = nil
    }
}

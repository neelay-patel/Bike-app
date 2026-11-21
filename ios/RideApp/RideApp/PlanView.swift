import SwiftUI
import UIKit

/// The training plan (GET /v1/plan): a month calendar of sessions, the selected day's sessions, and each
/// session's structure (intervals, how long, how hard, targets in watts and heart rate). The plan can be
/// added to the rider's own calendar (a subscribed feed that updates itself) and sessions exported to Zwift.
struct PlanView: View {
    @EnvironmentObject var model: AppModel
    @State private var month = Calendar.current.date(from: Calendar.current.dateComponents([.year, .month], from: Date()))!
    @State private var selected = Calendar.current.startOfDay(for: Date())
    @State private var settingGoal = false
    @State private var editingDays = false
    @State private var editingFTP = false
    @State private var calendarMessage: String?
    /// Opened from the Train tab ("The plan ahead"): inside its navigation, with a back button.
    var embedded = false

    var body: some View {
        if embedded {
            content.toolbar(.visible, for: .navigationBar).navigationTitle("The plan ahead")
                .navigationBarTitleDisplayMode(.inline)
        } else {
            NavigationStack { content.toolbar(.hidden, for: .navigationBar) }
        }
    }

    private var content: some View {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    header
                    if let plan = model.plan {
                        if plan.ftp.watts == nil { FTPBanner { editingFTP = true } }
                        MonthCalendar(plan: plan, month: $month, selected: $selected)
                        DaySessions(plan: plan, day: selected)
                        if let week = week(of: selected, in: plan) { WeekSummary(week: week) }
                        Text("Training guidance from your own data, not medical advice.")
                            .font(Theme.mono(11)).foregroundStyle(Theme.label)
                    } else if !model.isLoading {
                        Button { settingGoal = true } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Set a goal and your plan appears here").font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                                Text("Week by week to your goal: every session with its intervals, durations and targets, on your usual days.")
                                    .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                            }
                            .padding(16).frame(maxWidth: .infinity, alignment: .leading).surfaceCard(radius: 16)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 24)
            }
            .background(Theme.ground.ignoresSafeArea())
            .refreshable { await model.refresh() }
            .sheet(isPresented: $settingGoal) { GoalFlow() }
            .sheet(isPresented: $editingDays) { if let plan = model.plan { DaysSheet(plan: plan) } }
            .sheet(isPresented: $editingFTP) { FTPSheet(current: model.plan?.ftp) }
            .alert("Training calendar", isPresented: Binding(get: { calendarMessage != nil }, set: { if !$0 { calendarMessage = nil } })) {
                Button("OK", role: .cancel) {}
            } message: { Text(calendarMessage ?? "") }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                if let plan = model.plan, let w = plan.thisWeek, let week = plan.weeks.first(where: { $0.index == w }) {
                    MonoLabel("Week \(w) of \(plan.weeks.count) · \(PlanText.phase(week.phase))")
                } else {
                    MonoLabel("Your training")
                }
                if let g = model.goal {   // no big "Plan" title (20 Nov 2026): the week and the goal lead
                    Text(g.goal.title + (g.goal.readyBy.flatMap(GoalText.date).map { " · ready by \($0.formatted(.dateTime.day().month(.wide)))" } ?? ""))
                        .font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
                }
            }
            Spacer()
            if model.plan != nil {
                Menu {
                    Button("Add to my calendar", systemImage: "calendar.badge.plus") { Task { await subscribe() } }
                    Button("Copy calendar link", systemImage: "link") { Task { await copyLink() } }
                    Button("Days and times", systemImage: "clock") { editingDays = true }
                    Button("Your FTP", systemImage: "bolt") { editingFTP = true }
                } label: {
                    Image(systemName: "ellipsis.circle").font(.system(size: 22)).frame(width: 44, height: 44)
                }
                .accessibilityLabel("Plan options")
            }
        }
        .padding(.horizontal, 4).padding(.top, 8)
    }

    private func week(of day: Date, in plan: TrainingPlan) -> TrainingPlan.Week? {
        plan.weeks.first { w in
            guard let s = GoalText.date(w.weekStart) else { return false }
            return day >= s && day < Calendar.current.date(byAdding: .day, value: 7, to: s)!
        }
    }

    private func subscribe() async {
        do {
            let link = try await APIClient().calendarLink()
            if let url = URL(string: link.webcal) { await UIApplication.shared.open(url) }
        } catch {
            calendarMessage = error.localizedDescription
        }
    }

    private func copyLink() async {
        do {
            UIPasteboard.general.string = try await APIClient().calendarLink().url
            calendarMessage = "Link copied. In Google Calendar or Outlook, add a calendar \"from URL\" and paste it. It updates itself when your plan changes."
        } catch {
            calendarMessage = error.localizedDescription
        }
    }
}

enum PlanText {
    static func phase(_ p: String) -> String {
        ["base": "Base", "build": "Build", "sharpen": "Sharpen", "recovery": "Easier week", "taper": "Taper"][p] ?? p.capitalized
    }

    static func duration(_ seconds: Double) -> String {
        let m = Int((seconds / 60).rounded())
        return m >= 60 ? "\(m / 60) h \(String(format: "%02d", m % 60))" : "\(m) min"
    }

    static func short(_ seconds: Double) -> String {
        seconds < 60 ? "\(Int(seconds)) s" : seconds.truncatingRemainder(dividingBy: 60) == 0 ? "\(Int(seconds / 60)) min" : duration(seconds)
    }

    static func zoneColor(_ z: String?) -> Color {
        switch z {
        case "Z1": Color(hex: 0xC9D3F2)
        case "Z2": Color(hex: 0x9DB0E6)
        case "Z3": Color(hex: 0x6A86D4)
        case "SS": Color(hex: 0x3352A6)
        case "Z4": Color(hex: 0x1D3A8C)
        case "Z5": Color(hex: 0x7C1E3E)
        case "Z6": Color(hex: 0x5A1530)
        default: Color(hex: 0x1B1618)
        }
    }

    static func intensity(_ s: PlanStep) -> Double {
        guard let t = s.target else { return 0.5 }
        return Double(t.pctFtp[0] + t.pctFtp[1]) / 200
    }

    static func target(_ s: PlanStep) -> String {
        guard let t = s.target else { return "" }
        var parts = [t.watts.map { "\($0[0])–\($0[1]) W" } ?? "\(t.pctFtp[0])–\(t.pctFtp[1])% FTP"]
        if let hr = t.hr { parts.append("♥ \(hr[0])–\(hr[1])") }
        return parts.joined(separator: " · ")
    }
}

// MARK: - Calendar

private struct MonthCalendar: View {
    let plan: TrainingPlan
    @Binding var month: Date
    @Binding var selected: Date
    private let cal = Calendar(identifier: .iso8601)

    var body: some View {
        let byDay = Dictionary(grouping: plan.sessions, by: \.date)
        VStack(spacing: 10) {
            HStack {
                Button { shift(-1) } label: { Image(systemName: "chevron.left").frame(width: 44, height: 44) }
                    .accessibilityLabel("Previous month")
                Spacer()
                Text(month.formatted(.dateTime.month(.wide).year())).font(Theme.text(17, .semibold))
                Spacer()
                Button { shift(1) } label: { Image(systemName: "chevron.right").frame(width: 44, height: 44) }
                    .accessibilityLabel("Next month")
            }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 4), count: 7), spacing: 6) {
                ForEach(["M", "T", "W", "T", "F", "S", "S"].indices, id: \.self) { i in
                    Text(["M", "T", "W", "T", "F", "S", "S"][i]).font(Theme.mono(11)).foregroundStyle(Theme.label)
                }
                ForEach(cells(), id: \.self) { day in
                    if let day {
                        let key = iso(day)
                        DayCell(day: day, sessions: byDay[key] ?? [], selected: cal.isDate(day, inSameDayAs: selected),
                                today: cal.isDateInToday(day)) { selected = day }
                    } else {
                        Color.clear.frame(height: 48)
                    }
                }
            }
            HStack(spacing: 14) {
                Legend(color: Theme.cobalt, label: "Done", filled: true)
                Legend(color: Theme.cobalt, label: "Planned", filled: false)
                Legend(color: Theme.heart, label: "Missed", filled: false)
                Legend(color: Color(hex: 0xB89A3E), label: "Off bike", filled: true)
            }
            .font(Theme.text(11)).foregroundStyle(Theme.inkMuted)
        }
        .padding(12).surfaceCard(radius: 18)
    }

    private func shift(_ n: Int) {
        month = cal.date(byAdding: .month, value: n, to: month)!
    }

    private func cells() -> [Date?] {
        let first = cal.date(from: cal.dateComponents([.year, .month], from: month))!
        let lead = (cal.component(.weekday, from: first) + 5) % 7   // Monday first
        let days = cal.range(of: .day, in: .month, for: first)!.count
        return Array(repeating: nil, count: lead) + (0..<days).map { cal.date(byAdding: .day, value: $0, to: first) }
    }

    private func iso(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: d)
    }
}

private struct DayCell: View {
    let day: Date
    let sessions: [PlanSession]
    let selected: Bool
    let today: Bool
    let tap: () -> Void

    var body: some View {
        Button(action: tap) {
            VStack(spacing: 4) {
                Text("\(Calendar.current.component(.day, from: day))")
                    .font(Theme.text(14, today ? .semibold : .regular))
                    .foregroundStyle(selected ? .white : today ? Theme.cobalt : Theme.ink)
                HStack(spacing: 3) {
                    ForEach(sessions.prefix(3)) { s in Dot(session: s, onDark: selected) }
                }
                .frame(height: 7)
            }
            .frame(maxWidth: .infinity, minHeight: 48)
            .background(selected ? Theme.cobalt : Color.clear, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(today && !selected ? Theme.cobalt : .clear, lineWidth: 1.5))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(day.formatted(.dateTime.weekday(.wide).day().month(.wide))), \(sessions.map(\.title).joined(separator: ", "))")
    }
}

private struct Dot: View {
    let session: PlanSession
    var onDark = false

    var body: some View {
        let color = session.offBike ? Color(hex: 0xB89A3E) : session.status == "missed" ? Theme.heart : onDark ? .white : Theme.cobalt
        let filled = session.status == "done" || session.offBike && session.status == "done"
        Circle().fill(filled ? color : .clear).overlay(Circle().stroke(color, lineWidth: 1.5)).frame(width: 7, height: 7)
    }
}

private struct Legend: View {
    let color: Color
    let label: String
    let filled: Bool

    var body: some View {
        HStack(spacing: 4) {
            Circle().fill(filled ? color : .clear).overlay(Circle().stroke(color, lineWidth: 1.5)).frame(width: 7, height: 7)
            Text(label)
        }
    }
}

// MARK: - The selected day

private struct DaySessions: View {
    let plan: TrainingPlan
    let day: Date

    var body: some View {
        let key = { let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"; return f.string(from: day) }()
        let sessions = plan.sessions.filter { $0.date == key }
        VStack(alignment: .leading, spacing: 8) {
            MonoLabel(day.formatted(.dateTime.weekday(.wide).day().month(.wide))).padding(.horizontal, 4)
            if sessions.isEmpty {
                Text("Rest day. Recovery is where the fitness is made.")
                    .font(Theme.text(14)).foregroundStyle(Theme.inkMuted).padding(.horizontal, 4)
            }
            ForEach(sessions) { s in
                NavigationLink { SessionDetail(session: s, plan: plan) } label: { SessionCard(session: s) }
                    .buttonStyle(.plain)
            }
        }
    }
}

struct SessionCard: View {
    let session: PlanSession

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(session.time).font(Theme.mono(12)).foregroundStyle(Theme.inkMuted)
                Text(session.title).font(Theme.text(17, .semibold)).foregroundStyle(Theme.ink)
                Spacer()
                StatusChip(status: session.status)
            }
            Text("\(PlanText.duration(session.seconds)) · \(session.offBike ? "off the bike" : session.indoor ? "indoors" : "outdoors")"
                 + (session.steps.first(where: { $0.set != nil })?.set.map { " · \($0)" } ?? ""))
                .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
            if !session.steps.isEmpty {
                IntervalChart(steps: session.steps).frame(height: 44)
            }
        }
        .padding(14).surfaceCard(radius: 16).contentShape(Rectangle())
    }
}

struct StatusChip: View {
    let status: String

    var body: some View {
        let (text, color): (String, Color) = switch status {
        case "done": ("Done", Theme.cobalt)
        case "missed": ("Missed", Theme.heart)
        case "today": ("Today", Color(hex: 0x7A5410))
        case "open": ("To do", Theme.inkMuted)
        default: ("", .clear)
        }
        if !text.isEmpty {
            Text(text).font(Theme.mono(11)).foregroundStyle(color)
                .padding(.horizontal, 8).padding(.vertical, 3).overlay(Capsule().stroke(color))
        }
    }
}

private struct WeekSummary: View {
    let week: TrainingPlan.Week

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                MonoLabel("Week \(week.index) · \(PlanText.phase(week.phase))")
                Text("\(Format.number(week.hours, decimals: 1)) h planned · \(week.done) of \(week.total) done")
                    .font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
            }
            Spacer()
        }
        .padding(14).surfaceCard(radius: 16)
    }
}

/// The session's shape: each step a block, as wide as it is long and as tall as it is hard.
struct IntervalChart: View {
    let steps: [PlanStep]

    var body: some View {
        let flat = steps.flatMap(\.flat)
        let total = max(1, flat.reduce(0) { $0 + ($1.seconds ?? 0) })
        GeometryReader { geo in
            HStack(alignment: .bottom, spacing: 0) {
                ForEach(Array(flat.enumerated()), id: \.offset) { _, s in
                    Rectangle()
                        .fill(PlanText.zoneColor(s.zone))
                        .frame(width: max(1, geo.size.width * CGFloat((s.seconds ?? 0) / total)),
                               height: geo.size.height * CGFloat(min(1, PlanText.intensity(s) / 1.5)))
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .bottomLeading)
        }
        .clipShape(RoundedRectangle(cornerRadius: 4))
        .accessibilityHidden(true)
    }
}

// MARK: - Session detail

struct SessionDetail: View {
    @EnvironmentObject var model: AppModel
    let session: PlanSession
    let plan: TrainingPlan?
    @State private var shareURL: URL?
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 6) {
                    MonoLabel("\(session.day?.formatted(.dateTime.weekday(.wide).day().month(.wide)) ?? session.date) · \(session.time)")
                    Text(session.title).font(Theme.heading(40)).foregroundStyle(Theme.ink)
                    Text(session.purpose).font(Theme.text(15)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
                }
                if !session.steps.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            HeroStat(label: "Time", value: PlanText.duration(session.seconds), unit: nil)
                            Spacer()
                            if let load = session.load { HeroStat(label: "Load", value: "\(Int(load))", unit: nil) }
                        }
                        IntervalChart(steps: session.steps).frame(height: 90)
                        if plan?.ftp.watts == nil {
                            Text("Watts appear once we know your FTP. Until then, ride by % of FTP and heart rate.")
                                .font(Theme.text(12)).foregroundStyle(Theme.panelLabel)
                        }
                    }
                    .foregroundStyle(.white).padding(16)
                    .background(Theme.panel, in: RoundedRectangle(cornerRadius: 20, style: .continuous))

                    MonoLabel("The session")
                    VStack(spacing: 0) {
                        ForEach(Array(session.steps.enumerated()), id: \.offset) { i, s in
                            StepRow(step: s)
                            if i < session.steps.count - 1 { Rectangle().fill(Theme.line).frame(height: 1) }
                        }
                    }
                    .padding(.horizontal, 14).surfaceCard(radius: 16)
                }
                HStack {
                    Button(session.status == "done" ? "Mark not done" : "Mark as done") {
                        Task {
                            await model.run("Couldn't update the session") { try await APIClient().setDone(session.id, session.status != "done") }
                        }
                    }
                    .buttonStyle(SecondaryButton())
                    Spacer()
                    if !session.steps.isEmpty && session.indoor {
                        Button("Export for Zwift") { Task { await export() } }.buttonStyle(SecondaryButton())
                    }
                }
                if let error { Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart) }
                Text("Zwift: put the file in Documents/Zwift/Workouts and Zwift sets your KICKR's resistance for each step.")
                    .font(Theme.text(12)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                    .opacity(session.indoor && !session.steps.isEmpty ? 1 : 0)
            }
            .padding(16)
        }
        .background(Theme.ground.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: Binding(get: { shareURL != nil }, set: { if !$0 { shareURL = nil } })) {
            if let shareURL { ShareSheet(items: [shareURL]).presentationDetents([.medium, .large]) }
        }
    }

    private func export() async {
        do {
            let data = try await APIClient().zwift(session.id)
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(session.title) \(session.date).zwo")
            try data.write(to: url)
            shareURL = url
        } catch {
            self.error = error.localizedDescription
        }
    }
}

private struct StepRow: View {
    let step: PlanStep

    var body: some View {
        if let set = step.set, let inner = step.steps {
            VStack(alignment: .leading, spacing: 6) {
                Text(set).font(Theme.text(15, .semibold))
                ForEach(Array(inner.enumerated()), id: \.offset) { _, s in
                    if s.set != nil { StepRow(step: s).padding(.leading, 12) } else { line(s, indent: true) }
                }
            }
            .padding(.vertical, 10)
        } else {
            line(step, indent: false).padding(.vertical, 10)
        }
    }

    private func line(_ s: PlanStep, indent: Bool) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            RoundedRectangle(cornerRadius: 2).fill(PlanText.zoneColor(s.zone)).frame(width: 4, height: 16)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(s.label ?? "") · \(PlanText.short(s.seconds ?? 0))").font(Theme.text(indent ? 14 : 15, indent ? .regular : .semibold))
                if let t = s.target {
                    Text(PlanText.target(s)).font(Theme.mono(12)).foregroundStyle(Theme.cobalt)
                    Text("\(t.zoneName) · feels \(t.rpe)/10").font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.leading, indent ? 12 : 0)
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Settings sheets

private struct FTPBanner: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: "bolt.fill").foregroundStyle(Theme.cobalt)
                Text("Targets show as % of FTP and heart rate until your first rides with power. Know your FTP? Add it.")
                    .font(Theme.text(13)).foregroundStyle(Theme.inkSoft).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            .padding(12).surfaceCard(radius: 14)
        }
        .buttonStyle(.plain)
    }
}

private struct FTPSheet: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let current: TrainingPlan.FTP?
    @State private var text = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Watts", text: $text).keyboardType(.numberPad)
                } header: { Text("Your FTP") } footer: {
                    Text("The most power you can hold for about an hour. Zwift and Garmin estimate it. Leave it empty and we'll estimate it from your rides with power.\n\nNow: \(current?.watts.map { "\(Int($0)) W, \(current!.source)" } ?? current?.source ?? "unknown")")
                }
            }
            .navigationTitle("FTP").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        let w = Double(text.trimmingCharacters(in: .whitespaces))
                        Task {
                            await model.run("Couldn't save your FTP") { try await APIClient().setFTP(w) }
                            dismiss()
                        }
                    }
                }
            }
            .onAppear { if current?.source == "yours", let w = current?.watts { text = String(Int(w)) } }
        }
    }
}

private struct DaysSheet: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let plan: TrainingPlan
    @State private var days: Set<String> = []
    @State private var times: [String: Date] = [:]
    @State private var hours = 4.5
    @State private var saving = false
    private let all = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    ForEach(all, id: \.self) { d in
                        HStack {
                            Toggle(isOn: Binding(get: { days.contains(d) }, set: { if $0 { days.insert(d) } else { days.remove(d) } })) {
                                Text(d)
                            }
                            if days.contains(d) {
                                DatePicker("", selection: Binding(get: { times[d] ?? Self.time("07:00") }, set: { times[d] = $0 }),
                                           displayedComponents: .hourAndMinute).labelsHidden()
                            }
                        }
                    }
                } header: { Text("Days you can ride, and when") } footer: {
                    Text("The longest session goes on a weekend day if you pick one. The plan changes from today; past weeks stay as they were.")
                }
                Section("Time each week") {
                    Picker("Hours", selection: $hours) {
                        Text("About 3 h").tag(3.0)
                        Text("4–5 h").tag(4.5)
                        Text("6 h or more").tag(6.0)
                    }
                    .pickerStyle(.segmented)
                }
            }
            .navigationTitle("Days and times").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { save() }.disabled(days.isEmpty || saving)
                }
            }
            .onAppear {
                days = Set(plan.days)
                times = plan.times.mapValues(Self.time)
                hours = [3.0, 4.5, 6.0].min(by: { abs($0 - plan.weeklyHours) < abs($1 - plan.weeklyHours) }) ?? 4.5
            }
        }
    }

    private static func time(_ s: String) -> Date {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        return f.date(from: s) ?? Date()
    }

    private func save() {
        saving = true
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        let order = all.filter(days.contains)
        let t = Dictionary(uniqueKeysWithValues: order.map { ($0, f.string(from: times[$0] ?? Self.time("07:00"))) })
        Task {
            await model.run("Couldn't save your plan settings") { _ = try await APIClient().planSettings(days: order, times: t, weeklyHours: hours) }
            dismiss()
        }
    }
}

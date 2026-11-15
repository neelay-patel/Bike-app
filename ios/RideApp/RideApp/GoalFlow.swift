import SwiftUI

/// Setting a goal (the approved mock-up, docs/coaching.md): pick an objective, say what it looks like
/// for you, a few taps of detail, then the reveal (the gap, from your own rides) and the goal with the
/// markers we'll watch. Every number comes from the server's goals engine.
struct GoalFlow: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var options: GoalOptions?
    @State private var draft = GoalDraft()
    @State private var path: [Step] = []
    @State private var error: String?

    enum Step: Hashable { case aspiration, details, reveal, goal }

    var body: some View {
        NavigationStack(path: $path) {
            GoalScreen(label: "Step 1 of 5 · Your goal", title: "What do you want from your riding?") {
                Text("Pick the one that matters most right now. Your plan, and what we track, follow from it.")
                    .font(Theme.text(15)).foregroundStyle(Theme.inkSoft)
                if let options {
                    LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                        ForEach(options.objectives) { o in
                            Button {
                                draft = GoalDraft(objective: o.id)
                                path.append(.aspiration)
                            } label: { ObjectiveTile(objective: o) }
                            .buttonStyle(.plain)
                        }
                    }
                } else if let error {
                    Text(error).font(Theme.text(14)).foregroundStyle(Theme.heart)
                } else {
                    ProgressView().tint(Theme.cobalt).frame(maxWidth: .infinity)
                }
            }
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .navigationDestination(for: Step.self) { step in
                switch step {
                case .aspiration: AspirationStep(options: options, draft: $draft) { path.append(.details) }
                case .details: DetailsStep(options: options, draft: $draft) { path.append(.reveal) }
                case .reveal: RevealStep(draft: $draft) { path.append(.goal) }
                case .goal: GoalStep(draft: $draft) {
                    await model.refresh()
                    dismiss()
                }
                }
            }
        }
        .tint(Theme.cobalt)
        .task {
            do { options = try await APIClient().goalOptions() } catch { self.error = error.localizedDescription }
        }
    }
}

/// The shared page: mono step label, serif title, content, optional bottom button.
private struct GoalScreen<Content: View>: View {
    let label: String
    let title: String
    var button: String? = nil
    var buttonDisabled = false
    var action: (() -> Void)? = nil
    @ViewBuilder let content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    MonoLabel(label)
                    Text(title).font(Theme.heading(38)).foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
                content
            }
            .padding(.horizontal, 20).padding(.top, 8).padding(.bottom, 24)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Theme.ground.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .safeAreaInset(edge: .bottom) {
            if let button, let action {
                Button(button, action: action)
                    .buttonStyle(DarkButton()).disabled(buttonDisabled)
                    .padding(.horizontal, 20).padding(.vertical, 10)
                    .background(Theme.ground)
            }
        }
    }
}

struct DarkButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.text(16, .semibold)).foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 52)
            .background(Theme.ink.opacity(configuration.isPressed ? 0.8 : 1), in: Capsule())
    }
}

private struct ObjectiveTile: View {
    let objective: GoalOptions.Objective

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Image(systemName: icon).font(.system(size: 22, weight: .semibold)).foregroundStyle(Theme.cobalt)
            Spacer(minLength: 24)
            Text(objective.title).font(Theme.heading(30)).foregroundStyle(Theme.ink)
            Text(objective.line).font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, minHeight: 160, alignment: .topLeading)
        .padding(16).surfaceCard(radius: 18)
        .contentShape(Rectangle())
    }

    private var icon: String {
        switch objective.id {
        case "faster": "hare.fill"
        case "further": "road.lanes"
        case "stronger": "mountain.2.fill"
        default: "calendar"
        }
    }
}

// MARK: - Step 2: what it looks like for you

private struct AspirationStep: View {
    let options: GoalOptions?
    @Binding var draft: GoalDraft
    let next: () -> Void

    var body: some View {
        let objective = options?.objectives.first { $0.id == draft.objective }
        GoalScreen(label: "\(objective?.title ?? "") · Step 2 of 5", title: "What does \(objective?.title.lowercased() ?? "it") look like for you?",
                   button: "Continue", buttonDisabled: draft.aspiration.isEmpty, action: next) {
            ForEach(objective?.aspirations ?? []) { a in
                let selected = draft.aspiration == a.id
                Button {
                    draft.aspiration = a.id
                    draft.targetKm = a.targetKm
                } label: {
                    HStack(spacing: 12) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(a.title).font(Theme.text(17, .semibold))
                            Text(a.line).font(Theme.text(13)).foregroundStyle(selected ? Theme.cobaltSoft : Theme.inkMuted)
                        }
                        Spacer(minLength: 0)
                        if selected { Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.sand) }
                    }
                    .foregroundStyle(selected ? .white : Theme.ink)
                    .padding(.horizontal, 16).padding(.vertical, 14)
                    .frame(maxWidth: .infinity, minHeight: 64, alignment: .leading)
                    .background(selected ? Theme.cobalt : Theme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(selected ? Theme.cobalt : Theme.line))
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
            VStack(alignment: .leading, spacing: 6) {
                MonoLabel("Or say it your way")
                TextField("e.g. I keep getting dropped on Saturdays", text: $draft.words, axis: .vertical)
                    .lineLimit(1...4)
                    .font(Theme.text(15)).padding(12)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.line))
                Text("Saved with your goal. The coach will read it to understand what you're after.")
                    .font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
            }
        }
    }
}

// MARK: - Step 3: a few taps of detail

private struct DetailsStep: View {
    let options: GoalOptions?
    @Binding var draft: GoalDraft
    let next: () -> Void
    @State private var byDate = false

    var body: some View {
        GoalScreen(label: "Step 3 of 5", title: title, button: "Show me what it means", action: next) {
            Text("A few taps. A rough guess is fine.").font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
            switch draft.aspiration {
            case "keep_up_group":
                ChoiceRow(label: "How fast do they ride?", values: [28.0, 30, 32, 35], selection: $draft.groupKmh) { "\(Int($0)) km/h" }
                ChoiceRow(label: "How long are the rides?", values: [1.0, 1.75, 3], selection: $draft.rideHours) {
                    $0 == 1 ? "About 1 h" : $0 == 1.75 ? "1.5–2 h" : "3 h or more"
                }
                ChoiceRow(label: "What are the roads like?", values: ["flat", "rolling", "hilly"], selection: $draft.terrain) { $0.capitalized }
            case "first_distance":
                let base = draft.targetKm ?? 150
                ChoiceRow(label: "How far?", values: [base, base + 30, base + 80], selection: Binding(
                    get: { draft.targetKm ?? base }, set: { draft.targetKm = $0 })) { "\(Int($0)) km" }
            case "event":
                ChoiceRow(label: "How long is it?", values: [60.0, 100, 160, 200], selection: Binding(
                    get: { draft.eventKm ?? 100 }, set: { draft.eventKm = $0 })) { "\(Int($0)) km" }
                ChoiceRow(label: "How much climbing?", values: [500.0, 1000, 2000, 3000], selection: Binding(
                    get: { draft.eventClimbingM ?? 1000 }, set: { draft.eventClimbingM = $0 })) { "\(Int($0)) m" }
            default:
                EmptyView()
            }
            VStack(alignment: .leading, spacing: 8) {
                MonoLabel(draft.aspiration == "event" ? "When is it?" : "When do you want to be ready?")
                if draft.aspiration != "event" {
                    HStack(spacing: 8) {
                        Chip(text: whenOutdoor, selected: !byDate) { byDate = false; draft.readyBy = nil }
                        Chip(text: "By a date", selected: byDate) { byDate = true; draft.readyBy = draft.readyBy ?? defaultDate }
                    }
                }
                if byDate || draft.aspiration == "event" {
                    DatePicker("Date", selection: Binding(get: { draft.readyBy ?? defaultDate }, set: { draft.readyBy = $0 }),
                               in: Date()..., displayedComponents: .date)
                        .labelsHidden().tint(Theme.cobalt)
                }
            }
            ChoiceRow(label: "Time you can give it each week", values: [3.0, 4.5, 6], selection: $draft.weeklyHours) {
                $0 == 3 ? "About 3 h" : $0 == 4.5 ? "4–5 h" : "6 h or more"
            }
        }
        .onAppear { if draft.aspiration == "event" && draft.readyBy == nil { draft.readyBy = defaultDate } }
    }

    private var title: String {
        switch draft.aspiration {
        case "keep_up_group": "Tell us about the group"
        case "event": "Tell us about the event"
        default: "A few details"
        }
    }

    private var whenOutdoor: String {
        guard let from = options?.season.outdoorFrom, let d = GoalText.date(from) else { return "This season" }
        return "When the roads open (\(d.formatted(.dateTime.day().month(.abbreviated))))"
    }

    private var defaultDate: Date { Calendar.current.date(byAdding: .month, value: 4, to: Date()) ?? Date() }
}

private struct ChoiceRow<V: Hashable>: View {
    let label: String
    let values: [V]
    @Binding var selection: V
    let text: (V) -> String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            MonoLabel(label)
            FlowLayout(spacing: 8) {
                ForEach(values, id: \.self) { v in
                    Chip(text: text(v), selected: v == selection) { selection = v }
                }
            }
        }
    }
}

private struct Chip: View {
    let text: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(text).font(Theme.text(15, selected ? .semibold : .regular))
                .foregroundStyle(selected ? .white : Theme.ink)
                .padding(.horizontal, 16).frame(minHeight: 44)
                .background(selected ? Theme.cobalt : Theme.surface, in: Capsule())
                .overlay(Capsule().stroke(selected ? Theme.cobalt : Theme.line))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

// MARK: - Step 4: the reveal

private struct RevealStep: View {
    @Binding var draft: GoalDraft
    let next: () -> Void
    @State private var view: GoalView?
    @State private var error: String?

    var body: some View {
        GoalScreen(label: "Step 4 of 5 · From your rides", title: "Here's the gap", button: "Set my goal",
                   buttonDisabled: view == nil, action: next) {
            if let v = view {
                VStack(alignment: .leading, spacing: 14) {
                    if let solo = v.reveal.figures.soloKmh, let group = v.reveal.figures.groupKmh {
                        HStack(alignment: .bottom) {
                            GapNumber(label: "You, solo", value: solo, caption: "km/h on your flat rides", color: .white)
                            Spacer()
                            Image(systemName: "arrow.right").foregroundStyle(Theme.cobaltSoft)
                            Spacer()
                            GapNumber(label: "The goal", value: group, caption: "km/h", color: Theme.sand)
                        }
                    }
                    Text(v.reveal.headline).font(Theme.text(16)).foregroundStyle(.white)
                        .fixedSize(horizontal: false, vertical: true)
                    ForEach(v.reveal.notes.dropLast(), id: \.self) { n in
                        Text(n).font(Theme.text(15)).foregroundStyle(Color(hex: 0xE2DADC)).fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(18).frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.panel, in: RoundedRectangle(cornerRadius: 22, style: .continuous))

                MonoLabel("What we'll build")
                ForEach(Array(v.reveal.build.enumerated()), id: \.element.id) { i, b in
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text("\(i + 1)").font(Theme.hero(22)).foregroundStyle(Theme.cobalt)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(b.title).font(Theme.text(15, .semibold))
                            Text(b.line).font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 14).padding(.vertical, 12).surfaceCard(radius: 14)
                }
                if let last = v.reveal.notes.last {
                    Text(last).font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
                }
            } else if let error {
                Text(error).font(Theme.text(14)).foregroundStyle(Theme.heart)
            } else {
                ProgressView("Looking at your rides").tint(Theme.cobalt).frame(maxWidth: .infinity).padding(.vertical, 40)
            }
        }
        .task {
            do { view = try await APIClient().goalPreview(draft) } catch { self.error = error.localizedDescription }
        }
    }
}

private struct GapNumber: View {
    let label: String
    let value: Double
    let caption: String
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            MonoLabel(label, color: Theme.panelLabel)
            Text(Format.hero(value, decimals: value.rounded() == value ? 0 : 1)).font(Theme.hero(48)).foregroundStyle(color)
            Text(caption).font(Theme.text(12)).foregroundStyle(Theme.panelLabel)
        }
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Step 5: the goal and how you'll see it working

private struct GoalStep: View {
    @Binding var draft: GoalDraft
    let done: () async -> Void
    @State private var view: GoalView?
    @State private var saving = false
    @State private var error: String?

    var body: some View {
        GoalScreen(label: "Step 5 of 5", title: "Your goal", button: saving ? "Saving…" : "Start my goal",
                   buttonDisabled: view == nil || saving, action: save) {
            if let v = view {
                GoalSummary(view: v)
            } else if let error {
                Text(error).font(Theme.text(14)).foregroundStyle(Theme.heart)
            } else {
                ProgressView().tint(Theme.cobalt).frame(maxWidth: .infinity).padding(.vertical, 40)
            }
        }
        .task {
            do { view = try await APIClient().goalPreview(draft) } catch { self.error = error.localizedDescription }
        }
    }

    private func save() {
        saving = true
        Task {
            do {
                _ = try await APIClient().setGoal(draft)
                await done()
            } catch {
                self.error = error.localizedDescription
                saving = false
            }
        }
    }
}

/// The goal card, its markers and the season: shown at the end of the flow and on the You tab.
struct GoalSummary: View {
    let view: GoalView
    var compact = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            MonoLabel("Your goal", color: Theme.cobaltSoft)
            Text(view.goal.title).font(Theme.heading(compact ? 28 : 32)).foregroundStyle(.white)
                .fixedSize(horizontal: false, vertical: true)
            if let by = view.goal.readyBy.flatMap(GoalText.date) {
                Text("Ready by \(by.formatted(.dateTime.day().month(.wide).year()))").font(Theme.text(14)).foregroundStyle(Color(hex: 0xE3E8F7))
            }
            if let words = view.goal.words, !compact {
                Text("“\(words)”").font(Theme.text(13)).foregroundStyle(Theme.cobaltSoft).padding(.top, 4)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.cobalt, in: RoundedRectangle(cornerRadius: 20, style: .continuous))

        MonoLabel("How you'll see it working").padding(.top, 4)
        VStack(spacing: 0) {
            ForEach(Array(view.markers.enumerated()), id: \.element.id) { i, m in
                MarkerRow(marker: m)
                if i < view.markers.count - 1 { Rectangle().fill(Theme.line).frame(height: 1) }
            }
        }
        .padding(.horizontal, 14).surfaceCard(radius: 16)
        Text("Read from your normal riding. No tests needed.").font(Theme.text(12)).foregroundStyle(Theme.inkMuted)

        if !compact {
            MonoLabel("Your season").padding(.top, 4)
            Text(GoalText.season(view.season)).font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct MarkerRow: View {
    let marker: GoalView.Marker

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(marker.label).font(Theme.text(14))
                if let pending = marker.pending {
                    Text(pending).font(Theme.text(12)).foregroundStyle(Theme.inkMuted)
                }
            }
            Spacer(minLength: 6)
            let values = marker.history.map(\.value)
            if values.count > 2 {
                Sparkline(values: Array(values.suffix(20)), higherIsBetter: marker.better == "higher").frame(width: 54, height: 22)
            }
            if let cur = marker.current {
                (Text(cur.formatted()) + Text(" → ").foregroundColor(Theme.inkMuted)
                 + Text((marker.target?.formatted() ?? "–") + marker.unitText).foregroundColor(Theme.cobalt).bold())
                    .font(Theme.mono(13)).lineLimit(1).minimumScaleFactor(0.8)
            }
        }
        .padding(.vertical, 10)
        .accessibilityElement(children: .combine)
    }
}

enum GoalText {
    static func date(_ iso: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: iso)
    }

    static func season(_ s: Season) -> String {
        let months = s.outdoorMonths.map { Calendar.current.monthSymbols[$0 - 1] }
        let range = months.count > 1 ? "\(months.first!) to \(months.last!)" : months.first ?? ""
        let from = s.outdoorFrom.flatMap(date).map { $0.formatted(.dateTime.day().month(.wide)) }
        switch s.now {
        case "indoor": return "You ride outdoors \(range). You're in your indoor months now: a build on Zwift and the KICKR"
            + (from.map { ", outdoors again from \($0)." } ?? ".")
        case "outdoor": return "You're in your outdoor season (\(range))."
        default: return months.isEmpty ? "We'll learn your season as you ride." : "You ride outdoors \(range)."
        }
    }
}

// MARK: - On the You tab

/// The active goal and its markers, or a prompt to set one.
struct GoalCard: View {
    @EnvironmentObject var model: AppModel
    @State private var settingGoal = false
    @State private var confirmEnd = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let goal = model.goal {
                GoalSummary(view: goal, compact: true)
                HStack {
                    Button("Change goal") { settingGoal = true }.buttonStyle(SecondaryButton())
                    Spacer()
                    Button("End goal", role: .destructive) { confirmEnd = true }
                        .font(Theme.text(14)).tint(Theme.heart)
                }
            } else {
                Button { settingGoal = true } label: {
                    HStack(spacing: 14) {
                        Image(systemName: "scope").font(.system(size: 26)).foregroundStyle(Theme.cobalt)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Set a goal").font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                            Text("Faster, further, stronger or an event. We'll show what it takes, from your own rides.")
                                .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: 0)
                        Image(systemName: "chevron.right").foregroundStyle(Theme.label)
                    }
                    .padding(14).surfaceCard(radius: 16).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .sheet(isPresented: $settingGoal) { GoalFlow() }
        .confirmationDialog("End this goal?", isPresented: $confirmEnd, titleVisibility: .visible) {
            Button("End goal", role: .destructive) {
                Task { await model.run { try await APIClient().endGoal() } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("It's kept in your history. You can set a new one any time.")
        }
    }
}

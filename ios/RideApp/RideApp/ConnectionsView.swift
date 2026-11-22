import SwiftUI

/// One card per source: connect once, then rides arrive on their own.
struct ConnectionsView: View {
    @EnvironmentObject var model: AppModel
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    // No big title (20 Nov 2026); the settings gear keeps its place on the right.
                    HStack(alignment: .center) {
                        MonoLabel("Where your rides come from")
                        Spacer()
                        Button { showSettings = true } label: {
                            Image(systemName: "gearshape").font(.system(size: 20)).frame(width: 44, height: 44)
                        }
                        .accessibilityLabel("Settings")
                    }
                    .padding(.horizontal, 4)
                    StatusLine()
                    AppleHealthCard().arrive(0)
                    MonoLabel("Accounts").padding(.horizontal, 4).padding(.top, 8)
                    ForEach(Array(model.connections.filter { $0.auth != "device" }.enumerated()), id: \.element.id) { i, c in
                        ProviderCard(connection: c).arrive(1 + i)
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 24)
            }
            .background(Theme.ground.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
            .refreshable { await model.refresh() }
            .sheet(isPresented: $showSettings) { SettingsView().presentationDragIndicator(.visible) }
        }
    }
}

struct AppleHealthCard: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var health: HealthSync
    @State private var since = Calendar.current.date(from: DateComponents(year: 2025, month: 1, day: 1))!
    @State private var confirmDisconnect = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("Apple Health", systemImage: "heart.text.square.fill")
                    .font(Theme.text(17, .semibold)).foregroundStyle(Theme.ink)
                Spacer()
                StateBadge(state: health.isConnected ? "connected" : "not_connected")
            }
            Text("Cycling workouts, their routes, and the heart rate, calories, distance, power, cadence and speed recorded during them. For recovery: heart rate for 3 minutes after each ride, VO2 max, HRV, resting heart rate and Cardio Recovery. Recovery data is only ever shown to you.")
                .font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
            if health.isConnected && health.needsPermission {
                Button("Allow new data") { Task { await health.allowNewData(); await model.refresh() } }
                    .buttonStyle(PrimaryButton())
            }
            if !health.isConnected {
                Text("On the Health screen, turn on every item and choose \"All Recorded Data\" so older rides can be imported. For new rides to arrive in the background, keep Background App Refresh on for Kova.")
                    .font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
            }
            DatePicker("Import rides since", selection: $since, displayedComponents: .date)
                .font(Theme.text(15)).tint(Theme.cobalt)
            if let p = health.progress {
                ProgressView(value: Double(p.done), total: Double(max(p.total, 1))) {
                    Text("Sending \(p.done) of \(p.total)").font(Theme.mono(12))
                }
                .tint(Theme.cobalt)
            }
            if let message = health.lastMessage {
                Text(message).font(Theme.text(13)).foregroundStyle(Theme.inkSoft)
            }
            HStack {
                if health.isConnected {
                    Button("Import history") { Task { await health.importHistory(since: since); await model.refresh() } }
                        .buttonStyle(SecondaryButton())
                    Spacer()
                    Button("Disconnect", role: .destructive) { confirmDisconnect = true }
                        .buttonStyle(SecondaryButton(color: Theme.heart))
                } else {
                    Button("Connect Apple Health") { Task { await health.connect(importSince: since); await model.refresh() } }
                        .buttonStyle(PrimaryButton())
                }
            }
            .disabled(health.isWorking)
        }
        .padding(16).surfaceCard()
        .confirmationDialog("Disconnect Apple Health?", isPresented: $confirmDisconnect, titleVisibility: .visible) {
            Button("Disconnect and delete its rides", role: .destructive) {
                Task { await health.disconnect(); await model.refresh() }
            }
        } message: {
            Text("Rides sent from Apple Health are deleted from the server. To stop access fully, also turn it off in the Health app.")
        }
    }
}

struct ProviderCard: View {
    @EnvironmentObject var model: AppModel
    let connection: Connection
    @State private var showKeySheet = false
    @State private var confirmDisconnect = false

    private var connected: Bool { connection.state != "not_connected" }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(connection.name).font(Theme.text(17, .semibold)).foregroundStyle(Theme.ink)
                Spacer()
                StateBadge(state: connection.availability == "available" ? connection.state : connection.availability)
            }
            Text(connection.gives).font(Theme.text(14)).foregroundStyle(Theme.inkSoft)
            if !connection.notes.isEmpty {
                Text(connection.notes).font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
            }
            if let detail = connection.detail {
                Text(detail).font(Theme.text(13)).foregroundStyle(Theme.heart)
            }
            if connection.availability == "available" {
                HStack {
                    if connected {
                        Text("\(connection.recordings) rides").font(Theme.mono(12)).foregroundStyle(Theme.inkMuted)
                        Spacer()
                        Button("Sync now") { Task { await model.run("Couldn't sync \(connection.name)") { _ = try await APIClient().sync(connection.provider) } } }
                            .buttonStyle(SecondaryButton())
                        Button("Disconnect", role: .destructive) { confirmDisconnect = true }
                            .buttonStyle(SecondaryButton(color: Theme.heart))
                    } else if connection.auth == "api_key" {
                        Button("Connect") { showKeySheet = true }.buttonStyle(PrimaryButton())
                    }
                }
                .padding(.top, 4)
            }
        }
        .padding(16).surfaceCard()
        .sheet(isPresented: $showKeySheet) { APIKeySheet(connection: connection) }
        .confirmationDialog("Disconnect \(connection.name)?", isPresented: $confirmDisconnect, titleVisibility: .visible) {
            Button("Disconnect and delete its rides", role: .destructive) {
                Task { await model.run("Couldn't disconnect \(connection.name)") { try await APIClient().disconnect(connection.provider) } }
            }
        }
    }
}

/// For providers that use a personal API key (Garmin's Personal tier).
struct APIKeySheet: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let connection: Connection
    @State private var key = ""
    @State private var since = Calendar.current.date(from: DateComponents(year: 2025, month: 1, day: 1))!
    @State private var working = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    SecureField("Personal API key", text: $key)
                        .autocorrectionDisabled()
                    DatePicker("Import rides since", selection: $since, displayedComponents: .date)
                } footer: {
                    Text("Create the key in Garmin Connect on the web: Settings → Personal API. It's stored encrypted on the server.")
                }
                if let error { Text(error).foregroundStyle(Theme.heart) }
            }
            .font(Theme.text(15))
            .scrollContentBackground(.hidden)
            .background(Theme.ground)
            .navigationTitle(connection.name)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Connect") {
                        working = true
                        Task {
                            do {
                                try await APIClient().connect(connection.provider, credentials: ["api_key": key], since: since)
                                await model.refresh()
                                dismiss()
                            } catch {
                                self.error = error.localizedDescription
                            }
                            working = false
                        }
                    }
                    .disabled(key.trimmingCharacters(in: .whitespaces).isEmpty || working)
                }
            }
        }
        .tint(Theme.cobalt)
    }
}

struct StateBadge: View {
    let state: String

    var body: some View {
        let (text, color): (String, Color) = switch state {
        case "connected": ("Connected", Theme.cobalt)
        case "error": ("Problem", Theme.heart)
        case "planned": ("Coming soon", Theme.label)
        case "blocked": ("Not available yet", Theme.label)
        default: ("Not connected", Theme.label)
        }
        HStack(spacing: 6) {
            if state == "connected" {
                // Live: rides arrive on their own.
                Circle().fill(color).frame(width: 7, height: 7)
                    .background(Ripple(color: color, size: 8))
                    .accessibilityHidden(true)
            }
            MonoLabel(text, color: color)
        }
    }
}

struct PrimaryButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.text(15, .semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 18).frame(minHeight: 44)
            .background(Theme.cobalt.opacity(configuration.isPressed ? 0.8 : 1), in: Capsule())
    }
}

struct SecondaryButton: ButtonStyle {
    var color: Color = Theme.ink

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.text(14, .medium))
            .foregroundStyle(color)
            .padding(.horizontal, 14).frame(minHeight: 44)
            .background(configuration.isPressed ? Theme.surfaceSelected : Theme.surface, in: Capsule())
            .overlay(Capsule().stroke(Theme.line, lineWidth: 1))
    }
}

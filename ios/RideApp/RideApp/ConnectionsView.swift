import SwiftUI

/// One row per provider: connect once, then rides arrive on their own.
struct ConnectionsView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        NavigationStack {
            List {
                if let error = model.error {
                    Text(error).foregroundStyle(.red).font(.footnote)
                }
                Section {
                    AppleHealthRow()
                }
                Section("Accounts") {
                    ForEach(model.connections.filter { $0.auth != "device" }) { c in
                        ProviderRow(connection: c)
                    }
                }
            }
            .navigationTitle("Connections")
            .refreshable { await model.refresh() }
        }
    }
}

struct AppleHealthRow: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var health: HealthSync
    @State private var since = Calendar.current.date(from: DateComponents(year: 2025, month: 1, day: 1))!
    @State private var confirmDisconnect = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("Apple Health", systemImage: "heart.text.square.fill").font(.headline)
                Spacer()
                StateBadge(state: health.isConnected ? "connected" : "not_connected")
            }
            Text("Cycling workouts, their routes, and the heart rate, calories and distance recorded during them.")
                .font(.footnote).foregroundStyle(.secondary)
            DatePicker("Import rides since", selection: $since, displayedComponents: .date)
            if let p = health.progress {
                ProgressView(value: Double(p.done), total: Double(max(p.total, 1))) {
                    Text("Sending \(p.done) of \(p.total)").font(.footnote)
                }
            }
            if let message = health.lastMessage {
                Text(message).font(.footnote)
            }
            HStack {
                if health.isConnected {
                    Button("Import history") { Task { await health.importHistory(since: since); await model.refresh() } }
                    Spacer()
                    Button("Disconnect", role: .destructive) { confirmDisconnect = true }
                } else {
                    Button("Connect Apple Health") { Task { await health.connect(importSince: since); await model.refresh() } }
                        .buttonStyle(.borderedProminent)
                }
            }
            .disabled(health.isWorking)
            .buttonStyle(.bordered)
        }
        .confirmationDialog("Disconnect Apple Health?", isPresented: $confirmDisconnect, titleVisibility: .visible) {
            Button("Disconnect and delete its rides", role: .destructive) {
                Task { await health.disconnect(); await model.refresh() }
            }
        } message: {
            Text("Rides sent from Apple Health are deleted from the server. To stop access fully, also turn it off in the Health app.")
        }
    }
}

struct ProviderRow: View {
    @EnvironmentObject var model: AppModel
    let connection: Connection
    @State private var showKeySheet = false
    @State private var confirmDisconnect = false

    private var connected: Bool { connection.state != "not_connected" }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(connection.name).font(.headline)
                Spacer()
                StateBadge(state: connection.availability == "available" ? connection.state : connection.availability)
            }
            Text(connection.gives).font(.footnote)
            if !connection.notes.isEmpty {
                Text(connection.notes).font(.footnote).foregroundStyle(.secondary)
            }
            if let detail = connection.detail {
                Text(detail).font(.footnote).foregroundStyle(.red)
            }
            if connection.availability == "available" {
                HStack {
                    if connected {
                        Text("\(connection.recordings) rides").font(.footnote).foregroundStyle(.secondary)
                        Spacer()
                        Button("Sync now") { Task { await model.run { _ = try await APIClient().sync(connection.provider) } } }
                        Button("Disconnect", role: .destructive) { confirmDisconnect = true }
                    } else if connection.auth == "api_key" {
                        Button("Connect") { showKeySheet = true }.buttonStyle(.borderedProminent)
                    }
                }
                .buttonStyle(.bordered)
            }
        }
        .sheet(isPresented: $showKeySheet) { APIKeySheet(connection: connection) }
        .confirmationDialog("Disconnect \(connection.name)?", isPresented: $confirmDisconnect, titleVisibility: .visible) {
            Button("Disconnect and delete its rides", role: .destructive) {
                Task { await model.run { try await APIClient().disconnect(connection.provider) } }
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
                if let error { Text(error).foregroundStyle(.red) }
            }
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
    }
}

struct StateBadge: View {
    let state: String

    var body: some View {
        let (text, color): (String, Color) = switch state {
        case "connected": ("Connected", .green)
        case "error": ("Problem", .red)
        case "planned": ("Coming soon", .secondary)
        case "blocked": ("Not available yet", .secondary)
        default: ("Not connected", .secondary)
        }
        Text(text).font(.caption.weight(.semibold)).foregroundStyle(color)
    }
}

import MapKit
import SwiftUI

/// Home, and the dev login: the backend's address and the token from `python -m backend create-user`.
struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var server = ServerConfig.serverURL?.absoluteString ?? ""
    @State private var token = ServerConfig.token ?? ""
    @State private var saved = false
    @FocusState private var editing: Bool

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        MonoLabel("You and the server")
                        Text("Settings").font(Theme.heading(44)).foregroundStyle(Theme.ink)
                    }
                    .padding(.horizontal, 4).padding(.top, 8)

                    HomeSetting()

                    MonoLabel("Development server").padding(.horizontal, 4).padding(.top, 12)
                    VStack(alignment: .leading, spacing: 0) {
                        field("Server", text: $server, prompt: "http://your-mac.local:8000", url: true)
                        Rectangle().fill(Theme.line).frame(height: 1)
                        // A plain field, not SecureField: iOS would offer to save the dev token as a password.
                        field("Token", text: $token, prompt: "Paste the token", url: false)
                    }
                    .surfaceCard(radius: 16)

                    Text("On the Mac: python -m backend create-user, then python -m backend serve --host 0.0.0.0. Copy the token on the Mac and paste it here.")
                        .font(Theme.text(13)).foregroundStyle(Theme.inkMuted).padding(.horizontal, 4)

                    Button("Save and check") {
                        editing = false
                        ServerConfig.serverURL = URL(string: server.trimmingCharacters(in: .whitespaces))
                        ServerConfig.token = token.trimmingCharacters(in: .whitespacesAndNewlines)
                        Task {
                            await model.refresh()
                            saved = true
                        }
                    }
                    .buttonStyle(PrimaryButton())

                    VStack(alignment: .leading, spacing: 4) {
                        MonoLabel("Credits")
                        Text("Place names: GeoNames (geonames.org), CC BY 4.0. Fonts: Instrument Serif, IBM Plex, Doto, under the SIL Open Font License.")
                            .font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                    }
                    .padding(.horizontal, 4).padding(.top, 16)
                    if saved {
                        if let error = model.error {
                            Text(error).font(Theme.text(14)).foregroundStyle(Theme.heart)
                        } else {
                            Label("Connected to the server", systemImage: "checkmark.circle.fill")
                                .font(Theme.text(14, .medium)).foregroundStyle(Theme.cobalt)
                        }
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 24)
            }
            .scrollDismissesKeyboard(.interactively)  // drag down to put the keyboard away
            .background(Theme.ground.ignoresSafeArea())
            .onTapGesture { editing = false }
            .toolbar(.hidden, for: .navigationBar)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") { editing = false }.font(Theme.text(16, .semibold))
                }
            }
        }
    }

    private func field(_ label: String, text: Binding<String>, prompt: String, url: Bool) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            MonoLabel(label)
            TextField(prompt, text: text)
                .focused($editing)
                .submitLabel(.done)
                .onSubmit { editing = false }
                .font(url ? Theme.text(15) : Theme.mono(14))
                .foregroundStyle(Theme.ink)
                .autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                .keyboardType(url ? .URL : .default)
                #endif
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
    }
}


/// Home: where "from home" routes start, which route is the home loop, and what the ride card hides.
/// Worked out from rides unless the rider sets it (searching Apple Maps for an address).
struct HomeSetting: View {
    @State private var home: HomeInfo?
    @State private var changing = false
    @State private var query = ""
    @State private var busy = false
    @State private var error: String?
    @StateObject private var search = PlaceSearch()
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            MonoLabel("Home")
            if let h = home {
                if h.source == "set" {
                    Text(h.label?.isEmpty == false ? h.label! : "Set by you").font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                    Text("Set by you.").font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                } else if h.source == "rides" {
                    Text(h.label.map { $0.prefix(1).uppercased() + $0.dropFirst() } ?? "From your rides")
                        .font(Theme.text(16, .semibold)).foregroundStyle(Theme.ink)
                    Text("Worked out from your rides: \(h.rides ?? 0) of them started here in the past year.")
                        .font(Theme.text(13)).foregroundStyle(Theme.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                } else {
                    Text("Not known yet: ride from home a few times, or set it.").font(Theme.text(14)).foregroundStyle(Theme.inkMuted)
                }
            } else if error == nil {
                ProgressView().controlSize(.small)
            }
            Text("Used for routes from home, your home loop, and the part of a ride card that's hidden near home.")
                .font(Theme.text(12)).foregroundStyle(Theme.label)
                .fixedSize(horizontal: false, vertical: true)
            if changing {
                TextField("Your address", text: $query)
                    .font(Theme.text(15)).focused($focused).autocorrectionDisabled()
                    .submitLabel(.search)
                    .onChange(of: query) { _, t in search.update(t) }
                    .padding(10)
                    .background(Theme.ground, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                ForEach(search.results, id: \.self) { c in
                    Button { pick(c) } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Image(systemName: "house").foregroundStyle(Theme.cobalt)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(c.title).font(Theme.text(15, .medium)).foregroundStyle(Theme.ink)
                                if !c.subtitle.isEmpty { Text(c.subtitle).font(Theme.text(12)).foregroundStyle(Theme.inkMuted) }
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 4).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(busy)
                }
            }
            HStack(spacing: 16) {
                Button(changing ? "Cancel" : (home?.source == "set" ? "Change" : "Set my address")) {
                    changing.toggle()
                    query = ""
                    focused = changing
                }
                if home?.source == "set" && !changing {
                    Button("Use my rides instead") { reset() }
                }
                if busy { ProgressView().controlSize(.small) }
            }
            .font(Theme.text(14, .medium)).foregroundStyle(Theme.cobalt).buttonStyle(.plain)
            if let error { Text(error).font(Theme.text(13)).foregroundStyle(Theme.heart) }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .surfaceCard(radius: 16)
        .task { await load() }
    }

    private func load() async {
        do { home = try await APIClient().home(); error = nil } catch { self.error = error.localizedDescription }
    }

    private func pick(_ c: MKLocalSearchCompletion) {
        busy = true
        Task {
            defer { busy = false }
            guard let p = await PlaceSearch.place(c), let lat = p["lat"] as? Double, let lon = p["lon"] as? Double else {
                error = "Apple Maps couldn't place that; try another way of writing it."
                return
            }
            do {
                home = try await APIClient().setHome(lat: lat, lon: lon, label: c.title)
                changing = false
                focused = false
                error = nil
            } catch { self.error = error.localizedDescription }
        }
    }

    private func reset() {
        busy = true
        Task {
            defer { busy = false }
            do { home = try await APIClient().clearHome(); error = nil } catch { self.error = error.localizedDescription }
        }
    }
}

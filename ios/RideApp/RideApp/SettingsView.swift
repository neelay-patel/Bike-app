import SwiftUI

/// Dev login: the backend's address and the token from `python -m backend create-user`.
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
                        MonoLabel("Development server")
                        Text("Settings").font(Theme.heading(44)).foregroundStyle(Theme.ink)
                    }
                    .padding(.horizontal, 4).padding(.top, 8)

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

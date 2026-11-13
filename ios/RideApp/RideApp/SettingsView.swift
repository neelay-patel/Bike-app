import SwiftUI

/// Dev login: the backend's address and the token from `python -m backend create-user`.
struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var server = ServerConfig.serverURL?.absoluteString ?? ""
    @State private var token = ServerConfig.token ?? ""
    @State private var saved = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://your-mac.local:8000", text: $server)
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        #endif
                    // A plain field, not SecureField: iOS would offer to save the dev token as a password.
                    TextField("Token", text: $token)
                        .font(.body.monospaced())
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        #endif
                } header: {
                    Text("Server")
                } footer: {
                    Text("On the Mac: python -m backend create-user, then python -m backend serve --host 0.0.0.0. Copy the token on the Mac and paste it here.")
                }
                Button("Save and check") {
                    ServerConfig.serverURL = URL(string: server.trimmingCharacters(in: .whitespaces))
                    ServerConfig.token = token.trimmingCharacters(in: .whitespacesAndNewlines)
                    Task {
                        await model.refresh()
                        saved = true
                    }
                }
                if saved {
                    if let error = model.error {
                        Text(error).foregroundStyle(.red)
                    } else {
                        Label("Connected to the server", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                    }
                }
            }
            .navigationTitle("Settings")
        }
    }
}

import SwiftUI

struct SettingsView: View {
    @ObservedObject private var api = CumulousAPI.shared
    @State private var draft = ""
    @State private var pingResult: String?
    @State private var autoLockSeconds: Int = 60

    var body: some View {
        ZStack {
            CumulousTheme.bg.ignoresSafeArea()
            Form {
                Section {
                    TextField("http://192.168.1.x:8765", text: $draft)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    Button("Save & Test") {
                        api.setBaseURL(draft)
                        Task {
                            let ok = await api.ping()
                            pingResult = ok ? "Connected" : (api.lastError ?? "Unreachable")
                        }
                    }
                    if let pingResult {
                        Text(pingResult == "Connected" ? "Connected" : "Can’t reach Mac Mini right now")
                            .foregroundStyle(pingResult == "Connected" ? CumulousTheme.success : CumulousTheme.amber)
                    }
                } header: {
                    Text("Mac Mini API")
                } footer: {
                    Text("Photos load inside Cumulous from this address. Same Wi‑Fi as the Mac, or Tailscale for cellular.")
                }

                Section("Install preference") {
                    Text("Home Screen icon (Web Clip) or full app when IPA is installed via USB/Xcode.")
                        .font(.footnote)
                        .foregroundStyle(CumulousTheme.muted)
                }

                Section {
                    Picker("Your usual Auto-Lock", selection: $autoLockSeconds) {
                        Text("30 Seconds").tag(30)
                        Text("1 Minute").tag(60)
                        Text("2 Minutes").tag(120)
                        Text("3 Minutes").tag(180)
                        Text("4 Minutes").tag(240)
                        Text("5 Minutes").tag(300)
                        Text("Never").tag(0)
                    }
                    .onChange(of: autoLockSeconds) { newVal in
                        BackupPowerManager.shared.setPriorAutoLockSeconds(newVal)
                    }
                    Button("Open Display Settings") {
                        BackupPowerManager.shared.openDisplaySettings()
                    }
                } header: {
                    Text("Auto-Lock (logged for restore)")
                } footer: {
                    Text("Apple blocks apps from changing system Auto-Lock. Log your usual setting; Cumulous pushes restore with this exact value when any backup ends, and restores in-app wake automatically.")
                }
            }
            .scrollContentBackground(.hidden)
        }
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            draft = api.baseURL
            autoLockSeconds = BackupPowerManager.shared.priorAutoLockSeconds() ?? 60
        }
        .preferredColorScheme(.dark)
    }
}

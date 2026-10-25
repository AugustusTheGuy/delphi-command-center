import SwiftUI

/// CardSession Settings hub — nests History, Status, Mac connection, Confirm.
struct SettingsHubView: View {
    var body: some View {
        NavigationStack {
            ZStack {
                CumulousTheme.bg.ignoresSafeArea()
                List {
                    Section {
                        NavigationLink {
                            SettingsView()
                        } label: {
                            Label("Mac Mini connection", systemImage: "desktopcomputer")
                        }
                        NavigationLink {
                            HistoryView()
                        } label: {
                            Label("Backup history", systemImage: "clock.arrow.circlepath")
                        }
                        NavigationLink {
                            DeviceStatusView()
                        } label: {
                            Label("Live device health", systemImage: "waveform.path.ecg")
                        }
                    } header: {
                        Text("Cumulous")
                    } footer: {
                        Text("Connection and history only. Confirm lives under Sessions; categories under Home; backup under Backup.")
                    }
                }
                .scrollContentBackground(.hidden)
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.large)
            .preferredColorScheme(.dark)
        }
    }
}

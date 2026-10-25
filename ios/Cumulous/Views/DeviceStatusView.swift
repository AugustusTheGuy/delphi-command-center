import SwiftUI

/// Extra Cumulous tab: device + backup health (beyond Photos).
struct DeviceStatusView: View {
    @ObservedObject private var api = CumulousAPI.shared
    @State private var harvestLine = "—"
    @State private var dualCount = 0
    @State private var freeable = 0
    @State private var keepAwake = false
    @State private var backupLine = "No full-system backup running"

    var body: some View {
        NavigationStack {
            ZStack {
                CumulousTheme.bg.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 14) {
                        CumulousCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("This iPhone")
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(CumulousTheme.muted)
                                Text(UIDevice.current.name)
                                    .font(.system(size: 20, weight: .semibold))
                                    .tracking(-0.4)
                                    .foregroundStyle(CumulousTheme.text)
                                SoftChip(text: api.online ? "Linked to Mac Mini" : "Mac offline", ok: api.online)
                            }
                        }
                        HStack(spacing: 12) {
                            metric("Dual photos", "\(dualCount)")
                            metric("Freeable", "\(freeable)")
                        }
                        CumulousCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("Photo backup")
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(CumulousTheme.muted)
                                Text(harvestLine)
                                    .font(.system(size: 15))
                                    .foregroundStyle(CumulousTheme.text)
                                if keepAwake {
                                    SoftChip(text: "Screen stay-awake on", ok: true)
                                }
                            }
                        }
                        CumulousCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("Full system")
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(CumulousTheme.muted)
                                Text(backupLine)
                                    .font(.system(size: 15))
                                    .foregroundStyle(CumulousTheme.text)
                            }
                        }
                    }
                    .padding(20)
                }
            }
            .navigationTitle("Status")
            .navigationBarTitleDisplayMode(.large)
            .task { await reload() }
            .refreshable { await reload() }
            .preferredColorScheme(.dark)
        }
    }

    private func metric(_ t: String, _ v: String) -> some View {
        CumulousCard {
            VStack(alignment: .leading, spacing: 4) {
                Text(t.uppercased())
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(CumulousTheme.muted)
                Text(v)
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(CumulousTheme.text)
            }
        }
    }

    private func reload() async {
        _ = await api.ping()
        if let url = URL(string: "\(api.baseURL)/photos/harvest-progress"),
           let (data, _) = try? await URLSession.shared.data(from: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            harvestLine = obj["status_line"] as? String ?? "—"
            if let lib = obj["library"] as? [String: Any] {
                dualCount = lib["dual_mirrored"] as? Int ?? dualCount
            }
            if let power = obj["power"] as? [String: Any] {
                keepAwake = power["keep_awake"] as? Bool ?? false
            }
            await BackupPowerManager.shared.apply(from: [
                "active": obj["active"] as? Bool ?? false,
                "status": obj["status"] as? String ?? "",
                "power": obj["power"] as? [String: Any] ?? [:],
            ], apiBase: api.baseURL)
        }
        if let url = URL(string: "\(api.baseURL)/photos/mirror-report"),
           let (data, _) = try? await URLSession.shared.data(from: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            dualCount = obj["dual_mirrored"] as? Int ?? dualCount
            freeable = obj["deletion_queue_pending"] as? Int ?? freeable
        }
        if let url = URL(string: "\(api.baseURL)/backup/progress"),
           let (data, _) = try? await URLSession.shared.data(from: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if (obj["active"] as? Bool) == true {
                backupLine = obj["status_line"] as? String ?? "Backup running"
            } else if (obj["status"] as? String) == "complete" {
                backupLine = "Last full backup complete"
            }
        }
    }
}

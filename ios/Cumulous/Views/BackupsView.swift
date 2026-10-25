import SwiftUI

struct BackupsView: View {
    @ObservedObject private var api = CumulousAPI.shared
    @State private var dualCount = 0
    @State private var pendingDelete = 0
    @State private var libraryRoot = ""

    var body: some View {
        ZStack {
            CumulousTheme.bg.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 16) {
                    CumulousCard {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Vault")
                                .font(.system(size: 17, weight: .semibold))
                                .tracking(-0.3)
                                .foregroundStyle(CumulousTheme.text)
                            Text("Photos dual-mirror to the Mac Mini. Unplug anytime — backup continues on Wi‑Fi.")
                                .font(.system(size: 14))
                                .foregroundStyle(CumulousTheme.muted)
                            SoftChip(text: "Unplug-safe", ok: true)
                        }
                    }
                    HStack(spacing: 12) {
                        stat("Dual mirror", "\(dualCount)")
                        stat("Free-ready", "\(pendingDelete)")
                    }
                    CumulousCard {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Vault path")
                                .font(.system(size: 12, weight: .semibold))
                                .foregroundStyle(CumulousTheme.muted)
                            if !libraryRoot.isEmpty {
                                Text(libraryRoot)
                                    .font(.caption2)
                                    .foregroundStyle(CumulousTheme.muted)
                            } else {
                                Text("Path loads from Mac Mini when online.")
                                    .font(.caption)
                                    .foregroundStyle(CumulousTheme.muted)
                            }
                        }
                    }
                }
                .padding(20)
            }
        }
        .navigationTitle("Backups")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .preferredColorScheme(.dark)
    }

    private func stat(_ t: String, _ v: String) -> some View {
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

    private func load() async {
        _ = await api.ping()
        guard let url = URL(string: "\(api.baseURL)/photos/mirror-report") else { return }
        guard let (data, _) = try? await URLSession.shared.data(from: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        dualCount = obj["dual_mirrored"] as? Int ?? 0
        pendingDelete = obj["deletion_queue_pending"] as? Int ?? 0
        if let prefs = obj["prefs"] as? [String: Any] { _ = prefs }
        if let lib = obj["hdd_library"] as? String { libraryRoot = lib }
        else if let status = try? await api.fetchAlbums() {
            dualCount = status.first(where: { $0.id == "dual_mirror" })?.count ?? dualCount
        }
    }
}

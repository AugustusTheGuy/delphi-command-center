import SwiftUI

/// CardSession “History” — backup generations / vault activity.
struct HistoryView: View {
    @ObservedObject private var api = CumulousAPI.shared
    @State private var lines: [String] = []
    @State private var dual = 0
    @State private var harvest = ""

    var body: some View {
        NavigationStack {
            ZStack {
                CumulousTheme.bg.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 14) {
                        CumulousCard {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Backup History")
                                    .font(.system(size: 20, weight: .semibold))
                                    .foregroundStyle(CumulousTheme.text)
                                Text("Dual-mirrored photos and system vault generations on your Mac Mini.")
                                    .font(.footnote)
                                    .foregroundStyle(CumulousTheme.muted)
                                SoftChip(text: "\(dual) dual photos", ok: dual > 0)
                            }
                        }
                        if !harvest.isEmpty {
                            CumulousCard {
                                Text(harvest)
                                    .font(.system(size: 14))
                                    .foregroundStyle(CumulousTheme.text)
                            }
                        }
                        if lines.isEmpty {
                            CumulousCard {
                                Text("No detailed generation list from API yet. Open Backups on Mac for full catalog, or pull-to-refresh.")
                                    .foregroundStyle(CumulousTheme.muted)
                            }
                        } else {
                            ForEach(lines, id: \.self) { line in
                                CumulousCard {
                                    Text(line)
                                        .font(.system(size: 14))
                                        .foregroundStyle(CumulousTheme.text)
                                }
                            }
                        }
                    }
                    .padding(20)
                }
            }
            .navigationTitle("History")
            .navigationBarTitleDisplayMode(.large)
            .task { await load() }
            .refreshable { await load() }
            .preferredColorScheme(.dark)
        }
    }

    private func load() async {
        _ = await api.ping()
        if let url = URL(string: "\(api.baseURL)/photos/mirror-report"),
           let (data, _) = try? await URLSession.shared.data(from: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            dual = obj["dual_mirrored"] as? Int ?? 0
            let files = obj["file_count"] as? Int ?? 0
            lines = [
                "HDD library files: \(files)",
                "Dual-mirrored: \(dual)",
                "Freeable queue: \(obj["deletion_queue_pending"] as? Int ?? 0)",
            ]
        }
        if let url = URL(string: "\(api.baseURL)/photos/harvest-progress"),
           let (data, _) = try? await URLSession.shared.data(from: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            harvest = obj["status_line"] as? String ?? ""
            if let h = obj["harvest"] as? [String: Any] {
                let scanned = h["scanned"] as? Int ?? 0
                let mirrored = h["mirrored"] as? Int ?? 0
                let skip = h["skipped_existing"] as? Int ?? 0
                lines.append("Last harvest · scanned \(scanned) · new \(mirrored) · skipped \(skip)")
            }
        }
        if let url = URL(string: "\(api.baseURL)/backup/categories"),
           let (data, _) = try? await URLSession.shared.data(from: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let sum = obj["summary"] as? [String: Any] {
            let v = sum["categories_verified"] as? Int ?? 0
            let t = sum["categories_total"] as? Int ?? 0
            lines.append("Categories verified: \(v)/\(t)")
        }
    }
}

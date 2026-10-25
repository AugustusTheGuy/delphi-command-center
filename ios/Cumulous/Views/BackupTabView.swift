import SwiftUI

/// Backup tab — selective checkbox tree + green backup / sky-blue restore buttons.
struct BackupTabView: View {
    @ObservedObject private var api = CumulousAPI.shared
    @State private var categories: [SelectableNodeDTO] = []
    @State private var apps: [SelectableNodeDTO] = []
    @State private var selected: Set<String> = ["photos_videos", "music"]
    @State private var expanded: Set<String> = []
    @State private var statusLine = ""
    @State private var busy = false
    @State private var showOptimize = false
    @State private var showRestoreAllConfirm = false
    @State private var optimizePlan = ""
    @State private var dualCount = 0
    @State private var destination = "DelphiBEAR Nextcloud + Mac HDD (dual)"

    private var hasSelection: Bool { !selected.isEmpty }

    var body: some View {
        NavigationStack {
            ZStack {
                CumulousTheme.bg.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 16) {
                        // —— Green backup row ——
                        HStack(spacing: 10) {
                            Button {
                                Task { await runBackupSelected() }
                            } label: {
                                Text(busy ? "Working…" : "Backup Selected Items")
                                    .multilineTextAlignment(.center)
                                    .lineLimit(2)
                                    .minimumScaleFactor(0.8)
                            }
                            .buttonStyle(BackupGreenButtonStyle())
                            .disabled(busy || !hasSelection || !api.online)

                            Button {
                                Task { await runBackupAll() }
                            } label: {
                                Text(busy ? "Working…" : "Backup All Device Data")
                                    .multilineTextAlignment(.center)
                                    .lineLimit(2)
                                    .minimumScaleFactor(0.8)
                            }
                            .buttonStyle(BackupGreenButtonStyle())
                            .disabled(busy || !api.online)
                        }

                        // —— Sky blue restore row (directly under greens) ——
                        HStack(spacing: 10) {
                            Button {
                                Task { await runRestoreSelected() }
                            } label: {
                                Text(busy ? "Working…" : "Restore Selected Data")
                                    .multilineTextAlignment(.center)
                                    .lineLimit(2)
                                    .minimumScaleFactor(0.8)
                            }
                            .buttonStyle(RestoreSkyBlueButtonStyle())
                            .disabled(busy || !hasSelection || !api.online)

                            Button {
                                showRestoreAllConfirm = true
                            } label: {
                                Text(busy ? "Working…" : "Restore All Device Data")
                                    .multilineTextAlignment(.center)
                                    .lineLimit(2)
                                    .minimumScaleFactor(0.8)
                            }
                            .buttonStyle(RestoreSkyBlueButtonStyle())
                            .disabled(busy || !api.online)
                        }

                        if !statusLine.isEmpty {
                            Text(statusLine)
                                .font(.footnote)
                                .foregroundStyle(CumulousTheme.muted)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }

                        CumulousCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("WHAT TO BACK UP / RESTORE")
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(CumulousTheme.faint)
                                    .tracking(0.8)
                                Text("Check categories or apps. Use any combination.")
                                    .font(.caption)
                                    .foregroundStyle(CumulousTheme.muted)

                                ForEach(categories) { cat in
                                    nodeBlock(cat)
                                }

                                if !apps.isEmpty {
                                    Text("APPS")
                                        .font(.system(size: 11, weight: .semibold))
                                        .foregroundStyle(CumulousTheme.faint)
                                        .tracking(0.8)
                                        .padding(.top, 8)
                                    ForEach(apps) { app in
                                        nodeBlock(app)
                                    }
                                }

                                if categories.isEmpty {
                                    Text("Loading categories…")
                                        .foregroundStyle(CumulousTheme.muted)
                                }
                            }
                        }

                        CumulousCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("DESTINATION")
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(CumulousTheme.faint)
                                    .tracking(0.8)
                                Text(destination)
                                    .font(.system(size: 16, weight: .semibold))
                                    .foregroundStyle(CumulousTheme.text)
                                SoftChip(text: "End-to-end path · dual-mirror media", ok: true)
                                Text("Self-hosted · Tailscale / LAN · Dual photos in vault: \(dualCount)")
                                    .font(.footnote)
                                    .foregroundStyle(CumulousTheme.muted)
                            }
                        }

                    }
                    .padding(20)
                }
            }
            .navigationTitle("Backup")
            .navigationBarTitleDisplayMode(.large)
            .task { await load() }
            .refreshable { await load() }
            .alert("Restore everything?", isPresented: $showRestoreAllConfirm) {
                Button("Cancel", role: .cancel) {}
                Button("Yes — stage full restore on Mac") {
                    Task { await runRestoreAll() }
                }
            } message: {
                Text("This prepares a full restore package on your Mac from the Cumulous vault. Vault copies stay safe. Confirm to continue.")
            }
            .alert("Free space before backup?", isPresented: $showOptimize) {
                Button("Yes — free safe space first") {
                    Task { await runOptimize(yes: true) }
                }
                Button("No — just back up", role: .cancel) {
                    Task { await runOptimize(yes: false) }
                }
            } message: {
                Text(optimizePlan.isEmpty
                     ? "Dual-backed-up photos only. Vault on Mac is never deleted."
                     : optimizePlan)
            }
            .preferredColorScheme(.dark)
        }
    }

    @ViewBuilder
    private func nodeBlock(_ node: SelectableNodeDTO) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            checkboxRow(
                id: node.id,
                title: node.title,
                sizeLabel: node.sizeLabel,
                subtitle: node.verified == true ? "Verified in vault" : "Pending full capture",
                isChild: false
            )
            lineActions(id: node.id, title: node.title)
            if !node.children.isEmpty {
                ForEach(node.children) { child in
                    checkboxRow(
                        id: child.id,
                        title: child.title,
                        sizeLabel: child.sizeLabel,
                        subtitle: child.hint,
                        isChild: true
                    )
                    lineActions(id: child.id, title: child.title)
                        .padding(.leading, 22)
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func checkboxRow(id: String, title: String, sizeLabel: String, subtitle: String, isChild: Bool) -> some View {
        let on = selected.contains(id)
        return Button {
            if on {
                selected.remove(id)
            } else {
                selected.insert(id)
            }
        } label: {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: on ? "checkmark.square.fill" : "square")
                    .foregroundStyle(on ? CumulousTheme.backupGreen : CumulousTheme.muted)
                    .font(.system(size: isChild ? 16 : 18))
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        Text(title)
                            .font(.system(size: isChild ? 14 : 16, weight: isChild ? .regular : .semibold))
                            .foregroundStyle(CumulousTheme.text)
                        Text(sizeLabel)
                            .font(.system(size: isChild ? 12 : 13, weight: .medium))
                            .foregroundStyle(CumulousTheme.muted)
                    }
                    if !subtitle.isEmpty {
                        Text(subtitle)
                            .font(.caption)
                            .foregroundStyle(CumulousTheme.muted)
                            .lineLimit(2)
                    }
                }
                Spacer()
            }
            .padding(.leading, isChild ? 22 : 0)
            .padding(.vertical, 4)
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private func lineActions(id: String, title: String) -> some View {
        HStack(spacing: 6) {
            Button {
                Task { await runBackupIds([id], label: title) }
            } label: {
                Text(busy ? "…" : "Backup")
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
            }
            .buttonStyle(.plain)
            .background(RoundedRectangle(cornerRadius: 10).fill(CumulousTheme.accent))
            .foregroundStyle(.white)
            .disabled(busy || !api.online)

            Button {
                Task { await runRestoreIds([id], label: title) }
            } label: {
                Text(busy ? "…" : "Restore")
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
            }
            .buttonStyle(.plain)
            .background(RoundedRectangle(cornerRadius: 10).fill(CumulousTheme.accent))
            .foregroundStyle(.white)
            .disabled(busy || !api.online)

            Button {
                Task { await runDeviceDelete(id: id, label: title) }
            } label: {
                Text(busy ? "…" : "Device Delete")
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
            }
            .buttonStyle(.plain)
            .background(RoundedRectangle(cornerRadius: 10).fill(CumulousTheme.accent))
            .foregroundStyle(.white)
            .disabled(busy || !api.online)
        }
    }

    private func runDeviceDelete(id: String, label: String) async {
        busy = true
        defer { busy = false }
        let catId = id.split(separator: ".").first.map(String.init) ?? id
        let obj = await postJSON(path: "/backup/categories/free", body: [
            "category_id": catId,
            "source": "ios",
        ])
        statusLine = obj?["message"] as? String
            ?? ((obj?["ok"] as? Bool == true)
                ? "Device Delete · vault kept (\(label))"
                : "Device Delete failed — USB may be required")
    }

    private func load() async {
        _ = await api.ping()
        if let url = URL(string: "\(api.baseURL)/backup/selectable"),
           let (data, _) = try? await URLSession.shared.data(from: url),
           let rep = try? JSONDecoder().decode(SelectableCatalogDTO.self, from: data) {
            categories = rep.categories
            apps = rep.apps
            if let saved = rep.saved_ids, !saved.isEmpty {
                selected = Set(saved)
            } else if let defs = rep.default_ids, !defs.isEmpty {
                selected = Set(defs)
            }
        } else if let url = URL(string: "\(api.baseURL)/backup/categories"),
                  let (data, _) = try? await URLSession.shared.data(from: url),
                  let rep = try? JSONDecoder().decode(BackupCategoriesReport.self, from: data) {
            categories = rep.categories.map { cat in
                SelectableNodeDTO(
                    id: cat.id,
                    title: cat.title,
                    verified: cat.verified,
                    sizeLabel: cat.sizeLabel,
                    children: cat.subcategories.map {
                        SelectableChildDTO(
                            id: "\(cat.id).\($0.id)",
                            title: $0.title,
                            hint: $0.detail,
                            sizeLabel: $0.sizeLabel
                        )
                    }
                )
            }
            selected = Set(rep.categories.map(\.id))
        }
        if let url = URL(string: "\(api.baseURL)/photos/mirror-report"),
           let (data, _) = try? await URLSession.shared.data(from: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            dualCount = obj["dual_mirrored"] as? Int ?? 0
        }
    }

    private func postJSON(path: String, body: [String: Any]) async -> [String: Any]? {
        guard let url = URL(string: "\(api.baseURL)\(path)") else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        guard let (data, _) = try? await URLSession.shared.data(for: req),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        return obj
    }

    private func runBackupSelected() async {
        await runBackupIds(Array(selected), label: "selection")
    }

    private func runBackupIds(_ ids: [String], label: String) async {
        busy = true
        defer { busy = false }
        let obj = await postJSON(path: "/backup/selected", body: [
            "ids": ids,
            "background": true,
        ])
        statusLine = obj?["message"] as? String
            ?? ((obj?["ok"] as? Bool == true) ? "Backup started for \(label)." : "Couldn’t start backup.")
    }

    private func runBackupAll() async {
        // Keep optimize prompt for full backup
        busy = true
        defer { busy = false }
        if let url = URL(string: "\(api.baseURL)/storage/optimize/backup-gate") {
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: [
                "source": "ios", "mode": "balanced", "execute": false,
            ])
            if let (data, _) = try? await URLSession.shared.data(for: req),
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                if let plan = obj["plan"] as? [String: Any] {
                    let mb = plan["projected_mb"] as? Double ?? Double(plan["projected_mb"] as? Int ?? 0)
                    let n = plan["selected_count"] as? Int ?? 0
                    optimizePlan = "About \(Int(mb)) MB freeable (\(n) items). Vault stays on Mac."
                } else {
                    optimizePlan = obj["message"] as? String ?? ""
                }
            }
        }
        showOptimize = true
    }

    private func runOptimize(yes: Bool) async {
        busy = true
        defer { busy = false }
        if yes, let url = URL(string: "\(api.baseURL)/storage/optimize/backup-gate") {
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: [
                "source": "ios", "mode": "balanced",
                "user_wants_optimize": true, "execute": true,
            ])
            _ = try? await URLSession.shared.data(for: req)
        }
        let obj = await postJSON(path: "/backup/all", body: ["background": true])
        statusLine = obj?["message"] as? String
            ?? ((obj?["ok"] as? Bool == true) ? "Full device backup started." : "Couldn’t start full backup.")
    }

    private func runRestoreSelected() async {
        await runRestoreIds(Array(selected), label: "selection")
    }

    private func runRestoreIds(_ ids: [String], label: String) async {
        busy = true
        defer { busy = false }
        let obj = await postJSON(path: "/restore/selected", body: [
            "ids": ids,
        ])
        statusLine = obj?["message"] as? String
            ?? ((obj?["ok"] as? Bool == true) ? "Restore staged on Mac for \(label)." : "Couldn’t restore.")
    }

    private func runRestoreAll() async {
        busy = true
        defer { busy = false }
        let obj = await postJSON(path: "/restore/all", body: [
            "confirm": true,
        ])
        statusLine = obj?["message"] as? String
            ?? ((obj?["ok"] as? Bool == true) ? "Full restore staged on Mac." : "Couldn’t stage full restore.")
    }
}

// MARK: - Selectable catalog DTOs

struct SelectableCatalogDTO: Decodable {
    var categories: [SelectableNodeDTO]
    var apps: [SelectableNodeDTO]
    var default_ids: [String]?
    var saved_ids: [String]?
}

struct SelectableNodeDTO: Decodable, Identifiable {
    var id: String
    var title: String
    var verified: Bool?
    var sizeLabel: String
    var children: [SelectableChildDTO]

    init(
        id: String,
        title: String,
        verified: Bool? = nil,
        sizeLabel: String = "—",
        children: [SelectableChildDTO] = []
    ) {
        self.id = id
        self.title = title
        self.verified = verified
        self.sizeLabel = sizeLabel
        self.children = children
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        verified = try c.decodeIfPresent(Bool.self, forKey: .verified)
        sizeLabel = try c.decodeIfPresent(String.self, forKey: .sizeLabel) ?? "—"
        children = try c.decodeIfPresent([SelectableChildDTO].self, forKey: .children) ?? []
    }

    enum CodingKeys: String, CodingKey {
        case id, title, verified, children
        case sizeLabel = "size_label"
    }
}

struct SelectableChildDTO: Decodable, Identifiable {
    var id: String
    var title: String
    var hint: String
    var sizeLabel: String

    init(id: String, title: String, hint: String = "", sizeLabel: String = "—") {
        self.id = id
        self.title = title
        self.hint = hint
        self.sizeLabel = sizeLabel
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        hint = try c.decodeIfPresent(String.self, forKey: .hint) ?? ""
        sizeLabel = try c.decodeIfPresent(String.self, forKey: .sizeLabel) ?? "—"
    }

    enum CodingKeys: String, CodingKey {
        case id, title, hint
        case sizeLabel = "size_label"
    }
}

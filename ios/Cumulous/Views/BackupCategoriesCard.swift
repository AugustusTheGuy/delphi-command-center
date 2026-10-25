import SwiftUI

/// Verified backup categories — shown only on Home (not repeated on other tabs).
/// Each line: name · size · Backup / Restore (Apple blue).
struct BackupCategoriesCard: View {
    @State private var report: BackupCategoriesReport?
    @State private var busyId: String?
    @State private var statusLine = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Backed up")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(CumulousTheme.muted)
                .textCase(.uppercase)
                .tracking(0.6)
            if let report {
                Text(
                    "\(report.deviceName) · \(report.summary.categoriesVerified)/\(report.summary.categoriesTotal) categories"
                        + (report.summary.totalBackedUpLabel.map { " · \($0)" } ?? "")
                )
                .font(.system(size: 14))
                .foregroundStyle(CumulousTheme.muted)
                ForEach(report.categories) { cat in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(cat.verified ? "✓" : "·")
                                .foregroundStyle(cat.verified ? CumulousTheme.success : CumulousTheme.faint)
                                .fontWeight(.bold)
                            Text(cat.title)
                                .font(.system(size: 16, weight: .semibold))
                                .foregroundStyle(CumulousTheme.text)
                            Text("· \(cat.sizeLabel)")
                                .font(.system(size: 14, weight: .medium))
                                .foregroundStyle(CumulousTheme.muted)
                            Spacer()
                            Text("\(cat.subVerified)/\(cat.subTotal)")
                                .font(.caption)
                                .foregroundStyle(CumulousTheme.muted)
                        }
                        ForEach(cat.subcategories) { sub in
                            HStack(alignment: .top, spacing: 8) {
                                Text(sub.verified ? "✓" : "·")
                                    .foregroundStyle(sub.verified ? CumulousTheme.success : CumulousTheme.faint)
                                VStack(alignment: .leading, spacing: 2) {
                                    HStack(spacing: 6) {
                                        Text(sub.title)
                                            .font(.system(size: 13))
                                            .foregroundStyle(CumulousTheme.text)
                                        Text(sub.sizeLabel)
                                            .font(.system(size: 12, weight: .medium))
                                            .foregroundStyle(CumulousTheme.muted)
                                    }
                                    if !sub.detail.isEmpty {
                                        Text(sub.detail)
                                            .font(.system(size: 11))
                                            .foregroundStyle(CumulousTheme.faint)
                                            .lineLimit(2)
                                    }
                                }
                                Spacer(minLength: 4)
                            }
                            lineActions(
                                id: "\(cat.id).\(sub.id)",
                                title: sub.title
                            )
                        }
                        lineActions(id: cat.id, title: cat.title)
                        if cat.verified && cat.freeableOnDevice {
                            Button {
                                Task { await free(categoryId: cat.id) }
                            } label: {
                                Label(busyId == cat.id ? "…" : "Clear from phone", systemImage: "iphone.and.arrow.forward")
                                    .font(.system(size: 13, weight: .semibold))
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 10)
                            }
                            .buttonStyle(.plain)
                            .background(RoundedRectangle(cornerRadius: 12).fill(CumulousTheme.accent.opacity(0.18)))
                            .foregroundStyle(CumulousTheme.accent)
                            .disabled(busyId != nil)
                        }
                    }
                    .padding(14)
                    .background(
                        RoundedRectangle(cornerRadius: CumulousTheme.radiusCard, style: .continuous)
                            .fill(CumulousTheme.card)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: CumulousTheme.radiusCard, style: .continuous)
                            .stroke(CumulousTheme.cardStroke, lineWidth: 1)
                    )
                }
                if !statusLine.isEmpty {
                    Text(statusLine)
                        .font(.caption)
                        .foregroundStyle(CumulousTheme.muted)
                }
            } else {
                ProgressView().tint(.white)
            }
        }
        .task { await load() }
    }

    @ViewBuilder
    private func lineActions(id: String, title: String) -> some View {
        HStack(spacing: 6) {
            Button {
                Task { await backup(ids: [id], label: title) }
            } label: {
                Text(busyId == "bak-\(id)" ? "…" : "Backup")
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
            }
            .buttonStyle(.plain)
            .background(RoundedRectangle(cornerRadius: 10).fill(CumulousTheme.accent))
            .foregroundStyle(.white)
            .disabled(busyId != nil)

            Button {
                Task { await restore(ids: [id], label: title) }
            } label: {
                Text(busyId == "rst-\(id)" ? "…" : "Restore")
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
            }
            .buttonStyle(.plain)
            .background(RoundedRectangle(cornerRadius: 10).fill(CumulousTheme.accent))
            .foregroundStyle(.white)
            .disabled(busyId != nil)

            Button {
                Task { await deviceDelete(categoryId: id, label: title) }
            } label: {
                Text(busyId == "del-\(id)" ? "…" : "Device Delete")
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
            }
            .buttonStyle(.plain)
            .background(RoundedRectangle(cornerRadius: 10).fill(CumulousTheme.accent))
            .foregroundStyle(.white)
            .disabled(busyId != nil)
        }
    }

    private func deviceDelete(categoryId: String, label: String) async {
        busyId = "del-\(categoryId)"
        defer { busyId = nil }
        // Top-level id only for free endpoint (strip subcategory suffix if present)
        let catId = categoryId.split(separator: ".").first.map(String.init) ?? categoryId
        guard let url = URL(string: "\(CumulousAPI.shared.baseURL)/backup/categories/free") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "category_id": catId,
            "source": "ios",
        ])
        guard let (data, _) = try? await URLSession.shared.data(for: req),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            statusLine = "Device Delete failed — USB/Mac required"
            return
        }
        statusLine = (obj["message"] as? String)
            ?? ((obj["ok"] as? Bool == true) ? "Deleted from device · vault kept (\(label))" : "Couldn’t delete from device")
        await load()
    }

    private func load() async {
        guard let url = URL(string: "\(CumulousAPI.shared.baseURL)/backup/categories") else { return }
        guard let (data, _) = try? await URLSession.shared.data(from: url),
              let decoded = try? JSONDecoder().decode(BackupCategoriesReport.self, from: data) else { return }
        report = decoded
    }

    private func backup(ids: [String], label: String) async {
        let key = "bak-\(ids.first ?? label)"
        busyId = key
        defer { busyId = nil }
        guard let url = URL(string: "\(CumulousAPI.shared.baseURL)/backup/selected") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "ids": ids,
            "background": true,
        ])
        guard let (data, _) = try? await URLSession.shared.data(for: req),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            statusLine = "Couldn’t start backup — try again"
            return
        }
        statusLine = (obj["message"] as? String)
            ?? (obj["ok"] as? Bool == true ? "Backup started for \(label)" : "Couldn’t start backup")
    }

    private func restore(ids: [String], label: String) async {
        let key = "rst-\(ids.first ?? label)"
        busyId = key
        defer { busyId = nil }
        guard let url = URL(string: "\(CumulousAPI.shared.baseURL)/restore/selected") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["ids": ids])
        guard let (data, _) = try? await URLSession.shared.data(for: req),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            statusLine = "Couldn’t restore — try again"
            return
        }
        statusLine = (obj["message"] as? String) ?? "Restore staged on Mac for \(label)"
    }

    private func free(categoryId: String) async {
        busyId = categoryId
        defer { busyId = nil }
        guard let url = URL(string: "\(CumulousAPI.shared.baseURL)/backup/categories/free") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = ["category_id": categoryId, "source": "ios"]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        guard let (data, _) = try? await URLSession.shared.data(for: req),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            statusLine = "Couldn’t clear phone — try again"
            return
        }
        statusLine = (obj["message"] as? String) ?? (obj["ok"] as? Bool == true ? "Cleared from phone — vault kept" : "Couldn’t clear")
        await load()
    }
}

// MARK: - DTOs

struct BackupCategoriesReport: Decodable {
    let deviceName: String
    let summary: BackupCategoriesSummary
    let categories: [BackupCategoryDTO]

    enum CodingKeys: String, CodingKey {
        case deviceName = "device_name"
        case summary, categories
    }
}

struct BackupCategoriesSummary: Decodable {
    let categoriesVerified: Int
    let categoriesTotal: Int
    let subcategoriesVerified: Int
    let subcategoriesTotal: Int
    let photosDual: Int
    let totalBackedUpLabel: String?

    enum CodingKeys: String, CodingKey {
        case categoriesVerified = "categories_verified"
        case categoriesTotal = "categories_total"
        case subcategoriesVerified = "subcategories_verified"
        case subcategoriesTotal = "subcategories_total"
        case photosDual = "photos_dual"
        case totalBackedUpLabel = "total_backed_up_label"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        categoriesVerified = try c.decodeIfPresent(Int.self, forKey: .categoriesVerified) ?? 0
        categoriesTotal = try c.decodeIfPresent(Int.self, forKey: .categoriesTotal) ?? 0
        subcategoriesVerified = try c.decodeIfPresent(Int.self, forKey: .subcategoriesVerified) ?? 0
        subcategoriesTotal = try c.decodeIfPresent(Int.self, forKey: .subcategoriesTotal) ?? 0
        photosDual = try c.decodeIfPresent(Int.self, forKey: .photosDual) ?? 0
        totalBackedUpLabel = try c.decodeIfPresent(String.self, forKey: .totalBackedUpLabel)
    }
}

struct BackupCategoryDTO: Decodable, Identifiable {
    let id: String
    let title: String
    let verified: Bool
    let subVerified: Int
    let subTotal: Int
    let freeableOnDevice: Bool
    let sizeBytes: Int
    let sizeLabel: String
    let subcategories: [BackupSubcategoryDTO]

    enum CodingKeys: String, CodingKey {
        case id, title, verified
        case subVerified = "sub_verified"
        case subTotal = "sub_total"
        case freeableOnDevice = "freeable_on_device"
        case sizeBytes = "size_bytes"
        case sizeLabel = "size_label"
        case subcategories
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        verified = try c.decodeIfPresent(Bool.self, forKey: .verified) ?? false
        subVerified = try c.decodeIfPresent(Int.self, forKey: .subVerified) ?? 0
        subTotal = try c.decodeIfPresent(Int.self, forKey: .subTotal) ?? 0
        freeableOnDevice = try c.decodeIfPresent(Bool.self, forKey: .freeableOnDevice) ?? false
        sizeBytes = try c.decodeIfPresent(Int.self, forKey: .sizeBytes) ?? 0
        sizeLabel = try c.decodeIfPresent(String.self, forKey: .sizeLabel) ?? "—"
        subcategories = try c.decodeIfPresent([BackupSubcategoryDTO].self, forKey: .subcategories) ?? []
    }
}

struct BackupSubcategoryDTO: Decodable, Identifiable {
    let id: String
    let title: String
    let verified: Bool
    let detail: String
    let sizeBytes: Int
    let sizeLabel: String

    enum CodingKeys: String, CodingKey {
        case id, title, verified, detail
        case sizeBytes = "size_bytes"
        case sizeLabel = "size_label"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        verified = try c.decodeIfPresent(Bool.self, forKey: .verified) ?? false
        detail = try c.decodeIfPresent(String.self, forKey: .detail) ?? ""
        sizeBytes = try c.decodeIfPresent(Int.self, forKey: .sizeBytes) ?? 0
        sizeLabel = try c.decodeIfPresent(String.self, forKey: .sizeLabel) ?? "—"
    }
}

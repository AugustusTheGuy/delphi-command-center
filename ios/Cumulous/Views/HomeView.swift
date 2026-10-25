import SwiftUI
import UIKit

struct HomeView: View {
    @ObservedObject private var api = CumulousAPI.shared
    @State private var statusLine = "Connecting to Mac Mini…"
    @State private var storageLabel = "—"
    @State private var backupPct: Int? = nil
    @State private var backupLine = ""
    @State private var showCompletePush = false
    @State private var completeBody = ""

    var body: some View {
        NavigationStack {
            ZStack {
                CumulousTheme.bg.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 20) {
                        if let pct = backupPct {
                            backupBanner(pct: pct, line: backupLine)
                        }
                        header
                        metrics
                        statusCard
                        // Category status lives only on Home (not Library / Backup / Settings)
                        BackupCategoriesCard()
                        Text("Unplug-safe · continues on Wi‑Fi")
                            .font(.system(size: 12))
                            .foregroundStyle(CumulousTheme.faint)
                            .multilineTextAlignment(.center)
                            .padding(.top, 6)
                    }
                    .padding(24)
                }
                if showCompletePush {
                    completePushOverlay
                }
            }
            .navigationBarHidden(true)
            .task {
                await refresh()
                await pollBackupLoop()
            }
            .refreshable { await refresh() }
        }
    }

    private func backupBanner(pct: Int, line: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Backup")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(CumulousTheme.faint)
                Spacer()
                Text("\(pct)%")
                    .font(.system(size: 15, weight: .semibold, design: .rounded))
                    .foregroundStyle(CumulousTheme.text)
                    .tracking(-0.3)
            }
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.white.opacity(0.08))
                    Capsule()
                        .fill(
                            LinearGradient(
                                colors: [
                                    Color(red: 0.039, green: 0.518, blue: 1.0), // #0A84FF
                                    CumulousTheme.accent, // #007AFF
                                ],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(width: max(8, g.size.width * CGFloat(pct) / 100.0))
                        .shadow(color: CumulousTheme.accent.opacity(0.45), radius: 6, y: 0)
                }
            }
            .frame(height: 10)
            Text(line)
                .font(.system(size: 12))
                .foregroundStyle(CumulousTheme.muted)
                .lineLimit(2)
            SoftChip(text: "Unplug anytime · continues on Wi‑Fi", ok: true)
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: CumulousTheme.radiusCard, style: .continuous).fill(CumulousTheme.card))
        .overlay(RoundedRectangle(cornerRadius: CumulousTheme.radiusCard, style: .continuous).stroke(CumulousTheme.cardStroke, lineWidth: 1))
    }

    private var completePushOverlay: some View {
        ZStack {
            Color.black.opacity(0.55).ignoresSafeArea().onTapGesture {
                showCompletePush = false
            }
            VStack(spacing: 12) {
                HStack {
                    Button { showCompletePush = false } label: {
                        Circle()
                            .fill(Color(red: 1.0, green: 0.37, blue: 0.34))
                            .frame(width: 14, height: 14)
                    }
                    .buttonStyle(.plain)
                    Spacer()
                }
                Text("Cumulous Backup Complete")
                    .font(.headline)
                    .foregroundStyle(.white)
                Text(completeBody)
                    .font(.subheadline)
                    .foregroundStyle(CumulousTheme.muted)
                    .multilineTextAlignment(.center)
            }
            .padding(22)
            .frame(maxWidth: 320)
            .background(RoundedRectangle(cornerRadius: 22).fill(Color(white: 0.12)))
        }
    }

    private func pollBackupLoop() async {
        while !Task.isCancelled {
            await fetchBackupProgress()
            try? await Task.sleep(nanoseconds: 3_000_000_000)
        }
    }

    private func fetchBackupProgress() async {
        // Full-system progress
        guard let url = URL(string: "\(api.baseURL)/backup/progress") else { return }
        guard let (data, _) = try? await URLSession.shared.data(from: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            await applyHarvestKeepAwake()
            return
        }
        let active = obj["active"] as? Bool ?? false
        let status = obj["status"] as? String ?? ""
        let rawPct = obj["percent_int"] as? Int
            ?? Int(obj["percent"] as? Double ?? 0)
        let high = obj["high_water_percent"] as? Double
        let floored = BackupPowerManager.shared.floorPercent(
            max(rawPct, Int(high ?? 0), backupPct ?? 0)
        )
        // Photo harvest also keeps screen awake (no auto-dim while Cumulous open)
        if let harvestPayload = await fetchHarvestPowerPayload() {
            var merged = obj
            if let p = harvestPayload["power"] as? [String: Any],
               (p["keep_awake"] as? Bool) == true {
                merged["power"] = p
                merged["active"] = true
            }
            if let line = harvestPayload["status_line"] as? String,
               (harvestPayload["active"] as? Bool) == true {
                statusLine = line
            }
            await BackupPowerManager.shared.apply(from: merged, apiBase: api.baseURL)
        } else {
            await BackupPowerManager.shared.apply(from: obj, apiBase: api.baseURL)
        }
        let inFlight = active
            || status == "waiting_passcode"
            || status == "needs_resume"
            || status == "handoff"
            || status == "awaiting_network"
        if inFlight {
            // Never snap to 0% on lock / stalled poll — only climb or hold
            backupPct = max(floored, backupPct ?? 0)
            backupLine = obj["status_line"] as? String ?? backupLine
        } else if status == "complete" {
            if backupPct != nil {
                showCompletePush = true
                completeBody = obj["label"] as? String ?? "Full system backup finished"
            }
            BackupPowerManager.shared.resetPercentFloor()
            backupPct = nil
        } else {
            backupPct = nil
        }
    }

    /// Keep-awake during photo dual-mirror harvest (not only full system backup).
    private func fetchHarvestPowerPayload() async -> [String: Any]? {
        guard let url = URL(string: "\(api.baseURL)/photos/harvest-progress") else { return nil }
        guard let (data, _) = try? await URLSession.shared.data(from: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return obj
    }

    private func applyHarvestKeepAwake() async {
        guard let payload = await fetchHarvestPowerPayload() else { return }
        var synthetic: [String: Any] = [
            "active": payload["active"] as? Bool ?? false,
            "status": payload["status"] as? String ?? "idle",
            "power": payload["power"] as? [String: Any] ?? [:],
        ]
        if let line = payload["status_line"] as? String, (payload["active"] as? Bool) == true {
            statusLine = line
            synthetic["active"] = true
        }
        await BackupPowerManager.shared.apply(from: synthetic, apiBase: api.baseURL)
    }

    private var header: some View {
        VStack(spacing: 6) {
            Text("Cumulous")
                .font(.system(size: 32, weight: .semibold))
                .tracking(-0.8)
                .foregroundStyle(CumulousTheme.text)
            Text("Private backup · by device")
                .font(.system(size: 14, weight: .regular))
                .foregroundStyle(CumulousTheme.muted)
        }
        .padding(.top, 14)
    }

    private var metrics: some View {
        // Status indicators with colons + traffic-light glow (affirmed green / unaffirmed red)
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                StatusMetricTile(
                    label: "Storage:",
                    value: api.online ? storageLabel : "Offline",
                    affirmed: api.online && storageLabel != "—"
                )
                StatusMetricTile(
                    label: "Vault:",
                    value: api.online ? "Ready" : "—",
                    affirmed: api.online
                )
            }
            HStack(spacing: 10) {
                StatusMetricTile(
                    label: "Apple ID:",
                    value: api.online ? "Linked" : "None",
                    affirmed: api.online
                )
                StatusMetricTile(
                    label: "CEO gate:",
                    value: api.online ? "Ready" : "Setup",
                    affirmed: api.online
                )
            }
        }
    }

    private var statusCard: some View {
        HStack(spacing: 12) {
            Circle()
                .fill(api.online ? CumulousTheme.statusGreen : CumulousTheme.statusRed)
                .frame(width: 7, height: 7)
                .shadow(
                    color: (api.online ? CumulousTheme.statusGreenBright : CumulousTheme.statusRed)
                        .opacity(api.online ? 0.9 : 0.55),
                    radius: api.online ? 8 : 5
                )
            Text(statusLine)
                .font(.system(size: 15, weight: .medium))
                .tracking(-0.2)
                .foregroundStyle(CumulousTheme.text)
            Spacer()
            SoftChip(
                text: api.online ? "Live" : "No Connection",
                ok: api.online,
                liveConnection: true
            )
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: CumulousTheme.radiusCard, style: .continuous).fill(CumulousTheme.card))
        .overlay(RoundedRectangle(cornerRadius: CumulousTheme.radiusCard, style: .continuous).stroke(CumulousTheme.cardStroke, lineWidth: 1))
    }

    private func refresh() async {
        let ok = await api.ping()
        statusLine = ok ? "Connected to Mac Mini vault" : "Waiting for Mac Mini (Wi‑Fi / Tailscale)"
        if ok {
            if let albums = try? await api.fetchAlbums() {
                let n = albums.first(where: { $0.id == "recents" })?.count ?? albums.first?.count ?? 0
                storageLabel = "\(n)"
            }
            await fetchBackupProgress()
        } else {
            storageLabel = "—"
        }
    }
}

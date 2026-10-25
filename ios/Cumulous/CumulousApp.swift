import SwiftUI
import UIKit

@main
struct CumulousApp: App {
    @StateObject private var api = CumulousAPI.shared
    @State private var showSplash = true
    @State private var appVersion = "0.2.0"

    var body: some Scene {
        WindowGroup {
            ZStack {
                RootTabView()
                    .environmentObject(api)
                    .preferredColorScheme(.dark)
                    .opacity(showSplash ? 0 : 1)
                if showSplash {
                    DelphiSplashView(version: appVersion) {
                        showSplash = false
                    }
                    .transition(.opacity)
                    .zIndex(10)
                }
            }
            .task {
                // Always-latest version + persistent device install registration
                let deviceId = UIDevice.current.identifierForVendor?.uuidString
                    ?? UserDefaults.standard.string(forKey: "cumulous_device_id")
                    ?? UUID().uuidString
                UserDefaults.standard.set(deviceId, forKey: "cumulous_device_id")
                var versionURL = "\(api.baseURL)/app/version.json?device_id=\(deviceId)&platform=ios_native"
                if let url = URL(string: versionURL),
                   let (data, _) = try? await URLSession.shared.data(from: url),
                   let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let v = obj["version"] as? String {
                    appVersion = v
                    UserDefaults.standard.set(v, forKey: "cumulous_last_version")
                }
                // Explicit register so Mac tracks this install even if version GET is cached
                if let reg = URL(string: "\(api.baseURL)/install/register") {
                    var req = URLRequest(url: reg)
                    req.httpMethod = "POST"
                    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    let body: [String: Any] = [
                        "device_id": deviceId,
                        "version": appVersion,
                        "platform": "ios_native",
                        "source": "app_launch",
                        "display_name": UIDevice.current.name,
                    ]
                    req.httpBody = try? JSONSerialization.data(withJSONObject: body)
                    _ = try? await URLSession.shared.data(for: req)
                }
                _ = await api.ping()
            }
        }
    }
}

/// CardSession 5-tab shell + Photos Library:
/// Home · Library · Backup · Sessions · Settings
struct RootTabView: View {
    @State private var tab = 1 // Library first (Photos-app-like)
    @State private var topBackupPct: Int? = nil
    @State private var topBackupLine = ""
    @ObservedObject private var api = CumulousAPI.shared

    var body: some View {
        VStack(spacing: 0) {
            // Global top banner during backup / harvest (any tab except Home which has its own)
            if tab != 0, let pct = topBackupPct {
                VStack(alignment: .leading, spacing: 7) {
                    HStack {
                        Text("Backup")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(Color.white.opacity(0.45))
                        Spacer()
                        Text("\(pct)%")
                            .font(.system(size: 13, weight: .semibold, design: .rounded))
                            .foregroundStyle(.white)
                    }
                    ProgressView(value: Double(pct), total: 100)
                        .tint(CumulousTheme.accent)
                    Text(topBackupLine)
                        .font(.system(size: 11))
                        .foregroundStyle(Color.white.opacity(0.5))
                        .lineLimit(2)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 11)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.black.opacity(0.92))
                .overlay(Rectangle().frame(height: 0.5).foregroundStyle(Color.white.opacity(0.08)), alignment: .bottom)
            }
            TabView(selection: $tab) {
                HomeView()
                    .tabItem { Label("Home", systemImage: "house.fill") }
                    .tag(0)
                LibraryHubView()
                    .tabItem { Label("Library", systemImage: "photo.on.rectangle.angled") }
                    .tag(1)
                BackupTabView()
                    .tabItem { Label("Backup", systemImage: "arrow.triangle.2.circlepath") }
                    .tag(2)
                SessionsView()
                    .tabItem { Label("Sessions", systemImage: "wave.3.right.circle.fill") }
                    .tag(3)
                SettingsHubView()
                    .tabItem { Label("Settings", systemImage: "gearshape.fill") }
                    .tag(4)
            }
            .tint(CumulousTheme.accent)
        }
        .task {
            while !Task.isCancelled {
                await pollTopBackup()
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
        }
    }

    private func pollTopBackup() async {
        // Full system
        if let url = URL(string: "\(api.baseURL)/backup/progress"),
           let (data, _) = try? await URLSession.shared.data(from: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            var merged = obj
            // Merge harvest keep-awake + status line
            if let hURL = URL(string: "\(api.baseURL)/photos/harvest-progress"),
               let (hData, _) = try? await URLSession.shared.data(from: hURL),
               let hObj = try? JSONSerialization.jsonObject(with: hData) as? [String: Any] {
                if let p = hObj["power"] as? [String: Any], (p["keep_awake"] as? Bool) == true {
                    merged["power"] = p
                    merged["active"] = true
                }
                if (hObj["active"] as? Bool) == true, let line = hObj["status_line"] as? String {
                    topBackupLine = line
                }
            }
            await BackupPowerManager.shared.apply(from: merged, apiBase: api.baseURL)
            let active = merged["active"] as? Bool ?? false
            let status = obj["status"] as? String ?? ""
            let inFlight = active
                || status == "waiting_passcode"
                || status == "needs_resume"
                || status == "handoff"
                || status == "awaiting_network"
            if inFlight && (obj["active"] as? Bool == true) {
                let raw = obj["percent_int"] as? Int ?? Int(obj["percent"] as? Double ?? 0)
                let high = Int(obj["high_water_percent"] as? Double ?? 0)
                let floored = BackupPowerManager.shared.floorPercent(max(raw, high, topBackupPct ?? 0))
                topBackupPct = max(floored, topBackupPct ?? 0)
                topBackupLine = obj["status_line"] as? String ?? topBackupLine
            } else if status == "complete" {
                BackupPowerManager.shared.resetPercentFloor()
                topBackupPct = nil
            } else if (merged["active"] as? Bool) != true {
                topBackupPct = nil
            }
            return
        }
        // Harvest-only when full progress unreachable
        if let hURL = URL(string: "\(api.baseURL)/photos/harvest-progress"),
           let (hData, _) = try? await URLSession.shared.data(from: hURL),
           let hObj = try? JSONSerialization.jsonObject(with: hData) as? [String: Any] {
            await BackupPowerManager.shared.apply(from: [
                "active": hObj["active"] as? Bool ?? false,
                "status": hObj["status"] as? String ?? "",
                "power": hObj["power"] as? [String: Any] ?? [:],
            ], apiBase: api.baseURL)
            if (hObj["active"] as? Bool) == true {
                topBackupLine = hObj["status_line"] as? String ?? topBackupLine
            }
        }
    }
}

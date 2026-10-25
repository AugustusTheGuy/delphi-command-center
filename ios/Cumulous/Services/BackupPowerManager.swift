import AVFoundation
import Foundation
import UIKit
import UserNotifications

/// Keeps the iPhone screen from dimming/locking while a Cumulous backup is active.
///
/// Apple limits (no MDM / private API):
///  - `isIdleTimerDisabled` is the supported “don’t dim/lock while this app is foreground” switch.
///  - System Settings → Auto-Lock cannot be written by third-party apps.
///  - Injecting real touches is not allowed; reasserting the idle timer every 0.25s is the
///    clean equivalent of “touch before dim” and survives iOS occasionally clearing the flag.
///  - A near-silent looping audio session further discourages sleep while the app is open.
@MainActor
final class BackupPowerManager: ObservableObject {
    static let shared = BackupPowerManager()

    private let defaults = UserDefaults.standard
    private let priorKey = "cumulous_prior_auto_lock_seconds"
    private let priorKnownKey = "cumulous_prior_auto_lock_known"
    private let floorKey = "cumulous_backup_percent_floor"

    /// Poll interval for idle-timer reassert (matches product request: every 0.25s).
    private let reassertInterval: TimeInterval = 0.25

    private var lastKeepAwake = false
    private var notifiedRestoreId: String?
    private var reassertTimer: Timer?
    private var silentPlayer: AVAudioPlayer?
    private var observers: [NSObjectProtocol] = []

    private init() {
        // Re-engage if iOS clears the flag on lifecycle events.
        let nc = NotificationCenter.default
        observers.append(nc.addObserver(
            forName: UIApplication.didBecomeActiveNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.reassertIdleTimer() }
        })
        observers.append(nc.addObserver(
            forName: UIApplication.willEnterForegroundNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.reassertIdleTimer() }
        })
        observers.append(nc.addObserver(
            forName: UIApplication.didEnterBackgroundNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            // Still try — system may ignore when backgrounded; timer restarts on foreground.
            Task { @MainActor in self?.reassertIdleTimer() }
        })
    }

    deinit {
        observers.forEach { NotificationCenter.default.removeObserver($0) }
    }

    // MARK: - Public API

    /// Call on every `/backup/progress` poll.
    func apply(from progress: [String: Any], apiBase: String) async {
        let power = progress["power"] as? [String: Any] ?? [:]
        let keep = (power["keep_awake"] as? Bool ?? false)
            || (progress["active"] as? Bool ?? false)
            || Self.isBackupActiveStatus(progress["status"] as? String)

        if keep {
            engageKeepAwake()
            if !lastKeepAwake {
                await snapshotAndPromptStart(power: power, apiBase: apiBase)
            }
        } else if lastKeepAwake {
            await disengageKeepAwake(power: power, apiBase: apiBase)
        }
        lastKeepAwake = keep

        // Deliver server pushes (skip stale “restore” while still keeping awake)
        if let pending = power["pending_notifications"] as? [[String: Any]] {
            for n in pending where (n["delivered"] as? Bool) != true {
                let kind = n["kind"] as? String ?? ""
                if keep && kind == "auto_lock_restore" {
                    // Ack without presenting — backup still running; restore was a false complete.
                    if let id = n["id"] as? String {
                        await ack(apiBase: apiBase, notificationId: id)
                    }
                    continue
                }
                await presentLocal(n, apiBase: apiBase)
            }
        }
    }

    /// Never let displayed backup % go backwards (lock / relaunch / stale poll).
    func floorPercent(_ incoming: Int) -> Int {
        let prev = defaults.integer(forKey: floorKey)
        let next = max(0, min(100, max(prev, incoming)))
        if next > prev {
            defaults.set(next, forKey: floorKey)
        }
        return next
    }

    func resetPercentFloor() {
        defaults.set(0, forKey: floorKey)
    }

    /// User can set prior Auto-Lock from Settings (seconds; 0 = Never).
    func setPriorAutoLockSeconds(_ seconds: Int) {
        defaults.set(seconds, forKey: priorKey)
        defaults.set(true, forKey: priorKnownKey)
    }

    func priorAutoLockSeconds() -> Int? {
        defaults.bool(forKey: priorKnownKey) ? defaults.integer(forKey: priorKey) : nil
    }

    /// Best-effort open Display settings (iOS may ignore URL schemes).
    func openDisplaySettings() {
        let candidates = [
            "App-prefs:root=DISPLAY&path=AUTOLOCK",
            "prefs:root=DISPLAY&path=AUTOLOCK",
            "App-prefs:root=DISPLAY",
            UIApplication.openSettingsURLString,
        ]
        for s in candidates {
            if let u = URL(string: s), UIApplication.shared.canOpenURL(u) {
                UIApplication.shared.open(u)
                return
            }
        }
    }

    // MARK: - Keep-awake engine

    private func engageKeepAwake() {
        // Always force on first engage (before lastKeepAwake flips / timer exists).
        UIApplication.shared.isIdleTimerDisabled = true
        startReassertTimerIfNeeded()
        startSilentAudioIfNeeded()
    }

    private func disengageKeepAwake(power: [String: Any], apiBase: String) async {
        stopReassertTimer()
        stopSilentAudio()
        UIApplication.shared.isIdleTimerDisabled = false
        await promptRestore(power: power, apiBase: apiBase)
        resetPercentFloor()
    }

    private func reassertIdleTimer() {
        // Force true every tick — iOS sometimes clears this after auto-lock attempts.
        // Only meaningful while engaged (timer running or lastKeepAwake).
        guard lastKeepAwake || reassertTimer != nil else { return }
        UIApplication.shared.isIdleTimerDisabled = true
    }

    private func startReassertTimerIfNeeded() {
        guard reassertTimer == nil else { return }
        // Tolerance 0 keeps it tight enough before typical 30s dim windows.
        let t = Timer.scheduledTimer(withTimeInterval: reassertInterval, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.reassertIdleTimer()
            }
        }
        t.tolerance = 0.02
        RunLoop.main.add(t, forMode: .common)
        reassertTimer = t
        reassertIdleTimer()
    }

    private func stopReassertTimer() {
        reassertTimer?.invalidate()
        reassertTimer = nil
    }

    /// Near-silent looping tone — secondary keep-alive (works with idle timer, not instead of it).
    private func startSilentAudioIfNeeded() {
        if silentPlayer?.isPlaying == true { return }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
            try session.setActive(true, options: [])
            if silentPlayer == nil {
                silentPlayer = try Self.makeSilentPlayer()
            }
            silentPlayer?.volume = 0.01
            silentPlayer?.numberOfLoops = -1
            silentPlayer?.play()
        } catch {
            // Idle timer alone still applies if audio session fails.
        }
    }

    private func stopSilentAudio() {
        silentPlayer?.stop()
        silentPlayer = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
    }

    /// 1s of near-silence PCM (mono 16-bit 8kHz) — no asset bundle required.
    private static func makeSilentPlayer() throws -> AVAudioPlayer {
        let sampleRate = 8000
        let seconds = 1
        let numSamples = sampleRate * seconds
        var data = Data()
        // Minimal WAV header + zero samples (true digital silence; system still treats session as active)
        func appendUInt32(_ v: UInt32) {
            var le = v.littleEndian
            withUnsafeBytes(of: &le) { data.append(contentsOf: $0) }
        }
        func appendUInt16(_ v: UInt16) {
            var le = v.littleEndian
            withUnsafeBytes(of: &le) { data.append(contentsOf: $0) }
        }
        let dataSize = UInt32(numSamples * 2)
        data.append(contentsOf: [0x52, 0x49, 0x46, 0x46]) // RIFF
        appendUInt32(36 + dataSize)
        data.append(contentsOf: [0x57, 0x41, 0x56, 0x45]) // WAVE
        data.append(contentsOf: [0x66, 0x6D, 0x74, 0x20]) // fmt
        appendUInt32(16)
        appendUInt16(1) // PCM
        appendUInt16(1) // mono
        appendUInt32(UInt32(sampleRate))
        appendUInt32(UInt32(sampleRate * 2))
        appendUInt16(2)
        appendUInt16(16)
        data.append(contentsOf: [0x64, 0x61, 0x74, 0x61]) // data
        appendUInt32(dataSize)
        data.append(Data(count: numSamples * 2))
        let player = try AVAudioPlayer(data: data)
        player.prepareToPlay()
        return player
    }

    // MARK: - Notifications / server

    private static func isBackupActiveStatus(_ status: String?) -> Bool {
        guard let s = status else { return false }
        return ["running", "waiting_passcode", "needs_resume", "handoff", "awaiting_network", "receiving", "starting"].contains(s)
    }

    private func snapshotAndPromptStart(power: [String: Any], apiBase: String) async {
        let known = defaults.bool(forKey: priorKnownKey)
        let prior = known ? defaults.integer(forKey: priorKey) : -1
        await postSnapshot(apiBase: apiBase, seconds: known ? prior : nil, idleBefore: false)
        let body: String
        if known {
            let label = labelFor(prior)
            body = "Screen will not dim while Cumulous is open for backup. Prior Auto-Lock: \(label). Restore prompt when backup ends."
        } else {
            body = "Screen will not dim while Cumulous is open for backup. Optional: Settings → Display → Auto-Lock → Never for system-level awake."
        }
        await notify(title: "Cumulous · Keep screen awake", body: body, id: "wake-start-\(Int(Date().timeIntervalSince1970))")
    }

    private func promptRestore(power: [String: Any], apiBase: String) async {
        let label = (power["restore_to_label"] as? String)
            ?? (defaults.bool(forKey: priorKnownKey) ? labelFor(defaults.integer(forKey: priorKey)) : "your previous setting")
        let id = "wake-restore-\(Int(Date().timeIntervalSince1970))"
        if notifiedRestoreId == id { return }
        notifiedRestoreId = id
        await notify(
            title: "Cumulous · Restore Auto-Lock",
            body: "Backup ended. Restore Auto-Lock to \(label) if you changed it (Settings → Display & Brightness → Auto-Lock).",
            id: id
        )
    }

    private func labelFor(_ seconds: Int) -> String {
        switch seconds {
        case 0: return "Never"
        case 30: return "30 Seconds"
        case 60: return "1 Minute"
        case 120: return "2 Minutes"
        case 180: return "3 Minutes"
        case 240: return "4 Minutes"
        case 300: return "5 Minutes"
        default: return "\(seconds)s"
        }
    }

    private func postSnapshot(apiBase: String, seconds: Int?, idleBefore: Bool) async {
        guard let url = URL(string: "\(apiBase)/backup/power/snapshot") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var body: [String: Any] = ["idle_timer_disabled_before": idleBefore]
        if let seconds { body["auto_lock_seconds"] = seconds }
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        _ = try? await URLSession.shared.data(for: req)
    }

    private func presentLocal(_ n: [String: Any], apiBase: String) async {
        guard let id = n["id"] as? String else { return }
        let title = n["title"] as? String ?? "Cumulous"
        let body = n["body"] as? String ?? ""
        await notify(title: title, body: body, id: "srv-\(id)")
        await ack(apiBase: apiBase, notificationId: id)
    }

    private func ack(apiBase: String, notificationId: String) async {
        if let url = URL(string: "\(apiBase)/backup/power/ack?notification_id=\(notificationId)") {
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            _ = try? await URLSession.shared.data(for: req)
        }
    }

    private func notify(title: String, body: String, id: String) async {
        let center = UNUserNotificationCenter.current()
        let granted = await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            center.requestAuthorization(options: [.alert, .sound, .badge]) { ok, _ in
                cont.resume(returning: ok)
            }
        }
        guard granted else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 0.5, repeats: false)
        let req = UNNotificationRequest(identifier: id, content: content, trigger: trigger)
        try? await center.add(req)
    }
}

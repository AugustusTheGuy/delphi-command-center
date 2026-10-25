import Cocoa
import Darwin
import WebKit

let projectRoot = ProcessInfo.processInfo.environment["DHC_ROOT"]
    ?? (NSHomeDirectory() as NSString).appendingPathComponent("delphi-command-center")
let pythonPath = (projectRoot as NSString).appendingPathComponent(".venv/bin/python")
// 8501 is Delphi. 8502 is Cumulous. Do not move this.
let serverPort: UInt16 = 8501
let streamlitPidPath = projectRoot + "/data/streamlit.pid"
let noxRequestPath = projectRoot + "/data/nox_access.request"
let noxBookmarkPath = projectRoot + "/data/nox_bookmark.data"

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow?
    var webView: WKWebView?
    var process: Process?
    var logHandle: FileHandle?
    var startedByUs = false
    var waitingForPort = false
    var serverRestarts = 0
    var adoptedPid: Int32 = 0
    var noxScopedURL: URL?
    var noxPanelOpen = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        restoreNoxBookmark()
        ensureWindow()
        ensureServer()
        beginLoad()
        watchServer()
        watchNoxRequest()
        // Show the window after this method returns so startup cannot stall
        // on becoming the front app. Do not add a behavior that moves the
        // window onto a Space. That pair never finished opening the window.
        DispatchQueue.main.async { [weak self] in
            self?.raiseOnActiveSpace()
        }
    }

    /// Dock and Finder reopen the already-running app. The first launch is the
    /// only place a window used to be created, so a closed or stranded window
    /// left a live process with nothing on screen.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        ensureWindow()
        let wasDown = !portIsOpen()
        ensureServer()
        if wasDown || webView?.url == nil {
            beginLoad()
        }
        DispatchQueue.main.async { [weak self] in
            self?.raiseOnActiveSpace()
        }
        return true
    }

    /// A dead page server used to leave this window up with nothing behind it.
    /// Dock and Finder reopen, and this watcher, start it again.
    func ensureServer() {
        if portIsOpen() {
            adoptOurServer()
            return
        }
        if process?.isRunning == true { return }
        if serverRestarts >= 3 { return }
        serverRestarts += 1
        startServer()
        startedByUs = true
    }

    func beginLoad() {
        guard let webView, !waitingForPort else { return }
        waitingForPort = true
        waitAndLoad(webView, attempts: 40)
    }

    func watchServer() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let self else { return }
            if self.portIsOpen() {
                self.serverRestarts = 0
            } else if self.process?.isRunning != true {
                self.ensureServer()
                self.beginLoad()
            }
            self.watchServer()
        }
    }

    func focusedScreenFrame() -> NSRect {
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { $0.frame.contains(mouse) } ?? NSScreen.main
        return screen?.frame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
    }

    func ensureWindow() {
        let size = NSSize(width: 1280, height: 840)
        let screen = focusedScreenFrame()
        let origin = NSPoint(
            x: screen.midX - size.width / 2,
            y: screen.midY - size.height / 2
        )
        let frame = NSRect(origin: origin, size: size)
        if window == nil {
            // A normal window is pinned to the Space that launched it. A panel
            // with these behaviors is visible on the desktop in front, including
            // a full-screen Space. Checked with a throwaway panel on this Mac.
            let created = NSPanel(
                contentRect: frame,
                styleMask: [.titled, .closable, .miniaturizable, .resizable, .nonactivatingPanel],
                backing: .buffered,
                defer: false
            )
            created.title = "Delphi Command Center"
            created.minSize = NSSize(width: 960, height: 640)
            created.isReleasedWhenClosed = false
            created.isFloatingPanel = true
            created.hidesOnDeactivate = false
            created.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
            created.level = .floating
            let web = WKWebView(frame: created.contentView?.bounds ?? .zero)
            web.autoresizingMask = [.width, .height]
            created.contentView?.addSubview(web)
            window = created
            webView = web
        }
        guard let panel = window as? NSPanel else { return }
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.setFrame(frame, display: true)
    }

    func raiseOnActiveSpace() {
        guard let panel = window as? NSPanel else { return }
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.isFloatingPanel = true
        panel.level = .floating
        // A normal level did join this desktop, then the window left the screen
        // on the space in use. Stay floating so it remains visible.
        panel.orderFrontRegardless()
    }

    func portIsOpen() -> Bool {
        let sock = socket(AF_INET, SOCK_STREAM, 0)
        if sock < 0 { return false }
        defer { close(sock) }
        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = serverPort.bigEndian
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let connected = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(sock, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return connected == 0
    }

    func startServer() {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: pythonPath)
        proc.currentDirectoryURL = URL(fileURLWithPath: projectRoot)
        proc.arguments = [
            "-m", "streamlit", "run", "delphi_command_center.py",
            "--server.port", "8501",
            "--server.address", "127.0.0.1",
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ]
        let logURL = URL(fileURLWithPath: projectRoot).appendingPathComponent("data/logs/delphi-server.log")
        try? FileManager.default.createDirectory(
            at: logURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        if let handle = try? FileHandle(forWritingTo: logURL) {
            handle.seekToEndOfFile()
            logHandle = handle
            proc.standardOutput = handle
            proc.standardError = handle
        }
        try? proc.run()
        process = proc
        if proc.isRunning {
            writePidFile(proc.processIdentifier)
        }
    }

    func waitAndLoad(_ web: WKWebView, attempts: Int) {
        if portIsOpen() {
            waitingForPort = false
            web.load(URLRequest(url: URL(string: "http://127.0.0.1:\(serverPort)")!))
            return
        }
        if attempts <= 0 {
            waitingForPort = false
            let label = NSTextField(labelWithString: "Delphi Command Center could not start. See data/logs/delphi-server.log.")
            label.frame = NSRect(x: 24, y: 40, width: 900, height: 24)
            window?.contentView?.addSubview(label)
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            self.waitAndLoad(web, attempts: attempts - 1)
        }
    }

    func runCommand(_ launch: String, _ args: [String]) -> String {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: launch)
        proc.arguments = args
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = Pipe()
        do {
            try proc.run()
        } catch {
            return ""
        }
        proc.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        return String(data: data, encoding: .utf8) ?? ""
    }

    func isOurStreamlit(_ pid: Int32) -> Bool {
        if pid <= 0 { return false }
        let command = runCommand("/bin/ps", ["-p", String(pid), "-o", "command="])
        return command.contains("delphi_command_center.py") && command.contains("8501")
    }

    func readPidFile() -> Int32? {
        guard let text = try? String(contentsOfFile: streamlitPidPath, encoding: .utf8) else { return nil }
        return Int32(text.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    func writePidFile(_ pid: Int32) {
        let url = URL(fileURLWithPath: streamlitPidPath)
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? String(pid).write(to: url, atomically: true, encoding: .utf8)
    }

    func listenerPid() -> Int32? {
        let text = runCommand("/usr/sbin/lsof", ["-nP", "-iTCP:8501", "-sTCP:LISTEN", "-t"])
        for line in text.split(separator: "\n") {
            if let pid = Int32(line.trimmingCharacters(in: .whitespaces)) {
                return pid
            }
        }
        return nil
    }

    /// Take responsibility for a page server this app can prove is Delphi.
    func adoptOurServer() {
        if adoptedPid > 0 && isOurStreamlit(adoptedPid) { return }
        if let pid = readPidFile(), isOurStreamlit(pid) {
            adoptedPid = pid
            return
        }
        if let pid = listenerPid(), isOurStreamlit(pid) {
            adoptedPid = pid
            writePidFile(pid)
        }
    }

    func watchNoxRequest() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in
            guard let self else { return }
            if FileManager.default.fileExists(atPath: noxRequestPath) {
                try? FileManager.default.removeItem(atPath: noxRequestPath)
                self.askForNox()
            }
            self.watchNoxRequest()
        }
    }

    func askForNox() {
        if noxPanelOpen { return }
        noxPanelOpen = true
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = false
        panel.prompt = "Allow"
        panel.message = "Allow Delphi to save the library list on ExternalSSD."
        if FileManager.default.fileExists(atPath: "/Volumes/ExternalSSD") {
            panel.directoryURL = URL(fileURLWithPath: "/Volumes/ExternalSSD")
        }
        panel.begin { [weak self] response in
            guard let self else { return }
            self.noxPanelOpen = false
            guard response == .OK, let url = panel.url else { return }
            if url.startAccessingSecurityScopedResource() {
                self.noxScopedURL = url
            }
            if let bookmark = try? url.bookmarkData(options: [.withSecurityScope], includingResourceValuesForKeys: nil, relativeTo: nil) {
                try? bookmark.write(to: URL(fileURLWithPath: noxBookmarkPath))
            }
        }
    }

    func restoreNoxBookmark() {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: noxBookmarkPath)) else { return }
        var stale = false
        guard let resolved = try? URL(
            resolvingBookmarkData: data,
            options: [.withSecurityScope],
            relativeTo: nil,
            bookmarkDataIsStale: &stale
        ) else { return }
        if resolved.startAccessingSecurityScopedResource() {
            noxScopedURL = resolved
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        let child = process?.processIdentifier ?? 0
        if startedByUs {
            process?.terminate()
        }
        let extra = adoptedPid
        if extra > 0 && extra != child && isOurStreamlit(extra) {
            kill(extra, SIGTERM)
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()

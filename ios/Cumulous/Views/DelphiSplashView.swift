import SwiftUI

/// Full-screen Delphi Technologies loading screen (iPhone).
/// Duration scales with projected load; version/icon refreshed every launch.
struct DelphiSplashView: View {
    var version: String = "0.2.0"
    var onFinished: () -> Void

    @State private var opacity: Double = 1
    @State private var scale: CGFloat = 1
    @State private var displayVersion: String = "0.2.0"

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            VStack(spacing: 16) {
                Image("AppLogo")
                    .resizable()
                    .scaledToFill()
                    .frame(width: 120, height: 120)
                    .clipShape(RoundedRectangle(cornerRadius: 26.4, style: .continuous))
                    .scaleEffect(scale)
                    .onAppear {
                        withAnimation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true)) {
                            scale = 1.04
                        }
                    }
                Text("Delphi Technologies")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(.white)
                Text("Cumulous")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(Color(white: 0.55))
                Text("v\(displayVersion)")
                    .font(.system(size: 12))
                    .foregroundStyle(Color(white: 0.4))
            }
        }
        .opacity(opacity)
        .ignoresSafeArea()
        .task {
            // Fetch latest version from Mac Mini when reachable
            var dur: Double = 2.4
            displayVersion = version
            if let url = URL(string: "\(CumulousAPI.shared.baseURL)/app/version.json"),
               let (data, _) = try? await URLSession.shared.data(from: url),
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                if let v = obj["version"] as? String, !v.isEmpty {
                    displayVersion = v
                }
                if let splash = obj["splash"] as? [String: Any],
                   let d = splash["duration_sec"] as? Double {
                    dur = d
                }
            }
            try? await Task.sleep(nanoseconds: UInt64(max(1.2, min(dur, 4.2)) * 1_000_000_000))
            withAnimation(.easeOut(duration: 0.35)) { opacity = 0 }
            try? await Task.sleep(nanoseconds: 350_000_000)
            onFinished()
        }
    }
}

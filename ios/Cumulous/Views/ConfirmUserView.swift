import SwiftUI
import MapKit
import CoreLocation

/// Apple-style compact verification: 4-digit boxes + mini map of request location.
/// Polls Mac `/challenge/live` so codes reach every Cumulous iPhone, not only Mac.
struct ConfirmUserView: View {
    @ObservedObject private var api = CumulousAPI.shared
    @StateObject private var locationReporter = ChallengeLocationReporter()
    @State private var live: LiveCode?
    @State private var showInputSheet = false
    @State private var inputCode = ""
    @State private var message = "When Mac starts Confirm or Backup, the code appears here live."
    @State private var mapPosition: MapCameraPosition = .automatic
    @State private var verifyStatus = ""

    /// ~2.5in wide card; map ≈ ⅓ height
    private let cardWidth: CGFloat = 268
    private let mapHeight: CGFloat = 128
    /// Apple systemBlue (light HIG) — vibrant confirmation blue
    private let appleBlue = Color(red: 0.0, green: 0.478, blue: 1.0) // #007AFF

    var body: some View {
        NavigationStack {
            ZStack {
                CumulousTheme.bg.ignoresSafeArea()
                VStack(spacing: 18) {
                    Text("Confirm 4-Digit Code")
                        .font(.system(size: 22, weight: .semibold))
                        .foregroundStyle(CumulousTheme.text)
                        .shadow(color: .white.opacity(0.12), radius: 8)

                    if let live {
                        pinCard(live)
                    } else {
                        Text(message)
                            .font(.subheadline)
                            .foregroundStyle(CumulousTheme.muted)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal)
                        ProgressView()
                            .tint(appleBlue)
                    }

                    if !verifyStatus.isEmpty {
                        Text(verifyStatus)
                            .font(.caption)
                            .foregroundStyle(CumulousTheme.muted)
                    }

                    Text("Keep Cumulous open on Wi‑Fi or Tailscale to receive codes on every Apple device.")
                        .font(.caption)
                        .foregroundStyle(CumulousTheme.muted)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 28)

                    Spacer()
                }
                .padding(.top, 36)
            }
            .preferredColorScheme(.dark)
            .sheet(isPresented: $showInputSheet) {
                inputCodeSheet
                    .presentationDetents([.height(380)])
                    .presentationDragIndicator(.visible)
            }
            .task {
                locationReporter.start()
                await pollLoop()
            }
            .onDisappear { locationReporter.stop() }
        }
    }

    /// Phase 2 — same-size input after tapping Input Code
    private var inputCodeSheet: some View {
        VStack(spacing: 14) {
            Text("Confirm 4-Digit Code")
                .font(.system(size: 15, weight: .semibold))
            Text("Enter the code shown on your devices")
                .font(.caption)
                .foregroundStyle(.secondary)
            if let place = live?.place, !place.isEmpty {
                Text(place)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            TextField("••••", text: $inputCode)
                .keyboardType(.numberPad)
                .multilineTextAlignment(.center)
                .font(.system(size: 28, weight: .semibold, design: .rounded))
                .frame(width: 120)
                .padding(10)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color(white: 0.12)))
                .onChange(of: inputCode) { _, v in
                    inputCode = String(v.filter(\.isNumber).prefix(4))
                }
            Button {
                Task { await verifyOnMac() }
            } label: {
                Text("Verify")
                    .font(.system(size: 16, weight: .semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            }
            .buttonStyle(.plain)
            .background(RoundedRectangle(cornerRadius: 12).fill(appleBlue))
            .foregroundStyle(.white)
            .padding(.horizontal, 24)
            Button("Cancel") { showInputSheet = false }
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.top, 20)
        .preferredColorScheme(.dark)
    }

    @ViewBuilder
    private func pinCard(_ live: LiveCode) -> some View {
        VStack(spacing: 12) {
            Text("Confirm 4-Digit Code")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.white)
            Text("Cumulous · \(live.purpose.replacingOccurrences(of: "_", with: " ").capitalized)")
                .font(.system(size: 11))
                .foregroundStyle(Color(white: 0.72))

            HStack(spacing: 8) {
                ForEach(Array(live.digits.enumerated()), id: \.offset) { _, ch in
                    Text(String(ch))
                        .font(.system(size: 26, weight: .semibold, design: .rounded))
                        .foregroundStyle(.white)
                        .frame(width: 40, height: 48)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(Color(white: 0.12))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .stroke(Color.white.opacity(0.14), lineWidth: 1)
                        )
                }
            }
            .padding(.vertical, 2)

            if !live.place.isEmpty {
                Text(live.place)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Color(white: 0.9))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 8)
            }

            // Map ≈ ⅓ of card — live device location
            Group {
                if let lat = live.latitude, let lon = live.longitude {
                    Map(position: $mapPosition) {
                        Marker("Request", coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lon))
                            .tint(appleBlue)
                    }
                    .mapStyle(.standard(elevation: .realistic))
                    .frame(height: mapHeight)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .stroke(Color(red: 0.79, green: 0.64, blue: 0.15).opacity(0.35), lineWidth: 1)
                    )
                    .onAppear {
                        let c = CLLocationCoordinate2D(latitude: lat, longitude: lon)
                        mapPosition = .region(
                            MKCoordinateRegion(
                                center: c,
                                span: MKCoordinateSpan(latitudeDelta: 0.08, longitudeDelta: 0.08)
                            )
                        )
                    }
                } else if let url = URL(string: live.mapURL), !live.mapURL.isEmpty {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let img):
                            img.resizable().scaledToFill()
                        case .failure:
                            mapPlaceholder
                        default:
                            ProgressView().tint(appleBlue)
                        }
                    }
                    .frame(height: mapHeight)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                } else {
                    mapPlaceholder
                }
            }
            .frame(maxWidth: .infinity)

            if live.secondsLeft > 0 {
                Text("\(max(1, live.secondsLeft / 60)) min left")
                    .font(.caption2)
                    .foregroundStyle(Color(white: 0.55))
            }

            // Bottom-right: Apple systemBlue Input Code
            HStack {
                Spacer()
                Button {
                    inputCode = ""
                    showInputSheet = true
                } label: {
                    Text("Input Code")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 18)
                        .padding(.vertical, 10)
                        .background(Capsule().fill(appleBlue))
                }
                .buttonStyle(.plain)
            }
            .padding(.top, 4)
        }
        .padding(16)
        .frame(width: cardWidth)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Color(white: 0.17))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Color(red: 0.79, green: 0.64, blue: 0.15).opacity(0.28), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.45), radius: 24, y: 10)
    }

    private func verifyOnMac() async {
        guard inputCode.count == 4 else {
            verifyStatus = "Enter all 4 digits"
            return
        }
        guard let url = URL(string: "\(api.baseURL)/challenge/verify") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "code": inputCode,
            "purpose": live?.purpose ?? "confirm_user",
        ])
        if let (data, _) = try? await URLSession.shared.data(for: req),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           obj["ok"] as? Bool == true {
            verifyStatus = "Verified"
            showInputSheet = false
            self.live = nil
        } else {
            verifyStatus = "Code not accepted"
        }
    }

    private var mapPlaceholder: some View {
        ZStack {
            Color(white: 0.1)
            Text("Map loading…")
                .font(.caption2)
                .foregroundStyle(Color(white: 0.45))
        }
        .frame(height: mapHeight)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func pollLoop() async {
        while !Task.isCancelled {
            await fetchLive()
            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
    }

    private func fetchLive() async {
        var components = URLComponents(string: "\(api.baseURL)/challenge/live")
        var items: [URLQueryItem] = []
        if let did = locationReporter.deviceId, !did.isEmpty {
            items.append(.init(name: "device_id", value: did))
        }
        components?.queryItems = items.isEmpty ? nil : items
        guard let url = components?.url else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let decoded = try JSONDecoder().decode(LiveEnvelope.self, from: data)
            if let latest = decoded.latest, let code = latest.code, code.count >= 4 {
                let lat = latest.latitude ?? latest.location?.latitude
                let lon = latest.longitude ?? latest.location?.longitude
                live = LiveCode(
                    digits: Array(code.prefix(4)),
                    purpose: latest.purpose ?? "verification",
                    secondsLeft: latest.secondsLeft ?? 0,
                    place: latest.display_place
                        ?? latest.location?.display_place
                        ?? "",
                    mapURL: latest.map_url ?? latest.location?.map_url ?? "",
                    latitude: lat,
                    longitude: lon
                )
                message = "Code received"
                if let lat, let lon {
                    mapPosition = .region(
                        MKCoordinateRegion(
                            center: CLLocationCoordinate2D(latitude: lat, longitude: lon),
                            span: MKCoordinateSpan(latitudeDelta: 0.08, longitudeDelta: 0.08)
                        )
                    )
                }
            }
        } catch {
            message = "Waiting for Mac Mini…"
        }
    }
}

// MARK: - Location reporter (accurate request map)

@MainActor
final class ChallengeLocationReporter: NSObject, ObservableObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    @Published var deviceId: String?
    private var lastPost: Date = .distantPast

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        deviceId = UIDevice.current.identifierForVendor?.uuidString
    }

    func start() {
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()
    }

    func stop() {
        manager.stopUpdatingLocation()
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let loc = locations.last else { return }
        Task { @MainActor in
            // Throttle posts
            guard Date().timeIntervalSince(self.lastPost) > 30 else { return }
            self.lastPost = Date()
            await self.postLocation(loc)
        }
    }

    private func postLocation(_ loc: CLLocation) async {
        let base = CumulousAPI.shared.baseURL
        guard let url = URL(string: "\(base)/challenge/location") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = [
            "device_id": deviceId ?? "ios-device",
            "latitude": loc.coordinate.latitude,
            "longitude": loc.coordinate.longitude,
            "accuracy_m": loc.horizontalAccuracy,
            "label": "",
        ]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        _ = try? await URLSession.shared.data(for: req)
    }
}

// MARK: - Models

private struct LiveCode {
    var digits: [Character]
    var purpose: String
    var secondsLeft: Int
    var place: String = ""
    var mapURL: String = ""
    var latitude: Double? = nil
    var longitude: Double? = nil
}

private struct LiveEnvelope: Decodable {
    var latest: LivePayload?
}

private struct LivePayload: Decodable {
    var code: String?
    var purpose: String?
    var secondsLeft: Int?
    var map_url: String?
    var display_place: String?
    var latitude: Double?
    var longitude: Double?
    var location: LiveLocation?

    enum CodingKeys: String, CodingKey {
        case code, purpose, location
        case secondsLeft = "seconds_left"
        case map_url, display_place, latitude, longitude
    }
}

private struct LiveLocation: Decodable {
    var map_url: String?
    var display_place: String?
    var latitude: Double?
    var longitude: Double?
}

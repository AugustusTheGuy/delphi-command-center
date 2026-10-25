import Foundation
import UIKit

/// Talks to Mac Mini Cumulous bridge (LAN / Tailscale). Photos stream into the app — not Safari-only.
@MainActor
final class CumulousAPI: ObservableObject {
    static let shared = CumulousAPI()

    @Published var baseURL: String {
        didSet { UserDefaults.standard.set(baseURL, forKey: "cumulous_api_base") }
    }
    @Published var online = false
    @Published var lastError: String?

    private let session: URLSession
    private let imageCache = NSCache<NSString, UIImage>()

    init() {
        let stored = UserDefaults.standard.string(forKey: "cumulous_api_base")
        self.baseURL = stored ?? Self.discoverDefaultBase()
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 30
        cfg.requestCachePolicy = .returnCacheDataElseLoad
        cfg.urlCache = URLCache(memoryCapacity: 64 * 1024 * 1024, diskCapacity: 512 * 1024 * 1024)
        self.session = URLSession(configuration: cfg)
        imageCache.countLimit = 400
    }

    static func discoverDefaultBase() -> String {
        // Primary LAN from last known Cumulous Mac; override in Settings
        if let s = UserDefaults.standard.string(forKey: "cumulous_api_base"), !s.isEmpty { return s }
        return "http://192.168.1.100:8765"
    }

    func setBaseURL(_ url: String) {
        var u = url.trimmingCharacters(in: .whitespacesAndNewlines)
        while u.hasSuffix("/") { u.removeLast() }
        baseURL = u
    }

    // MARK: - Health

    func ping() async -> Bool {
        guard let url = URL(string: "\(baseURL)/health") else { return false }
        do {
            let (_, resp) = try await session.data(from: url)
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200
            online = ok
            return ok
        } catch {
            online = false
            lastError = error.localizedDescription
            return false
        }
    }

    // MARK: - Photos library (in-app)

    func fetchLibrary(query: String = "", limit: Int = 500) async throws -> [PhotoAssetDTO] {
        var c = URLComponents(string: "\(baseURL)/photos/library")!
        c.queryItems = [
            .init(name: "limit", value: "\(min(limit, 2000))"),
            .init(name: "q", value: query),
            .init(name: "sort", value: "date_desc"),
        ]
        let data = try await get(c.url!)
        return try JSONDecoder().decode(LibraryDTO.self, from: data).items
    }

    func fetchDays(limit: Int = 60) async throws -> [PhotoDayDTO] {
        var c = URLComponents(string: "\(baseURL)/photos/days")!
        c.queryItems = [.init(name: "limit_days", value: "\(limit)")]
        let data = try await get(c.url!)
        return try JSONDecoder().decode(DaysDTO.self, from: data).days
    }

    func fetchAlbums() async throws -> [PhotoAlbumDTO] {
        let data = try await get(URL(string: "\(baseURL)/photos/albums")!)
        return try JSONDecoder().decode(AlbumsDTO.self, from: data).albums
    }

    func fetchTags(digest: String) async throws -> PhotoTagsDTO? {
        let data = try await get(URL(string: "\(baseURL)/photos/tags/\(digest)")!)
        return try JSONDecoder().decode(TagsEnvelopeDTO.self, from: data).tags
    }

    func thumbURL(_ digest: String) -> URL? {
        URL(string: "\(baseURL)/photos/thumb/\(digest)")
    }

    func mediaURL(_ digest: String) -> URL? {
        URL(string: "\(baseURL)/photos/media/\(digest)")
    }

    func loadImage(url: URL?) async -> UIImage? {
        guard let url else { return nil }
        let key = url.absoluteString as NSString
        if let hit = imageCache.object(forKey: key) { return hit }
        do {
            let (data, _) = try await session.data(from: url)
            guard let img = UIImage(data: data) else { return nil }
            imageCache.setObject(img, forKey: key)
            return img
        } catch {
            return nil
        }
    }

    // MARK: - Install preference response

    func respondInstall(inviteId: String, accepted: Bool, preference: String) async {
        var c = URLComponents(string: "\(baseURL)/install/respond")!
        c.queryItems = [
            .init(name: "accepted", value: accepted ? "1" : "0"),
            .init(name: "invite_id", value: inviteId),
            .init(name: "preference", value: preference),
        ]
        _ = try? await get(c.url!)
    }

    // MARK: - Helpers

    private func get(_ url: URL) async throws -> Data {
        let (data, resp) = try await session.data(from: url)
        guard let http = resp as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        guard (200..<300).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return data
    }
}

// MARK: - DTOs

struct LibraryDTO: Codable { let items: [PhotoAssetDTO] }
struct DaysDTO: Codable { let days: [PhotoDayDTO] }
struct AlbumsDTO: Codable { let albums: [PhotoAlbumDTO] }
struct TagsEnvelopeDTO: Codable { let tags: PhotoTagsDTO }

struct PhotoAssetDTO: Identifiable, Codable, Hashable {
    var id: String { digest }
    let digest: String
    let name: String?
    let mediaType: String?
    let capturedAtIso: String?
    let placeName: String?
    let setting: String?
    let context: String?
    let keywords: [String]?
    let people: [TagLabelDTO]?
    let plants: [TagLabelDTO]?
    let objects: [TagLabelDTO]?
    let dualOk: Bool?

    enum CodingKeys: String, CodingKey {
        case digest, name, setting, context, keywords, people, plants, objects
        case mediaType = "media_type"
        case capturedAtIso = "captured_at_iso"
        case placeName = "place_name"
        case dualOk = "dual_ok"
    }

    /// Video by API type or filename (AFC names often lack media_type until catalog enrich).
    var isVideo: Bool {
        if (mediaType ?? "").lowercased() == "video" { return true }
        let n = (name ?? "").lowercased()
        return n.hasSuffix(".mov") || n.hasSuffix(".mp4") || n.hasSuffix(".m4v")
            || n.hasSuffix(".3gp") || n.hasSuffix(".avi")
    }

    var isScreenshot: Bool {
        let n = (name ?? "").lowercased()
        if n.contains("screenshot") || n.hasPrefix("img_s") { return true }
        return (keywords ?? []).contains { $0.lowercased().contains("screenshot") }
    }

    var isDualBacked: Bool { dualOk == true }
}

struct PhotoDayDTO: Identifiable, Codable {
    var id: String
    let title: String
    let subtitle: String?
    let count: Int
    let items: [PhotoAssetDTO]
}

struct PhotoAlbumDTO: Identifiable, Codable {
    var id: String
    let title: String
    let count: Int
}

struct PhotoTagsDTO: Codable {
    let capturedAtIso: String?
    let setting: String?
    let context: String?
    let people: [TagLabelDTO]?
    let plants: [TagLabelDTO]?
    let objects: [TagLabelDTO]?
    let relatableDetails: [String]?
    let keywords: [String]?
    let location: TagLocationDTO?

    enum CodingKeys: String, CodingKey {
        case setting, context, people, plants, objects, keywords, location
        case capturedAtIso = "captured_at_iso"
        case relatableDetails = "relatable_details"
    }
}

struct TagLocationDTO: Codable {
    let placeName: String?
    enum CodingKeys: String, CodingKey { case placeName = "place_name" }
}

struct TagLabelDTO: Codable, Hashable {
    let label: String
}

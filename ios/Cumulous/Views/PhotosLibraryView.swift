import SwiftUI
import UIKit

/// Cumulous Photos — iOS Photos–style library (full photo + video library by default).
/// Album chips filter the same library (Videos / Dual / Places / …); Recents = full library.
struct PhotosLibraryView: View {
    @StateObject private var model = PhotosLibraryModel()
    @State private var search = ""
    @State private var selectedDigest: String?
    /// `library` / `recents` = full library (Photos app default). Other ids filter.
    @State private var albumFilter: String = "library"

    /// Flat master library (days ∪ items) — source of truth for filters + viewer.
    private var allLibraryItems: [PhotoAssetDTO] {
        var byDigest: [String: PhotoAssetDTO] = [:]
        for it in model.items { byDigest[it.digest] = it }
        for day in model.days {
            for it in day.items { byDigest[it.digest] = it }
        }
        // Newest first (captured_at_iso string sort is ISO-friendly)
        return byDigest.values.sorted { a, b in
            (a.capturedAtIso ?? "") > (b.capturedAtIso ?? "")
        }
    }

    private var filteredItems: [PhotoAssetDTO] {
        let base: [PhotoAssetDTO]
        if !search.isEmpty {
            let q = search.lowercased()
            base = allLibraryItems.filter { it in
                (it.name ?? "").lowercased().contains(q)
                    || (it.placeName ?? "").lowercased().contains(q)
                    || (it.setting ?? "").lowercased().contains(q)
                    || (it.context ?? "").lowercased().contains(q)
                    || (it.keywords ?? []).joined(separator: " ").lowercased().contains(q)
            }
        } else {
            base = allLibraryItems
        }
        switch albumFilter {
        case "library", "recents", "":
            return base
        case "videos":
            return base.filter(\.isVideo)
        case "dual_mirror", "dual":
            // Prefer dual_ok; if none tagged yet, show whole library (still backed up on Mac)
            let dual = base.filter(\.isDualBacked)
            return dual.isEmpty ? base : dual
        case "people":
            let people = base.filter { !($0.people ?? []).isEmpty }
            return people
        case "places":
            return base.filter { !($0.placeName ?? "").isEmpty }
        case "screenshots":
            return base.filter(\.isScreenshot)
        default:
            return base
        }
    }

    private var viewerAssets: [PhotoAssetDTO] {
        let f = filteredItems
        return f.isEmpty ? allLibraryItems : f
    }

    private var isFullLibrary: Bool {
        search.isEmpty && (albumFilter == "library" || albumFilter == "recents" || albumFilter.isEmpty)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                CumulousTheme.bg.ignoresSafeArea()
                VStack(spacing: 0) {
                    searchBar
                    albumsStrip
                    content
                }
            }
            .navigationTitle("Library")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(CumulousTheme.bg, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await model.refresh() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                            .foregroundStyle(CumulousTheme.accent)
                    }
                }
            }
            .task { await model.refresh() }
            .refreshable { await model.refresh() }
            .fullScreenCover(isPresented: Binding(
                get: { selectedDigest != nil },
                set: { if !$0 { selectedDigest = nil } }
            )) {
                PhotoViewerContainer(
                    assets: viewerAssets,
                    startDigest: selectedDigest ?? ""
                )
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if model.loading && allLibraryItems.isEmpty {
            ProgressView().tint(.white).padding(.top, 48)
            Spacer()
        } else if allLibraryItems.isEmpty {
            emptyState
        } else if isFullLibrary {
            // Photos app: chronological Moments / Days for full library
            daysList
        } else {
            // Filtered album — flat grid of matching items
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    Text(filterTitle)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(CumulousTheme.text)
                        .padding(.horizontal, 16)
                        .padding(.top, 8)
                    Text("\(filteredItems.count) items")
                        .font(.footnote)
                        .foregroundStyle(CumulousTheme.muted)
                        .padding(.horizontal, 16)
                    if filteredItems.isEmpty {
                        filterEmpty
                    } else {
                        photoGrid(filteredItems)
                    }
                }
                .padding(.bottom, 28)
            }
        }
    }

    private var filterTitle: String {
        model.albums.first(where: { $0.id == albumFilter })?.title
            ?? albumFilter.capitalized
    }

    private var filterEmpty: some View {
        VStack(spacing: 10) {
            Image(systemName: "photo")
                .font(.system(size: 36))
                .foregroundStyle(Color.white.opacity(0.25))
            Text("No items in this album yet")
                .font(.subheadline.weight(.medium))
                .foregroundStyle(CumulousTheme.text)
            Text("Back up more media or open Library for everything.")
                .font(.footnote)
                .foregroundStyle(CumulousTheme.muted)
                .multilineTextAlignment(.center)
            Button("Show Library") {
                albumFilter = "library"
            }
            .buttonStyle(SecondaryButtonStyle())
            .padding(.horizontal, 40)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 40)
    }

    private var searchBar: some View {
        HStack {
            Image(systemName: "magnifyingglass").foregroundStyle(CumulousTheme.muted)
            TextField("Places, people, plants, context…", text: $search)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .foregroundStyle(CumulousTheme.text)
                .onSubmit { Task { await model.search(search) } }
            if !search.isEmpty {
                Button("Clear") {
                    search = ""
                    Task { await model.refresh() }
                }
                .font(.footnote)
                .foregroundStyle(CumulousTheme.accent)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color(white: 0.12)))
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
    }

    private var albumsStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                // Always lead with Library (full photo+video set)
                albumChip(id: "library", title: "Library", count: allLibraryItems.count)
                ForEach(model.albums) { alb in
                    // Skip redundant Recents if we have Library
                    if alb.id == "recents" { EmptyView() }
                    else {
                        albumChip(id: alb.id, title: alb.title, count: countForAlbum(alb))
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 8)
        }
    }

    private func countForAlbum(_ alb: PhotoAlbumDTO) -> Int {
        // Live counts from client filter (more accurate than stale server album counts)
        switch alb.id {
        case "videos": return allLibraryItems.filter(\.isVideo).count
        case "dual_mirror", "dual":
            let d = allLibraryItems.filter(\.isDualBacked)
            return d.isEmpty ? allLibraryItems.count : d.count
        case "people": return allLibraryItems.filter { !($0.people ?? []).isEmpty }.count
        case "places": return allLibraryItems.filter { !($0.placeName ?? "").isEmpty }.count
        case "screenshots": return allLibraryItems.filter(\.isScreenshot).count
        case "recents": return allLibraryItems.count
        default: return alb.count
        }
    }

    private func albumChip(id: String, title: String, count: Int) -> some View {
        Button {
            albumFilter = id
            search = ""
        } label: {
            VStack(spacing: 4) {
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(CumulousTheme.text)
                Text("\(count)")
                    .font(.system(size: 11))
                    .foregroundStyle(CumulousTheme.muted)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(albumFilter == id ? Color.white.opacity(0.14) : CumulousTheme.card)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(albumFilter == id ? CumulousTheme.accent.opacity(0.55) : CumulousTheme.cardStroke, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }

    private var daysList: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 18) {
                if model.days.isEmpty {
                    // Flat grid if days not ready
                    photoGrid(allLibraryItems)
                } else {
                    ForEach(model.days) { day in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(day.title)
                                .font(.system(size: 20, weight: .semibold))
                                .tracking(-0.3)
                                .foregroundStyle(CumulousTheme.text)
                                .padding(.horizontal, 16)
                            if let sub = day.subtitle, !sub.isEmpty {
                                Text(sub)
                                    .font(.footnote)
                                    .foregroundStyle(CumulousTheme.muted)
                                    .padding(.horizontal, 16)
                            }
                            photoGrid(day.items)
                        }
                    }
                }
            }
            .padding(.bottom, 28)
        }
    }

    private func photoGrid(_ items: [PhotoAssetDTO]) -> some View {
        // iOS Photos: 3 columns, tight gutters
        let columns = Array(repeating: GridItem(.flexible(), spacing: 2), count: 3)
        return LazyVGrid(columns: columns, spacing: 2) {
            ForEach(items) { asset in
                Button { selectedDigest = asset.digest } label: {
                    ZStack(alignment: .bottomTrailing) {
                        CachedAsyncImage(url: CumulousAPI.shared.thumbURL(asset.digest))
                            .aspectRatio(1, contentMode: .fill)
                            .frame(maxWidth: .infinity)
                            .clipped()
                        if asset.isVideo {
                            Image(systemName: "play.fill")
                                .font(.system(size: 11, weight: .bold))
                                .foregroundStyle(.white)
                                .padding(6)
                                .shadow(radius: 2)
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 0)
    }

    private var emptyState: some View {
        VStack(spacing: 14) {
            Image(systemName: "photo.on.rectangle.angled")
                .font(.system(size: 42))
                .foregroundStyle(Color(white: 0.35))
            Text("Your library lives here")
                .font(.headline)
                .foregroundStyle(CumulousTheme.text)
            Text("When photos and videos dual-mirror to the Mac, the full library appears here — same idea as the Photos app.")
                .font(.subheadline)
                .foregroundStyle(CumulousTheme.muted)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 36)
            if let err = model.error {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(CumulousTheme.danger)
                    .padding(.horizontal)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Model

@MainActor
final class PhotosLibraryModel: ObservableObject {
    @Published var days: [PhotoDayDTO] = []
    @Published var items: [PhotoAssetDTO] = []
    @Published var albums: [PhotoAlbumDTO] = []
    @Published var loading = false
    @Published var error: String?

    func refresh() async {
        loading = true
        error = nil
        defer { loading = false }
        do {
            async let d = CumulousAPI.shared.fetchDays()
            async let a = CumulousAPI.shared.fetchAlbums()
            // Pull a large page so filters (Videos, Dual, …) have full data
            async let l = CumulousAPI.shared.fetchLibrary(limit: 2000)
            days = try await d
            albums = try await a
            items = try await l
            _ = await CumulousAPI.shared.ping()
        } catch {
            self.error = "Can’t reach Mac Mini library. Same Wi‑Fi or Tailscale?"
            days = []; items = []; albums = []
        }
    }

    func search(_ q: String) async {
        loading = true
        defer { loading = false }
        do {
            items = try await CumulousAPI.shared.fetchLibrary(query: q, limit: 500)
        } catch {
            self.error = error.localizedDescription
        }
    }
}

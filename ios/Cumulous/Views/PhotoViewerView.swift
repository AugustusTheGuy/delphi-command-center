import SwiftUI
import UIKit
import AVKit

// MARK: - Apple Photos–style full-screen viewer
//
// Research notes (public UX only — Apple Photos source is proprietary):
// - Full-bleed black stage; photo aspect-fit to screen (contain), same as iOS Photos.
// - Horizontal swipe between assets (paging).
// - Swipe down to dismiss (interactive).
// - Bottom filmstrip: very small square thumbs, ~2pt gap, current item centered
//   with a thin (~1.5pt) white border (Photos scrubber language).
// - Scrubbing the filmstrip loads the touched thumb into the main stage.
// - Cumulous deltas (explicit CEO): red traffic-light close top-left; deeper tags
//   panel accessible without replacing the Photos chrome.

struct PhotoViewerContainer: View {
    let assets: [PhotoAssetDTO]
    let startDigest: String
    @Environment(\.dismiss) private var dismiss

    private var startIndex: Int {
        assets.firstIndex(where: { $0.digest == startDigest }) ?? 0
    }

    var body: some View {
        PhotoViewerPagedView(assets: assets, initialIndex: startIndex, onClose: { dismiss() })
    }
}

struct PhotoViewerPagedView: View {
    let assets: [PhotoAssetDTO]
    let initialIndex: Int
    var onClose: () -> Void

    @State private var index: Int = 0
    /// Controls (close / filmstrip) only — never metadata. Like Photos: chrome can fade.
    @State private var showChrome = true
    /// Metadata / EXIF-style details — hidden until user pulls up or taps Info (Photos pattern).
    @State private var showTags = false
    @State private var dragOffset: CGFloat = 0
    @State private var tagsCache: [String: PhotoTagsDTO] = [:]

    /// Filmstrip cell size — iOS Photos scrubber is ~tiny square (~36–44pt).
    private let stripSize: CGFloat = 40
    private let stripGap: CGFloat = 2
    private let selectBorder: CGFloat = 1.5

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.black.ignoresSafeArea()

                // Main paging stage (full screen like Photos)
                TabView(selection: $index) {
                    ForEach(Array(assets.enumerated()), id: \.element.digest) { i, asset in
                        PhotoPageView(asset: asset)
                            .tag(i)
                            .frame(width: geo.size.width, height: geo.size.height)
                    }
                }
                .tabViewStyle(.page(indexDisplayMode: .never))
                .ignoresSafeArea()
                .offset(y: dragOffset)
                .gesture(dismissDrag)
                .onTapGesture {
                    // Tap photo: toggle chrome only — never auto-open metadata
                    withAnimation(.easeInOut(duration: 0.18)) {
                        if showTags {
                            showTags = false
                        } else {
                            showChrome.toggle()
                        }
                    }
                }
                // Swipe up on photo → reveal details (iOS Photos “pull up for info”)
                .simultaneousGesture(
                    DragGesture(minimumDistance: 40)
                        .onEnded { v in
                            let up = v.translation.height < -70 && abs(v.translation.height) > abs(v.translation.width)
                            if up {
                                withAnimation(.easeInOut(duration: 0.22)) {
                                    showChrome = true
                                    showTags = true
                                }
                                Task { await loadTags(for: index) }
                            }
                        }
                )

                // Top chrome: close + optional Info only (no filename / EXIF)
                if showChrome {
                    VStack {
                        topBar
                        Spacer()
                    }
                    .transition(.opacity)
                }

                // Bottom: filmstrip always with chrome; tags only if user opened them
                if showChrome {
                    VStack(spacing: 0) {
                        Spacer()
                        if showTags {
                            tagsPanel
                                .transition(.move(edge: .bottom).combined(with: .opacity))
                                .gesture(
                                    DragGesture(minimumDistance: 24)
                                        .onEnded { v in
                                            if v.translation.height > 50 {
                                                withAnimation(.easeInOut(duration: 0.2)) { showTags = false }
                                            }
                                        }
                                )
                        }
                        filmstrip
                            .padding(.bottom, max(geo.safeAreaInsets.bottom, 8))
                    }
                    .transition(.opacity)
                }
            }
        }
        .statusBarHidden(!showChrome)
        .onAppear {
            index = min(max(0, initialIndex), max(0, assets.count - 1))
            // Photo only on open — do not prefetch tags into UI until user asks
            Task { await prefetchAround(index) }
        }
        .onChange(of: index) { new in
            // Changing photo: photo-only again (hide details)
            showTags = false
            Task { await prefetchAround(new) }
        }
    }

    // MARK: - Top bar (Photos-like + Cumulous red close) — no photo metadata text

    private var topBar: some View {
        HStack(spacing: 12) {
            Button(action: onClose) {
                Circle()
                    .fill(Color(red: 1.0, green: 0.37, blue: 0.34))
                    .frame(width: 14, height: 14)
                    .overlay(Circle().stroke(Color(red: 0.88, green: 0.27, blue: 0.24), lineWidth: 0.5))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Close")
            .padding(.leading, 4)

            Spacer(minLength: 0)

            Button {
                withAnimation(.easeInOut(duration: 0.2)) {
                    showTags.toggle()
                    if showTags {
                        Task { await loadTags(for: index) }
                    }
                }
            } label: {
                Image(systemName: showTags ? "info.circle.fill" : "info.circle")
                    .font(.system(size: 18, weight: .regular))
                    .foregroundStyle(.white.opacity(0.92))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Show photo details")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(
            LinearGradient(
                colors: [Color.black.opacity(0.45), Color.black.opacity(0)],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea(edges: .top)
        )
    }

    // MARK: - Filmstrip (Photos scrubber clone)

    private var filmstrip: some View {
        GeometryReader { g in
            ScrollViewReader { proxy in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: stripGap) {
                        // Leading inset so first item can center
                        Color.clear.frame(width: max(0, (g.size.width - stripSize) / 2))
                        ForEach(Array(assets.enumerated()), id: \.element.digest) { i, asset in
                            filmCell(asset: asset, selected: i == index)
                                .id(asset.digest)
                                .onTapGesture {
                                    withAnimation(.easeInOut(duration: 0.15)) { index = i }
                                }
                        }
                        Color.clear.frame(width: max(0, (g.size.width - stripSize) / 2))
                    }
                    .padding(.vertical, 6)
                }
                .background(
                    LinearGradient(
                        colors: [Color.black.opacity(0), Color.black.opacity(0.72)],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .onChange(of: index) { new in
                    guard assets.indices.contains(new) else { return }
                    withAnimation(.easeInOut(duration: 0.18)) {
                        proxy.scrollTo(assets[new].digest, anchor: .center)
                    }
                }
                .onAppear {
                    if assets.indices.contains(index) {
                        proxy.scrollTo(assets[index].digest, anchor: .center)
                    }
                }
                // Scrub: as user scrolls, update index when a cell is nearest center
                .simultaneousGesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { _ in }
                )
            }
        }
        .frame(height: stripSize + 20)
        .background(Color.black.opacity(0.55))
        // Preferential loading while scrubbing via preference-free continuous scroll observer
        .overlay(FilmstripScrollObserver(assets: assets, stripSize: stripSize, stripGap: stripGap) { nearest in
            if nearest != index, assets.indices.contains(nearest) {
                index = nearest
            }
        })
    }

    private func filmCell(asset: PhotoAssetDTO, selected: Bool) -> some View {
        ZStack {
            CachedAsyncImage(url: CumulousAPI.shared.thumbURL(asset.digest))
                .aspectRatio(1, contentMode: .fill)
                .frame(width: stripSize, height: stripSize)
                .clipped()
            if (asset.mediaType ?? "") == "video" {
                Image(systemName: "play.fill")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(.white.opacity(0.9))
                    .shadow(radius: 1)
            }
        }
        .frame(width: stripSize, height: stripSize)
        .overlay(
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .stroke(selected ? Color.white : Color.clear, lineWidth: selectBorder)
        )
        .clipShape(RoundedRectangle(cornerRadius: 2, style: .continuous))
        .scaleEffect(selected ? 1.06 : 1.0)
        .animation(.easeInOut(duration: 0.12), value: selected)
        .accessibilityLabel(selected ? "Current photo" : (asset.name ?? "Photo"))
    }

    // MARK: - Tags (Cumulous deeper metadata)

    private var tagsPanel: some View {
        let asset = assets.indices.contains(index) ? assets[index] : nil
        let tags = asset.flatMap { tagsCache[$0.digest] }
        return VStack(alignment: .leading, spacing: 8) {
            tagRow("When", tags?.capturedAtIso ?? asset?.capturedAtIso)
            tagRow("Where", tags?.location?.placeName ?? asset?.placeName)
            tagRow("Setting", tags?.setting ?? asset?.setting)
            tagRow("Context", tags?.context ?? asset?.context)
            tagRow("People", labelList(tags?.people ?? asset?.people))
            tagRow("Plants", labelList(tags?.plants ?? asset?.plants))
            tagRow("Objects", labelList(tags?.objects ?? asset?.objects))
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.ultraThinMaterial.opacity(0.4))
        .background(Color(white: 0.08).opacity(0.92))
    }

    private func tagRow(_ title: String, _ value: String?) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(title)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Color(white: 0.55))
                .frame(width: 68, alignment: .leading)
            Text((value?.isEmpty == false) ? value! : "—")
                .font(.system(size: 13))
                .foregroundStyle(.white.opacity(0.92))
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func labelList(_ items: [TagLabelDTO]?) -> String? {
        guard let items, !items.isEmpty else { return nil }
        return items.map(\.label).joined(separator: ", ")
    }

    // MARK: - Dismiss drag (swipe down like Photos)

    private var dismissDrag: some Gesture {
        DragGesture(minimumDistance: 20)
            .onChanged { v in
                if v.translation.height > 0, abs(v.translation.height) > abs(v.translation.width) {
                    dragOffset = v.translation.height
                }
            }
            .onEnded { v in
                if v.translation.height > 120 || v.predictedEndTranslation.height > 220 {
                    onClose()
                } else {
                    withAnimation(.spring(response: 0.28, dampingFraction: 0.86)) {
                        dragOffset = 0
                    }
                }
            }
    }

    // MARK: - Prefetch / tags

    private func loadTags(for i: Int) async {
        guard assets.indices.contains(i) else { return }
        let dig = assets[i].digest
        if tagsCache[dig] != nil { return }
        if let t = try? await CumulousAPI.shared.fetchTags(digest: dig) {
            tagsCache[dig] = t
        }
    }

    private func prefetchAround(_ i: Int) async {
        for j in [i - 1, i + 1, i + 2] where assets.indices.contains(j) {
            let url = CumulousAPI.shared.mediaURL(assets[j].digest) ?? CumulousAPI.shared.thumbURL(assets[j].digest)
            _ = await CumulousAPI.shared.loadImage(url: url)
        }
    }
}

// MARK: - Single page (aspect-fit full screen)

struct PhotoPageView: View {
    let asset: PhotoAssetDTO
    @State private var image: UIImage?
    @State private var scale: CGFloat = 1
    @State private var lastScale: CGFloat = 1

    var body: some View {
        ZStack {
            Color.black
            if (asset.mediaType ?? "") == "video" {
                if let url = CumulousAPI.shared.mediaURL(asset.digest) {
                    VideoPlayer(player: AVPlayer(url: url))
                        .aspectRatio(contentMode: .fit)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            } else if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .scaleEffect(scale)
                    .gesture(
                        MagnificationGesture()
                            .onChanged { v in scale = min(4, max(1, lastScale * v)) }
                            .onEnded { _ in
                                lastScale = scale
                                if scale < 1.05 {
                                    withAnimation { scale = 1; lastScale = 1 }
                                }
                            }
                    )
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ProgressView().tint(.white)
                CachedAsyncImage(url: CumulousAPI.shared.thumbURL(asset.digest))
                    .scaledToFit()
                    .opacity(0.35)
            }
        }
        .task {
            let full = await CumulousAPI.shared.loadImage(url: CumulousAPI.shared.mediaURL(asset.digest))
            if let full { image = full }
            else {
                image = await CumulousAPI.shared.loadImage(url: CumulousAPI.shared.thumbURL(asset.digest))
            }
        }
    }
}

// MARK: - Filmstrip center tracking (UIKit bridge)

/// Observes the nearest filmstrip cell to screen center while the user scrubs quickly.
private struct FilmstripScrollObserver: UIViewRepresentable {
    let assets: [PhotoAssetDTO]
    let stripSize: CGFloat
    let stripGap: CGFloat
    var onNearest: (Int) -> Void

    func makeUIView(context: Context) -> UIView {
        let v = UIView(frame: .zero)
        v.isUserInteractionEnabled = false
        context.coordinator.attach(to: v, assets: assets, stripSize: stripSize, stripGap: stripGap, onNearest: onNearest)
        return v
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        context.coordinator.assets = assets
        context.coordinator.onNearest = onNearest
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator {
        var assets: [PhotoAssetDTO] = []
        var stripSize: CGFloat = 40
        var stripGap: CGFloat = 2
        var onNearest: (Int) -> Void = { _ in }
        private weak var scrollView: UIScrollView?
        private var displayLink: CADisplayLink?
        private var lastIndex: Int = -1

        func attach(to host: UIView, assets: [PhotoAssetDTO], stripSize: CGFloat, stripGap: CGFloat, onNearest: @escaping (Int) -> Void) {
            self.assets = assets
            self.stripSize = stripSize
            self.stripGap = stripGap
            self.onNearest = onNearest
            DispatchQueue.main.async { [weak self, weak host] in
                guard let self, let host else { return }
                if let sv = self.findScrollView(from: host) {
                    self.scrollView = sv
                    self.startLink()
                }
            }
        }

        private func startLink() {
            displayLink?.invalidate()
            let link = CADisplayLink(target: self, selector: #selector(tick))
            link.add(to: .main, forMode: .common)
            displayLink = link
        }

        @objc private func tick() {
            guard let sv = scrollView, !assets.isEmpty else { return }
            // Prefer parent horizontal scroll view content offset
            let mid = sv.contentOffset.x + sv.bounds.width / 2
            let cell = stripSize + stripGap
            // Account for leading inset ~ half width
            let leading = max(0, (sv.bounds.width - stripSize) / 2)
            let raw = (mid - leading - stripSize / 2) / cell
            let i = Int(round(raw))
            let clamped = max(0, min(assets.count - 1, i))
            if clamped != lastIndex {
                lastIndex = clamped
                onNearest(clamped)
            }
        }

        private func findScrollView(from view: UIView) -> UIScrollView? {
            var v: UIView? = view.superview
            while let cur = v {
                if let sv = cur as? UIScrollView, sv.contentSize.width > sv.bounds.width + 1 {
                    return sv
                }
                // search siblings of ancestors
                if let parent = cur.superview {
                    for sub in parent.subviews {
                        if let sv = sub as? UIScrollView, sv.contentSize.width > sv.bounds.width + 1 {
                            return sv
                        }
                        if let found = deepScroll(sub) { return found }
                    }
                }
                v = cur.superview
            }
            return nil
        }

        private func deepScroll(_ view: UIView) -> UIScrollView? {
            if let sv = view as? UIScrollView, sv.contentSize.width > sv.bounds.width + 1 { return sv }
            for s in view.subviews {
                if let f = deepScroll(s) { return f }
            }
            return nil
        }

        deinit { displayLink?.invalidate() }
    }
}

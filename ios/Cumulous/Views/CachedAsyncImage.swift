import SwiftUI
import UIKit

/// In-app image loader (not Safari). Caches thumbs for the Photos clone.
struct CachedAsyncImage: View {
    let url: URL?
    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else if failed {
                Rectangle().fill(Color(white: 0.14))
                    .overlay(Image(systemName: "photo").foregroundStyle(Color(white: 0.35)))
            } else {
                Rectangle().fill(Color(white: 0.12))
                    .overlay(ProgressView().tint(.white.opacity(0.5)))
            }
        }
        .task(id: url?.absoluteString) {
            failed = false
            image = await CumulousAPI.shared.loadImage(url: url)
            if image == nil { failed = true }
        }
    }
}

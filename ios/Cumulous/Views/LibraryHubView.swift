import SwiftUI

/// Photos-app style top-level: Library is the full photo+video collection (default).
/// Kept as a thin shell so tab label can stay “Library” while reusing PhotosLibraryView.
struct LibraryHubView: View {
    var body: some View {
        PhotosLibraryView()
    }
}

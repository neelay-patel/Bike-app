import SwiftUI
import UIKit
import WebKit

/// The collectible ride card, drawn by the server (GET /v1/rides/{id}/card, rideengine/card/ride_card.py)
/// so the screen and the shared image are the same design. The app's own bundled fonts are embedded
/// into the page, so it works offline and asks nothing of Google. The route is already cut around home.
@MainActor
final class CardRenderer: NSObject, ObservableObject, WKNavigationDelegate {
    static let size = CGSize(width: 360, height: 640)

    let webView: WKWebView
    @Published private(set) var isLoaded = false
    @Published private(set) var failed: String?

    override init() {
        webView = WKWebView(frame: CGRect(origin: .zero, size: Self.size), configuration: WKWebViewConfiguration())
        super.init()
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        webView.scrollView.isScrollEnabled = false
        webView.navigationDelegate = self
    }

    func load(rideId: String) async {
        await load { try await APIClient().cardHTML(rideId) }
    }

    /// Load any server-drawn card page (ride card, rider card). `force` redraws one already shown.
    func load(force: Bool = false, _ fetch: () async throws -> String) async {
        guard force || !isLoaded else { return }
        do {
            let html = try await fetch()
            failed = nil
            webView.loadHTMLString(Self.embedFonts(html), baseURL: nil)
        } catch {
            failed = error.localizedDescription
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        isLoaded = true
    }

    /// The card as an image for sharing: 1080 x 1920, on white.
    func image() async -> UIImage? {
        let config = WKSnapshotConfiguration()
        config.rect = CGRect(origin: .zero, size: Self.size)
        guard let shot = try? await webView.takeSnapshot(configuration: config) else { return nil }
        // 1080 x 1920 pixels (9:16), whatever the screen's scale.
        let pixels = CGRect(x: 0, y: 0, width: 1080, height: 1920)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        return UIGraphicsImageRenderer(size: pixels.size, format: format).image { ctx in
            UIColor.white.setFill()
            ctx.fill(pixels)
            shot.draw(in: pixels)
        }
    }

    /// The page names font files (fonts=local); swap each for the bundled file's data.
    private static let fontData: [String: String] = {
        var out: [String: String] = [:]
        for name in ["Doto-Black", "InstrumentSerif-Regular", "IBMPlexMono-Regular", "IBMPlexMono-Medium"] {
            if let url = Bundle.main.url(forResource: name, withExtension: "ttf"), let data = try? Data(contentsOf: url) {
                out["\(name).ttf"] = "data:font/ttf;base64," + data.base64EncodedString()
            }
        }
        return out
    }()

    static func embedFonts(_ html: String) -> String {
        fontData.reduce(html) { page, font in page.replacingOccurrences(of: "url('\(font.key)')", with: "url('\(font.value)')") }
    }
}

private struct CardWebView: UIViewRepresentable {
    let renderer: CardRenderer
    func makeUIView(context: Context) -> WKWebView { renderer.webView }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}

/// The card at the top of a ride's screen, scaled to fit the width.
struct RideCard: View {
    @ObservedObject var renderer: CardRenderer
    let rideId: String

    var body: some View {
        CardFrame(renderer: renderer).task { await renderer.load(rideId: rideId) }
    }
}

/// Any 360 x 640 card page, scaled to fit the width.
struct CardFrame: View {
    @ObservedObject var renderer: CardRenderer

    var body: some View {
        GeometryReader { geo in
            let scale = min(1, geo.size.width / CardRenderer.size.width)
            CardWebView(renderer: renderer)
                .frame(width: CardRenderer.size.width, height: CardRenderer.size.height)
                .scaleEffect(scale, anchor: .topLeading)
                .offset(x: max(0, (geo.size.width - CardRenderer.size.width) / 2))
                .opacity(renderer.isLoaded ? 1 : 0)
                .overlay {
                    if let failed = renderer.failed {
                        Text(failed).font(Theme.text(13)).foregroundStyle(Theme.heart).padding()
                    } else if !renderer.isLoaded {
                        ProgressView().tint(Theme.cobalt)
                    }
                }
        }
        .aspectRatio(CardRenderer.size.width / CardRenderer.size.height, contentMode: .fit)
        .frame(maxWidth: CardRenderer.size.width)
        .frame(maxWidth: .infinity)
        .accessibilityLabel("Card")
    }
}

/// The system share sheet for the card image.
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

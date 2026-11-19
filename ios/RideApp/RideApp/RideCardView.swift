import SwiftUI
import UIKit
import WebKit

/// The collectible ride card, drawn by the server (GET /v1/rides/{id}/card, rideengine/card/ride_card.py)
/// so the screen and the shared image are the same design. The app's own bundled fonts are embedded
/// into the page, so it works offline and asks nothing of Google. The route is already cut around home.
@MainActor
final class CardRenderer: NSObject, ObservableObject, WKNavigationDelegate {
    /// Cards are 360 wide; a ride card is as tall as it needs (an indoor one has no map), measured on load.
    static let size = CGSize(width: 360, height: 640)

    let webView: WKWebView
    @Published private(set) var isLoaded = false
    @Published private(set) var failed: String?
    @Published private(set) var size = CardRenderer.size
    var onResize: ((CGSize) -> Void)?
    /// The page as last drawn, to draw it again if iOS throws the web view's content away in the background.
    private var page: String?

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
            page = Self.embedFonts(html)
            webView.loadHTMLString(page!, baseURL: nil)
        } catch {
            failed = error.localizedDescription
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        Task {
            // The page's height once its fonts are in (the name is fitted to the header then too).
            let height = try? await webView.callAsyncJavaScript(
                "await document.fonts.ready; return document.body.scrollHeight", contentWorld: .page) as? Double
            if let height, height > 100, abs(height - size.height) > 0.5 {
                size = CGSize(width: Self.size.width, height: height.rounded(.up))
                webView.frame.size = size
                onResize?(size)
            }
            isLoaded = true
        }
    }

    /// iOS can end a web view's content process (in the background, short of memory), leaving it blank
    /// though the card counts as drawn. Draw it again.
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        guard let page else { return }
        webView.loadHTMLString(page, baseURL: nil)
    }

    /// The card as an image for sharing: 1080 pixels wide (1080 x 1920 for a 9:16 card), on white.
    func image() async -> UIImage? {
        let config = WKSnapshotConfiguration()
        config.rect = CGRect(origin: .zero, size: size)
        guard let shot = try? await webView.takeSnapshot(configuration: config) else { return nil }
        // 1080 pixels wide whatever the screen's scale; as tall as the card.
        let pixels = CGRect(x: 0, y: 0, width: 1080, height: (1080 * size.height / size.width).rounded())
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
            .replacingOccurrences(of: "src=\"indoor-mark.png\"", with: "src=\"\(indoorMark)\"")
    }

    /// The indoor ride card's mark: the same icon as the collection's small indoor cards.
    private static let indoorMark: String = {
        let config = UIImage.SymbolConfiguration(pointSize: 52, weight: .regular)
        guard let symbol = UIImage(systemName: MiniCard.indoorSymbol, withConfiguration: config)?
            .withTintColor(UIColor(Theme.cobaltSoft), renderingMode: .alwaysOriginal) else { return "" }
        let format = UIGraphicsImageRendererFormat()
        format.scale = 3
        let png = UIGraphicsImageRenderer(size: symbol.size, format: format).image { _ in symbol.draw(at: .zero) }.pngData()
        return png.map { "data:image/png;base64," + $0.base64EncodedString() } ?? ""
    }()
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
    var entrance = false     // a new effort: a little spring and a sheen as it lands

    var body: some View {
        CardFrame(renderer: renderer, entrance: entrance).task(id: rideId) { await renderer.load(rideId: rideId) }
    }
}

/// Any 360 x 640 card page, scaled to fit the width.
struct CardFrame: View {
    @ObservedObject var renderer: CardRenderer
    var entrance = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geo in
            let scale = min(1, geo.size.width / CardRenderer.size.width)
            CardWebView(renderer: renderer)
                .frame(width: renderer.size.width, height: renderer.size.height)
                .overlay {
                    if entrance {
                        // The page draws the card 12 pt in from its edges, with 14 pt corners.
                        Sheen(run: renderer.isLoaded)
                            .mask(RoundedRectangle(cornerRadius: 14, style: .continuous).padding(12))
                    }
                }
                .scaleEffect(scale, anchor: .topLeading)
                .offset(x: max(0, (geo.size.width - CardRenderer.size.width) / 2))
                .opacity(renderer.isLoaded ? 1 : 0)
                .scaleEffect(entrance && !reduceMotion && !renderer.isLoaded ? 0.92 : 1, anchor: .center)
                .animation(entrance ? .spring(response: 0.5, dampingFraction: 0.68) : nil, value: renderer.isLoaded)
                .overlay {
                    if let failed = renderer.failed {
                        Text(failed).font(Theme.text(13)).foregroundStyle(Theme.heart).padding()
                    } else if !renderer.isLoaded {
                        ProgressView().tint(Theme.cobalt)
                    }
                }
        }
        .aspectRatio(renderer.size.width / renderer.size.height, contentMode: .fit)
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

import SwiftUI

/// The app's look (direction D). Values copied from design/tokens.json; tests/test_design_tokens.py
/// checks they still match. Rules for using them: docs/design.md.
enum Theme {
    // MARK: Colours
    static let ground = Color(hex: 0xF3EEEE)
    static let surface = Color(hex: 0xFBF8F8)
    static let surfaceSelected = Color(hex: 0xEDE5E6)
    static let line = Color(hex: 0xE6DEDF)
    static let ink = Color(hex: 0x1B1618)
    static let inkSoft = Color(hex: 0x3D3538)
    static let inkMuted = Color(hex: 0x5E5559)
    static let label = Color(hex: 0x6E6468)
    static let panel = Color(hex: 0x141113)
    static let panelLine = Color(hex: 0x3A3336)
    static let panelLabel = Color(hex: 0xBDB4B7)
    static let cobalt = Color(hex: 0x1D3A8C)
    static let cobaltSoft = Color(hex: 0xC9D3F2)
    static let heart = Color(hex: 0x7C1E3E)
    static let sand = Color(hex: 0xF1E2B6)
    static let strip = Color(hex: 0x3A3537)

    // MARK: Type
    /// Instrument Serif: screen and ride titles only.
    static func heading(_ size: CGFloat) -> Font {
        .custom("InstrumentSerif-Regular", size: size, relativeTo: .largeTitle)
    }

    /// IBM Plex Sans: everything people read.
    static func text(_ size: CGFloat = 15, _ weight: Font.Weight = .regular) -> Font {
        let name: String
        switch weight {
        case .semibold, .bold, .heavy, .black: name = "IBMPlexSans-SmBld"
        case .medium: name = "IBMPlexSans-Medm"
        default: name = "IBMPlexSans"
        }
        return .custom(name, size: size, relativeTo: .body)
    }

    /// IBM Plex Mono: small labels and details.
    static func mono(_ size: CGFloat = 12) -> Font {
        .custom("IBMPlexMono-Regular", size: size, relativeTo: .caption)
    }

    /// Doto dot-matrix: hero numbers only (month total, ride totals, insight figure).
    static func hero(_ size: CGFloat) -> Font {
        .custom("Doto-Black", size: size, relativeTo: .largeTitle)
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255)
    }
}

/// Upper-case, tracked mono label: "OCTOBER 2026", "AVG HEART RATE".
struct MonoLabel: View {
    let text: String
    var color: Color = Theme.label

    init(_ text: String, color: Color = Theme.label) {
        self.text = text
        self.color = color
    }

    var body: some View {
        Text(text.uppercased())
            .font(Theme.mono(11))
            .tracking(11 * 0.16)
            .foregroundStyle(color)
    }
}

/// Light content card on the porcelain ground.
struct SurfaceCard: ViewModifier {
    var radius: CGFloat = 22

    func body(content: Content) -> some View {
        content
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous).stroke(Theme.line, lineWidth: 1))
    }
}

extension View {
    func surfaceCard(radius: CGFloat = 22) -> some View { modifier(SurfaceCard(radius: radius)) }
}

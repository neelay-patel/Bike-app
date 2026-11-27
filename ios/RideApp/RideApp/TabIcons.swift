import SwiftUI
import UIKit

/// The tab bar's own marks (27 Nov 2026, canvas "Third pass"): Efforts is an effort's shape (easy, a push,
/// settle), drawn as a line that takes the tab's tint; Coach is a fresh effort (a ride line and a plus) in
/// colour on the cobalt disc, the same everywhere the coach speaks.
enum TabIcons {
    static let yellow = UIColor(red: 0xF2 / 255, green: 0xC2 / 255, blue: 0x30 / 255, alpha: 1)
    static let pink = UIColor(red: 0xF2 / 255, green: 0xA3 / 255, blue: 0xB8 / 255, alpha: 1)
    static let cobalt = UIColor(red: 0x1D / 255, green: 0x3A / 255, blue: 0x8C / 255, alpha: 1)

    /// The effort line, in a 24-unit box.
    static func effortPath(scale s: CGFloat) -> UIBezierPath {
        let p = UIBezierPath()
        let pts: [(CGFloat, CGFloat)] = [(3, 16), (6.5, 16), (8.5, 12), (11, 14), (14, 7), (16.5, 16), (18, 13), (21, 13)]
        p.move(to: CGPoint(x: pts[0].0 * s, y: pts[0].1 * s))
        for q in pts.dropFirst() { p.addLine(to: CGPoint(x: q.0 * s, y: q.1 * s)) }
        p.lineCapStyle = .round
        p.lineJoinStyle = .round
        return p
    }

    /// The fresh-effort line and its plus, in a 30-unit box (the disc's).
    static func freshPaths(scale s: CGFloat) -> (line: UIBezierPath, plus: UIBezierPath) {
        func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: (x + 3) * s, y: (y + 3.5) * s) }
        let line = UIBezierPath()
        line.move(to: pt(3, 19))
        line.addCurve(to: pt(10.5, 14.5), controlPoint1: pt(5.5, 15), controlPoint2: pt(8, 18.5))
        line.addCurve(to: pt(17, 11), controlPoint1: pt(13, 10.5), controlPoint2: pt(15, 12))
        let plus = UIBezierPath()
        plus.move(to: pt(19, 3)); plus.addLine(to: pt(19, 7))
        plus.move(to: pt(17, 5)); plus.addLine(to: pt(21, 5))
        for p in [line, plus] { p.lineCapStyle = .round; p.lineJoinStyle = .round }
        return (line, plus)
    }

    /// Efforts' tab image: a template, so the tab bar tints it.
    static func efforts(size: CGFloat = 26) -> UIImage {
        let img = UIGraphicsImageRenderer(size: CGSize(width: size, height: size)).image { _ in
            let p = effortPath(scale: size / 24)
            p.lineWidth = 1.8 * size / 24
            UIColor.black.setStroke()
            p.stroke()
        }
        return img.withRenderingMode(.alwaysTemplate)
    }

    /// Coach's disc as an image, in its own colours (the tab bar leaves it as drawn).
    static func coach(size: CGFloat = 26) -> UIImage {
        let img = UIGraphicsImageRenderer(size: CGSize(width: size, height: size)).image { _ in
            let s = size / 30
            cobalt.setFill()
            UIBezierPath(ovalIn: CGRect(x: s, y: s, width: 28 * s, height: 28 * s)).fill()
            let (line, plus) = freshPaths(scale: s)
            line.lineWidth = 2.3 * s
            plus.lineWidth = 2.3 * s
            yellow.setStroke(); line.stroke()
            pink.setStroke(); plus.stroke()
        }
        return img.withRenderingMode(.alwaysOriginal)
    }
}

/// The coach's face: the fresh effort on the cobalt disc, at any size.
struct CoachDisc: View {
    var size: CGFloat = 32
    var body: some View {
        Image(uiImage: TabIcons.coach(size: size))
            .resizable()
            .interpolation(.high)
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

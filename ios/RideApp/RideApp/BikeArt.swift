import SwiftUI
import UIKit

// The rider's own bike, drawn in code from real geometry (millimetres), so it's sharp at any size:
// the big drawing in the builder and Binder, and the nano version on the Rides tab.
// Type, frame colour, bar-tape colour and tyres come from the avatar spec (bike, bike_color,
// bike_accent, tyres; rideengine/card/avatar.py).

/// What to draw.
struct BikeSpec: Equatable, Codable {
    var type = "road"        // road, gravel, mtb, indoor
    var frame = "carbon"     // a kit colour, carbon or titanium
    var accent = "sand"      // bar tape, decals, bottle cap
    var tyres = "black"      // black or tan walls

    init(type: String = "road", frame: String = "carbon", accent: String = "sand", tyres: String = "black") {
        (self.type, self.frame, self.accent, self.tyres) = (type, frame, accent, tyres)
    }

    /// From the avatar spec (nil: the default bike).
    init(avatar: [String: String]?) {
        self.init()
        guard let a = avatar else { return }
        type = a["bike"] ?? type
        frame = a["bike_color"] ?? frame
        accent = a["bike_accent"] ?? accent
        tyres = a["tyres"] ?? tyres
    }

    /// "Road · carbon", for labels.
    var label: String {
        let kind = ["road": "Road", "gravel": "Gravel", "mtb": "Mountain", "indoor": "Indoor trainer"][type] ?? type.capitalized
        return "\(kind) · \(frame)"
    }

    /// Remembered so the tab icon is right at launch, before the server answers.
    static var saved: BikeSpec {
        get {
            guard let data = UserDefaults.standard.data(forKey: "bike.spec"),
                  let spec = try? JSONDecoder().decode(BikeSpec.self, from: data) else { return BikeSpec() }
            return spec
        }
        set { UserDefaults.standard.set(try? JSONEncoder().encode(newValue), forKey: "bike.spec") }
    }
}

/// The bike's colours. Copies of avatar.py's FRAME (which includes KIT) and TYRES; test_design.py checks they match.
enum BikePalette {
    static let frame: [String: UInt32] = [
        "carbon": 0x26252A, "titanium": 0xB9B4AC,
        "cobalt": 0x1D3A8C, "wine": 0x7C1E3E, "ink": 0x1B1618, "sand": 0xF1E2B6, "sky": 0x4A86E8,
        "red": 0xD7263D, "green": 0x3A9D4A, "yellow": 0xF3C623, "white": 0xFBF8F8, "orange": 0xE9772E,
    ]
    static let tyres: [String: UInt32] = ["black": 0x1C1A1B, "tan": 0xC49A63]

    static func color(_ name: String, in table: [String: UInt32], fallback: UInt32) -> UIColor {
        UIColor(rgb: table[name] ?? fallback)
    }
}

/// The bike, drawn to fit its frame (keeps its proportions, sits on the bottom edge).
/// icon: the nano version: thicker lines, no spokes, chain or bottle. mono: one colour (template icons).
struct BikeArt: View {
    var spec: BikeSpec
    var icon = false
    var mono: Color? = nil

    var body: some View {
        Canvas { ctx, size in
            BikePainter(spec: spec, icon: icon, mono: mono.map { UIColor($0) }).draw(in: &ctx, size: size)
        }
        .accessibilityLabel("Your bike: \(spec.label)")
    }
}

/// The Rides tab icon: your bike in colour when the tab is selected, a one-colour outline when it isn't.
enum BikeIcon {
    @MainActor
    static func image(_ spec: BikeSpec, selected: Bool) -> UIImage {
        let side: CGFloat = 30
        let view = BikeArt(spec: spec, icon: true, mono: selected ? nil : .black).frame(width: side, height: side)
        let renderer = ImageRenderer(content: view)
        renderer.scale = UIScreen.main.scale
        let image = renderer.uiImage ?? UIImage()
        return image.withRenderingMode(selected ? .alwaysOriginal : .alwaysTemplate)
    }
}

// MARK: - Geometry

private struct V {
    var x: CGFloat, y: CGFloat
    init(_ x: CGFloat, _ y: CGFloat) { self.x = x; self.y = y }
    static func + (a: V, b: V) -> V { V(a.x + b.x, a.y + b.y) }
    static func - (a: V, b: V) -> V { V(a.x - b.x, a.y - b.y) }
    static func * (a: V, k: CGFloat) -> V { V(a.x * k, a.y * k) }
    var length: CGFloat { (x * x + y * y).squareRoot() }
    var unit: V { let l = max(length, 0.0001); return V(x / l, y / l) }
    /// Rotated a quarter turn anticlockwise (y is up).
    var left: V { V(-y, x) }
    static func polar(_ r: CGFloat, _ a: CGFloat) -> V { V(r * cos(a), r * sin(a)) }
    func rotated(_ a: CGFloat) -> V { V(x * cos(a) - y * sin(a), x * sin(a) + y * cos(a)) }
}

private func rad(_ deg: CGFloat) -> CGFloat { deg * .pi / 180 }

/// Chainring or cog pitch radius for a tooth count (½" chain).
private func pitchRadius(_ teeth: Int) -> CGFloat { 12.7 / (2 * sin(.pi / CGFloat(teeth))) }

/// One bike's frame and parts, in millimetres, rear axle at the origin, y up.
private struct Geometry {
    enum Bar { case drop, flat }
    let type: String
    let chainstay, bbDrop, seatAngle, saddleHeight, stack, reach, headAngle, headTube, forkOffset: CGFloat
    let topJoin, stayJoin: CGFloat          // where the top tube and seat stays meet the seat tube (from the BB)
    let tyreWidth, rimDepth: CGFloat
    let stemLength, stemAngle, spacers: CGFloat
    let bar: Bar
    let rings: [Int]
    let cogs: [Int]
    let spokes: Int
    let suspension: Bool
    let dropper: Bool
    let tread: Int                           // 0 slick, otherwise knobs around the tyre
    let longCage: Bool

    static func of(_ type: String) -> Geometry {
        switch type {
        case "gravel":
            return Geometry(type: type, chainstay: 425, bbDrop: 75, seatAngle: 73.5, saddleHeight: 735, stack: 592,
                            reach: 382, headAngle: 71.5, headTube: 165, forkOffset: 50, topJoin: 470, stayJoin: 395,
                            tyreWidth: 44, rimDepth: 26, stemLength: 90, stemAngle: -6, spacers: 25, bar: .drop,
                            rings: [42], cogs: [44, 38, 32, 28, 24, 21, 19, 17, 15, 13, 11, 10], spokes: 28,
                            suspension: false, dropper: false, tread: 110, longCage: true)
        case "mtb":
            return Geometry(type: type, chainstay: 437, bbDrop: 32, seatAngle: 76.5, saddleHeight: 720, stack: 628,
                            reach: 470, headAngle: 65, headTube: 110, forkOffset: 44, topJoin: 420, stayJoin: 360,
                            tyreWidth: 60, rimDepth: 24, stemLength: 45, stemAngle: 0, spacers: 15, bar: .flat,
                            rings: [32], cogs: [52, 44, 38, 32, 28, 24, 21, 18, 16, 14, 12, 10], spokes: 32,
                            suspension: true, dropper: true, tread: 46, longCage: true)
        default:  // road, and the bike on the indoor trainer
            return Geometry(type: type, chainstay: 408, bbDrop: 70, seatAngle: 73.5, saddleHeight: 742, stack: 565,
                            reach: 388, headAngle: 73, headTube: 150, forkOffset: 45, topJoin: 500, stayJoin: 430,
                            tyreWidth: 28, rimDepth: 48, stemLength: 100, stemAngle: -10, spacers: 20, bar: .drop,
                            rings: [52, 36], cogs: [30, 27, 24, 21, 19, 17, 15, 14, 13, 12, 11], spokes: 24,
                            suspension: false, dropper: false, tread: 0, longCage: false)
        }
    }

    var indoor: Bool { type == "indoor" }
    let rear = V(0, 0)
    var rimOuter: CGFloat { 311 }
    var tyreR: CGFloat { rimOuter + tyreWidth }
    var rimInner: CGFloat { rimOuter - rimDepth }
    var bb: V { V((chainstay * chainstay - bbDrop * bbDrop).squareRoot(), -bbDrop) }
    var seatDir: V { V(-cos(rad(seatAngle)), sin(rad(seatAngle))) }
    /// Down the steering axis.
    var steer: V { V(cos(rad(headAngle)), -sin(rad(headAngle))) }
    /// Square to the steering axis, pointing forward.
    var steerFwd: V { V(sin(rad(headAngle)), cos(rad(headAngle))) }
    var htTop: V { bb + V(reach, stack) }
    var htBottom: V { htTop + steer * headTube }
    var front: V {
        let x0 = htBottom.x + htBottom.y / tan(rad(headAngle))  // where the steering axis meets axle height
        return V(x0 + forkOffset / sin(rad(headAngle)), 0)
    }
    var saddle: V { bb + seatDir * saddleHeight }
    var seatTop: V { bb + seatDir * (topJoin + 45) }
    var topRear: V { bb + seatDir * topJoin }
    var stayTop: V { bb + seatDir * stayJoin }
    var ground: CGFloat { -tyreR - (indoor ? 32 : 0) }
    var stemStart: V { htTop - steer * (spacers + 18) }
    var stemEnd: V { stemStart + steerFwd.rotated(rad(stemAngle)) * stemLength }
    var crank: CGFloat { 172.5 }
    var crankAngle: CGFloat { rad(-38) }
    var ring: CGFloat { pitchRadius(rings[0]) }
    var cog: CGFloat { pitchRadius(cogs[cogs.count / 2]) }
    var upperJockey: V { longCage ? V(-24, -cog - 40) : V(-18, -cog - 34) }
    var lowerJockey: V { longCage ? V(10, -cog - 158) : V(2, -cog - 112) }
}

// MARK: - Painting

private struct BikePainter {
    let spec: BikeSpec
    let icon: Bool
    let mono: UIColor?
    let g: Geometry

    init(spec: BikeSpec, icon: Bool, mono: UIColor?) {
        self.spec = spec
        self.icon = icon
        self.mono = mono
        g = Geometry.of(spec.type)
    }

    // Colours (one colour when mono).
    private func c(_ color: UIColor) -> UIColor { mono ?? color }
    private var frame: UIColor { c(BikePalette.color(spec.frame, in: BikePalette.frame, fallback: 0x26252A)) }
    private var accent: UIColor { c(BikePalette.color(spec.accent, in: BikePalette.frame, fallback: 0xF1E2B6)) }
    private var rubber: UIColor { c(UIColor(rgb: 0x1C1A1B)) }
    private var wall: UIColor { c(BikePalette.color(spec.tyres, in: BikePalette.tyres, fallback: 0x1C1A1B)) }
    private var parts: UIColor { c(UIColor(rgb: 0x232226)) }      // groupset, bars, saddle
    private var metal: UIColor { c(UIColor(rgb: 0xA9AAB0)) }      // rotors, cogs, chain
    private var spokeColor: UIColor { c(UIColor(rgb: 0x2E2D31)) }

    // World (mm, y up) to view (points, y down).
    private struct Fit { var scale: CGFloat; var minX: CGFloat; var maxY: CGFloat; var ox: CGFloat; var oy: CGFloat }
    private var bounds: (minX: CGFloat, maxX: CGFloat, minY: CGFloat, maxY: CGFloat) {
        let minX = min(-g.tyreR, g.indoor ? -250 : 0) - 8
        let maxX = g.front.x + g.tyreR + 8
        let top = max(g.saddle.y + 62, g.stemEnd.y + 40)
        return (minX, maxX, g.ground - (icon ? 8 : 24), top)
    }

    func draw(in ctx: inout GraphicsContext, size: CGSize) {
        let b = bounds
        let scale = min(size.width / (b.maxX - b.minX), size.height / (b.maxY - b.minY))
        let fit = Fit(scale: scale, minX: b.minX, maxY: b.maxY,
                      ox: (size.width - (b.maxX - b.minX) * scale) / 2,
                      oy: icon ? (size.height - (b.maxY - b.minY) * scale) / 2 : size.height - (b.maxY - b.minY) * scale)
        var pen = Pen(ctx: ctx, fit: fit, icon: icon)

        if !icon { shadow(&pen) }
        if g.indoor { trainer(&pen) } else { wheel(&pen, at: g.rear, rear: true) }
        if g.indoor { riser(&pen) }
        wheel(&pen, at: g.front, rear: false)
        if !icon { farSide(&pen) }
        frameTubes(&pen)
        fork(&pen)
        cockpit(&pen)
        seat(&pen)
        if !icon && !g.suspension { bottle(&pen) }
        drivetrain(&pen)
        ctx = pen.ctx
    }

    // MARK: Pen: paths in millimetres

    private struct Pen {
        var ctx: GraphicsContext
        let fit: Fit
        let icon: Bool

        func p(_ v: V) -> CGPoint { CGPoint(x: (v.x - fit.minX) * fit.scale + fit.ox, y: (fit.maxY - v.y) * fit.scale + fit.oy) }
        func mm(_ d: CGFloat) -> CGFloat { d * fit.scale }
        /// A line width in millimetres, never thinner than a hairline on screen.
        func w(_ d: CGFloat) -> CGFloat { max(d * fit.scale, 0.35) }

        func circle(_ c: V, _ r: CGFloat) -> Path {
            Path(ellipseIn: CGRect(x: p(c).x - mm(r), y: p(c).y - mm(r), width: mm(r) * 2, height: mm(r) * 2))
        }
        func ring(_ c: V, _ r0: CGFloat, _ r1: CGFloat) -> Path {
            var path = circle(c, r1)
            path.addPath(circle(c, r0))
            return path
        }
        func line(_ pts: [V]) -> Path {
            var path = Path()
            path.addLines(pts.map(p))
            return path
        }
        /// An arc as a polyline, from angle a0 to a1 (radians, anticlockwise with y up; a1 < a0 goes clockwise).
        func arc(_ c: V, _ r: CGFloat, from a0: CGFloat, to a1: CGFloat) -> Path {
            let steps = max(8, Int(abs(a1 - a0) * 24))
            return line((0...steps).map { c + V.polar(r, a0 + (a1 - a0) * CGFloat($0) / CGFloat(steps)) })
        }

        /// A tube along a centre line, tapering from w0 to w1, with round ends.
        func tube(_ pts: [V], _ w0: CGFloat, _ w1: CGFloat) -> Path {
            guard pts.count >= 2 else { return Path() }
            var lens: [CGFloat] = [0]
            for i in 1..<pts.count { lens.append(lens[i - 1] + (pts[i] - pts[i - 1]).length) }
            let total = max(lens.last ?? 1, 0.001)
            var upper: [V] = [], lower: [V] = []
            for (i, pt) in pts.enumerated() {
                let dir = (pts[min(i + 1, pts.count - 1)] - pts[max(i - 1, 0)]).unit
                let half = (w0 + (w1 - w0) * lens[i] / total) / 2
                upper.append(pt + dir.left * half)
                lower.append(pt - dir.left * half)
            }
            var path = Path()
            path.addLines((upper + lower.reversed()).map(p))
            path.closeSubpath()
            path.addPath(circle(pts[0], w0 / 2))
            path.addPath(circle(pts[pts.count - 1], w1 / 2))
            return path
        }

        /// Points along a quadratic curve, for bent tubes.
        func curve(_ a: V, _ control: V, _ b: V, steps: Int = 14) -> [V] {
            (0...steps).map { i in
                let t = CGFloat(i) / CGFloat(steps)
                return a * ((1 - t) * (1 - t)) + control * (2 * (1 - t) * t) + b * (t * t)
            }
        }

        /// Fill a tube with light along its upper edge and shade along the lower one, like a painted tube.
        mutating func paint(_ path: Path, _ color: UIColor, along a: V, _ b: V, width: CGFloat, edge: Bool = true, gloss: CGFloat = 1) {
            let mid = (a + b) * 0.5
            var n = (b - a).unit.left
            if n.y < 0 { n = n * -1 }
            let top = p(mid + n * (width / 2)), bottom = p(mid - n * (width / 2))
            let gradient = Gradient(stops: [
                .init(color: Color(color.shade(1 + 0.45 * gloss)), location: 0),
                .init(color: Color(color.shade(1 + 0.12 * gloss)), location: 0.22),
                .init(color: Color(color), location: 0.45),
                .init(color: Color(color.shade(0.78)), location: 0.85),
                .init(color: Color(color.shade(0.62)), location: 1),
            ])
            ctx.fill(path, with: .linearGradient(gradient, startPoint: top, endPoint: bottom))
            if edge && !icon {
                ctx.stroke(path, with: .color(Color(color.shade(color.isLight ? 0.72 : 0.55))), lineWidth: w(0.9))
            }
        }

        mutating func fill(_ path: Path, _ color: UIColor) { ctx.fill(path, with: .color(Color(color))) }
        mutating func fillEO(_ path: Path, _ color: UIColor) {
            ctx.fill(path, with: .color(Color(color)), style: FillStyle(eoFill: true))
        }
        mutating func stroke(_ path: Path, _ color: UIColor, _ width: CGFloat, dash: [CGFloat] = [], cap: CGLineCap = .round) {
            ctx.stroke(path, with: .color(Color(color)),
                       style: StrokeStyle(lineWidth: w(width), lineCap: cap, lineJoin: .round, dash: dash.map { mm($0) }))
        }
    }

    /// Thicker tubes in the nano version so the bike still reads at 30 points.
    private func t(_ width: CGFloat) -> CGFloat { icon ? width * 1.9 : width }

    // MARK: Parts

    private func shadow(_ pen: inout Pen) {
        let left = pen.p(V(-g.tyreR * 0.7, g.ground)), right = pen.p(V(g.front.x + g.tyreR * 0.7, g.ground))
        let rect = CGRect(x: left.x, y: left.y - pen.mm(12), width: right.x - left.x, height: pen.mm(24))
        var layer = pen.ctx
        layer.addFilter(.blur(radius: pen.mm(10)))
        layer.fill(Path(ellipseIn: rect), with: .color(Color(UIColor(rgb: 0x1B1618)).opacity(mono == nil ? 0.16 : 0)))
    }

    private func wheel(_ pen: inout Pen, at c: V, rear: Bool) {
        // Disc rotor on the far side, seen through the spokes.
        if !icon {
            let r: CGFloat = g.type == "mtb" ? (rear ? 90 : 100) : 80
            pen.fillEO(pen.ring(c, r - 15, r), metal)
            for i in 0..<6 {
                let a = CGFloat(i) * .pi / 3 + 0.3
                pen.stroke(pen.line([c + V.polar(18, a), c + V.polar(r - 12, a + 0.25)]), metal.shade(0.8), 6)
            }
            // Spokes, crossed.
            let n = g.spokes
            for i in 0..<n {
                let a = CGFloat(i) * 2 * .pi / CGFloat(n)
                let lead: CGFloat = (i % 2 == 0 ? 1 : -1) * (rear ? 0.62 : 0.4)
                pen.stroke(pen.line([c + V.polar(24, a + lead), c + V.polar(g.rimInner + 2, a)]), spokeColor, 1.9, cap: .butt)
            }
        }
        // Rim: deep carbon on the road bike, with decals in the accent colour.
        pen.fillEO(pen.ring(c, g.rimInner, g.rimOuter), parts)
        if !icon {
            pen.stroke(pen.circle(c, g.rimOuter - 3), parts.shade(1.6), 1.2)
            let mid = (g.rimInner + g.rimOuter) / 2
            let decal = max(g.rimDepth * 0.32, 5)
            for start in [rad(28), rad(208)] {
                pen.stroke(pen.arc(c, mid, from: start, to: start + rad(46)), accent, decal, cap: .butt)
            }
            pen.stroke(pen.line([c + V.polar(g.rimInner, rad(256)), c + V.polar(g.rimInner - 16, rad(256))]), metal, 3)
        }
        // Tyre: tread in black, walls in black or tan.
        pen.fillEO(pen.ring(c, g.rimOuter, g.tyreR), rubber)
        if spec.tyres != "black" {
            pen.fillEO(pen.ring(c, g.rimOuter + 1, g.rimOuter + g.tyreWidth * 0.62), wall)
        }
        if !icon {
            if g.tread > 0 {
                let knob: CGFloat = g.type == "mtb" ? 12 : 5
                for i in 0..<g.tread {
                    let a = CGFloat(i) * 2 * .pi / CGFloat(g.tread)
                    let r = g.tyreR - (i % 2 == 0 ? 0 : knob * 0.4)
                    pen.stroke(pen.line([c + V.polar(r - knob, a), c + V.polar(r + knob * 0.25, a)]), rubber,
                               g.type == "mtb" ? 10 : 4.5, cap: .butt)
                }
            }
            // A soft sheen on the upper left of the tyre.
            pen.stroke(pen.arc(c, g.tyreR - g.tyreWidth * 0.3, from: rad(105), to: rad(165)),
                       UIColor.white.withAlphaComponent(mono == nil ? 0.16 : 0), g.tyreWidth * 0.18)
            // Hub.
            pen.fill(pen.circle(c, 30), parts)
            pen.stroke(pen.circle(c, 22), parts.shade(1.7), 1.4)
            pen.fill(pen.circle(c, 9), metal)
        } else {
            pen.fill(pen.circle(c, 34), parts)
        }
    }

    /// The direct-drive trainer the bike sits on (rear wheel off), with its legs on the floor.
    private func trainer(_ pen: inout Pen) {
        let body = c(UIColor(rgb: 0x2A292D))
        let hub = g.rear + V(30, -70)
        let feet: [(V, V)] = [(hub, V(-245, g.ground + 12)), (hub, V(290, g.ground + 12))]
        for (a, b) in feet { pen.paint(pen.tube([a, b], t(46), t(34)), body, along: a, b, width: t(46), edge: false) }
        for x in [-245, 290] as [CGFloat] {
            pen.fill(pen.tube([V(x - 45, g.ground + 6), V(x + 45, g.ground + 6)], t(14), t(14)), body.shade(0.8))
        }
        let housing = pen.circle(hub, 185)
        pen.paint(housing, body, along: hub - V(185, 0), hub + V(185, 0), width: 370, edge: false)
        if !icon {
            pen.stroke(pen.circle(hub, 170), body.shade(1.5), 2.5)
            pen.stroke(pen.circle(hub, 118), body.shade(0.7), 6)
            pen.fill(pen.circle(hub + V(0, 140), 7), accent)  // status light
        }
    }

    /// The block under the front wheel on the trainer.
    private func riser(_ pen: inout Pen) {
        let top = g.ground + 32
        let shape = pen.tube([V(g.front.x - 120, top - 16), V(g.front.x + 120, top - 16)], 32, 32)
        pen.fill(shape, c(UIColor(rgb: 0x2A292D)))
    }

    /// Far-side crank arm and brake calipers (behind the frame).
    private func farSide(_ pen: inout Pen) {
        let far = g.bb + V.polar(g.crank, g.crankAngle + .pi)
        pen.fill(pen.tube([g.bb, far], 30, 22), parts.shade(0.8))
        pen.fill(pen.tube([far + V(-38, 0), far + V(38, 0)], 16, 16), parts.shade(0.7))
        let rearCaliper = g.rear + V.polar(78, rad(28))
        pen.fill(pen.tube([rearCaliper - V(26, 6), rearCaliper + V(26, 6)], 30, 30), parts.shade(0.9))
        let frontCaliper = g.front + (g.steer * -1).rotated(rad(28)) * 80
        pen.fill(pen.tube([frontCaliper - g.steer * 26, frontCaliper + g.steer * 26], 28, 28), parts.shade(0.9))
    }

    private func frameTubes(_ pen: inout Pen) {
        let dropout = g.rear
        // Rear end.
        pen.paint(pen.tube([dropout, g.bb], t(19), t(27)), frame, along: dropout, g.bb, width: t(27))
        pen.paint(pen.tube([dropout, g.stayTop], t(15), t(21)), frame, along: dropout, g.stayTop, width: t(21))
        // Main triangle.
        let seatBottom = g.bb + g.seatDir * 20
        pen.paint(pen.tube([seatBottom, g.seatTop], t(40), t(34)), frame, along: seatBottom, g.seatTop, width: t(40))
        let downFront = g.htBottom - g.steer * 28
        pen.paint(pen.tube([g.bb, downFront], t(64), t(56)), frame, along: g.bb, downFront, width: t(64))
        let topFront = g.htTop + g.steer * 22
        pen.paint(pen.tube([g.topRear, topFront], t(34), t(38)), frame, along: g.topRear, topFront, width: t(38))
        let htTop = g.htTop - g.steer * 6, htBottom = g.htBottom + g.steer * 4
        pen.paint(pen.tube([htTop, htBottom], t(50), t(58)), frame, along: htTop, htBottom, width: t(58))
        pen.paint(pen.circle(g.bb, t(34)), frame, along: g.bb - V(34, 0), g.bb + V(34, 0), width: t(68))
        if g.suspension { rearSuspension(&pen) }

        guard !icon else { return }
        // Accent: a pinstripe along the down tube, a band at the top of the seat tube, a head badge.
        let dt = (downFront - g.bb).unit
        let off = dt.left * 18
        pen.stroke(pen.line([g.bb + dt * 160 + off, g.bb + dt * 470 + off]), accent, 5)
        pen.stroke(pen.line([g.seatTop - g.seatDir * 26, g.seatTop - g.seatDir * 14]), accent, 34, cap: .butt)
        let badge = g.htTop + g.steer * (g.headTube * 0.45)
        pen.fill(pen.tube([badge - g.steer * 14, badge + g.steer * 14], 18, 12), accent)
    }

    /// A trail bike's rear end: a rocker pivoting on the seat tube, driving a shock that sits on the down tube.
    private func rearSuspension(_ pen: inout Pen) {
        let pivot = g.bb + g.seatDir * (g.stayJoin + 28)
        let shockTop = pivot + V(78, 26)
        let dt = (g.htBottom - g.bb).unit
        let shockBottom = g.bb + dt * 250 + dt.left * 40
        // Shock: body in black with a sticker, polished shaft at the bottom.
        let shaftEnd = shockBottom + (shockTop - shockBottom) * 0.38
        pen.paint(pen.tube([shockBottom, shaftEnd], t(18), t(18)), metal, along: shockBottom, shaftEnd, width: t(18), edge: false)
        pen.paint(pen.tube([shaftEnd, shockTop], t(40), t(34)), parts, along: shaftEnd, shockTop, width: t(40), edge: false)
        if !icon {
            let a = shaftEnd + (shockTop - shaftEnd) * 0.2, b = shaftEnd + (shockTop - shaftEnd) * 0.6
            pen.stroke(pen.line([a, b]), accent, 24, cap: .butt)
            pen.fill(pen.circle(shockBottom, 12), parts.shade(0.7))
        }
        // Rocker: a plate joining the seat stays, the pivot and the shock.
        let rocker = Path { path in
            path.addLines([pen.p(g.stayTop - g.seatDir * 6), pen.p(pivot + V(0, 18)), pen.p(shockTop + V(4, 14)),
                           pen.p(shockTop + V(8, -10)), pen.p(pivot + V(10, -16))])
            path.closeSubpath()
        }
        pen.paint(rocker, frame.shade(0.82), along: pivot, shockTop, width: 40)
        if !icon {
            for j in [g.stayTop, pivot, shockTop] { pen.fill(pen.circle(j, 7), metal.shade(0.8)) }
        }
    }

    private func fork(_ pen: inout Pen) {
        let crown = g.htBottom + g.steer * 22
        let legTop = crown + g.steerFwd * g.forkOffset
        if g.suspension {
            // Crown, stanchions (gold) and lowers down to the axle.
            pen.paint(pen.tube([crown - g.steerFwd * 8, legTop + g.steerFwd * 10], t(40), t(40)), parts,
                      along: crown, legTop, width: t(36), edge: false)
            let lowersTop = legTop + g.steer * 170
            pen.paint(pen.tube([legTop, lowersTop], t(34), t(34)), c(UIColor(rgb: 0xC8A25A)), along: legTop, lowersTop,
                      width: t(34), edge: false)
            pen.paint(pen.tube([lowersTop - g.steer * 12, g.front], t(46), t(30)), parts, along: lowersTop, g.front,
                      width: t(46), edge: false)
            if !icon {
                pen.stroke(pen.line([lowersTop + g.steer * 30, lowersTop + g.steer * 120]), accent, 8, cap: .butt)
            }
        } else {
            let pts = pen.curve(crown, legTop + g.steer * 140, g.front)
            pen.paint(pen.tube(pts, t(36), t(17)), frame, along: crown, g.front, width: t(36))
        }
    }

    private func cockpit(_ pen: inout Pen) {
        // Steerer and spacers above the head tube, then the stem.
        let spacerTop = g.htTop - g.steer * (g.spacers + 4)
        pen.paint(pen.tube([g.htTop, spacerTop], t(40), t(38)), parts, along: g.htTop, spacerTop, width: t(40), edge: false)
        pen.paint(pen.tube([g.stemStart, g.stemEnd], t(36), t(32)), parts, along: g.stemStart, g.stemEnd, width: t(36), edge: false)
        pen.fill(pen.circle(g.stemEnd, t(22)), parts)
        let o = g.stemEnd
        switch g.bar {
        case .drop:
            // Bar tape from the tops round to the drops; hoods and levers at the front of the bend.
            let deep: CGFloat = g.type == "gravel" ? 1.12 : 1
            let barPts = pen.curve(o, o + V(70, 4), o + V(98, -34 * deep)) + pen.curve(o + V(98, -34 * deep),
                                                                                       o + V(104, -110 * deep),
                                                                                       o + V(18, -122 * deep)).dropFirst()
            let tape = Array(barPts) + [o + V(-14, -122 * deep)]
            pen.stroke(pen.line(tape), accent.shade(0.7), t(25))
            pen.stroke(pen.line(tape), accent, t(21))
            if !icon {
                // Tape wraps.
                pen.stroke(pen.line(tape), accent.shade(0.86), 21, dash: [2.5, 9], cap: .butt)
                let hood = Path { path in
                    path.move(to: pen.p(o + V(48, 8)))
                    path.addCurve(to: pen.p(o + V(100, 36)), control1: pen.p(o + V(60, 24)), control2: pen.p(o + V(84, 34)))
                    path.addCurve(to: pen.p(o + V(108, 18)), control1: pen.p(o + V(112, 38)), control2: pen.p(o + V(114, 26)))
                    path.addCurve(to: pen.p(o + V(98, -28)), control1: pen.p(o + V(104, 6)), control2: pen.p(o + V(104, -12)))
                    path.addLine(to: pen.p(o + V(66, -4)))
                    path.closeSubpath()
                }
                pen.fill(hood, parts)
                pen.stroke(hood, parts.shade(1.9), 1.2)
                let lever = pen.curve(o + V(106, 14), o + V(122, -50), o + V(88, -108 * deep))
                pen.stroke(pen.line(lever), parts.shade(1.25), 11)
            }
        case .flat:
            // Riser bar seen end-on: a short rise back to the grip, lever reaching forward.
            let grip = o + V(-26, 30)
            pen.stroke(pen.line([o, grip]), parts, t(26))
            pen.fill(pen.circle(grip, t(19)), parts.shade(0.85))
            if !icon {
                pen.fill(pen.circle(grip, 9), accent)
                pen.stroke(pen.line([grip + V(10, 4), grip + V(64, -14), grip + V(82, -10)]), parts.shade(1.3), 9)
            }
        }
    }

    private func seat(_ pen: inout Pen) {
        let clamp = g.saddle
        if g.dropper {
            let collar = g.seatTop + g.seatDir * 30
            pen.paint(pen.tube([g.seatTop, collar], t(36), t(36)), parts, along: g.seatTop, collar, width: t(36), edge: false)
            pen.paint(pen.tube([collar, clamp], t(28), t(28)), c(UIColor(rgb: 0x2E2D31)), along: collar, clamp, width: t(28), edge: false)
        } else {
            pen.paint(pen.tube([g.seatTop, clamp], t(30), t(26)), parts, along: g.seatTop, clamp, width: t(30), edge: false)
        }
        // A short-nosed saddle on its rails.
        let s = clamp + V(0, 18)
        let shape = Path { path in
            path.move(to: pen.p(s + V(-128, 40)))
            path.addCurve(to: pen.p(s + V(118, 30)), control1: pen.p(s + V(-60, 56)), control2: pen.p(s + V(40, 38)))
            path.addCurve(to: pen.p(s + V(122, 14)), control1: pen.p(s + V(132, 28)), control2: pen.p(s + V(132, 16)))
            path.addCurve(to: pen.p(s + V(-120, 10)), control1: pen.p(s + V(40, 8)), control2: pen.p(s + V(-60, 0)))
            path.addCurve(to: pen.p(s + V(-128, 40)), control1: pen.p(s + V(-140, 16)), control2: pen.p(s + V(-142, 34)))
            path.closeSubpath()
        }
        pen.paint(shape, parts, along: s + V(-120, 10), s + V(-128, 44), width: 40, edge: false, gloss: 0.3)
        if !icon {
            pen.stroke(pen.line([s + V(-80, 10), clamp + V(-50, 2), clamp + V(50, 2), s + V(70, 12)]), metal, 4)
            pen.stroke(pen.line([s + V(-120, 38), s + V(-70, 46)]), accent, 4)
        }
    }

    private func bottle(_ pen: inout Pen) {
        let dt = (g.htBottom - g.bb).unit
        let up = dt.left
        let start = g.bb + dt * 170 + up * 70, end = g.bb + dt * 380 + up * 70
        pen.stroke(pen.line([g.bb + dt * 165 + up * 34, start - up * 20, end - up * 20, g.bb + dt * 385 + up * 34]),
                   parts, 6)
        let body = pen.tube([start, end], 72, 68)
        pen.paint(body, c(UIColor(rgb: 0xF6F2EC)), along: start, end, width: 72)
        pen.stroke(pen.line([g.bb + dt * 250 + up * 34, g.bb + dt * 250 + up * 106]), accent, 26, cap: .butt)
        pen.fill(pen.tube([end, end + dt * 26], 34, 22), accent)
    }

    private func drivetrain(_ pen: inout Pen) {
        let cassette = g.rear
        // Cassette: the biggest cog as a dark disc, each cog's edge in steel.
        let biggest = pitchRadius(g.cogs[0])
        pen.fill(pen.circle(cassette, biggest + 3), parts.shade(1.15))
        if !icon {
            for (i, n) in g.cogs.enumerated() {
                pen.stroke(pen.circle(cassette, pitchRadius(n) + 2), metal.shade(i % 2 == 0 ? 1 : 0.82), 2.2)
            }
            pen.fill(pen.circle(cassette, 16), metal.shade(0.75))
        }

        let ring = g.ring, cog = g.cog
        if !icon {
            // Chain: top run, round the front of the ring, bottom run back to the derailleur.
            let top = tangent(g.bb, ring, cassette, cog, upper: true)
            let ju = cassette + g.upperJockey, jl = cassette + g.lowerJockey
            let bottom = tangent(g.bb, ring, jl, 17, upper: false)
            let a0 = atan2(top.0.y - g.bb.y, top.0.x - g.bb.x), a1 = atan2(bottom.0.y - g.bb.y, bottom.0.x - g.bb.x)
            var chain = pen.line([top.1, top.0])
            chain.addPath(pen.arc(g.bb, ring, from: a0, to: a1 < a0 ? a1 : a1 - 2 * .pi))
            chain.addPath(pen.line([bottom.0, bottom.1]))
            chain.addPath(pen.line([cassette + V.polar(cog, rad(-118)), ju + V(-12, -4), jl + V(-14, 4)]))
            pen.stroke(chain, metal.shade(0.55), 8)
            pen.stroke(chain, metal.shade(1.1), 4, dash: [6.35, 6.35], cap: .butt)

            // Rear derailleur: knuckle down from the hanger, cage round the two jockey wheels.
            let hanger = cassette + V(12, -22)
            pen.paint(pen.tube([hanger, ju + V(-18, 14)], 30, 26), parts, along: hanger, ju, width: 30, edge: false)
            pen.paint(pen.tube([ju, jl], 34, 34), parts.shade(1.15), along: ju, jl, width: 34, edge: false)
            for j in [ju, jl] {
                pen.fill(pen.circle(j, 15), metal.shade(0.7))
                pen.fill(pen.circle(j, 5), metal)
            }
            pen.stroke(pen.line([jl + V(-6, 30), ju + V(-6, -22)]), accent, 3)
            // Gear cable in its housing, out of the chainstay into the derailleur.
            let exit = g.rear + (g.bb - g.rear).unit * 90
            let housing = Path { path in
                path.move(to: pen.p(exit))
                path.addCurve(to: pen.p(hanger + V(-6, -14)), control1: pen.p(exit + V(10, -70)), control2: pen.p(hanger + V(60, -50)))
            }
            pen.stroke(housing, parts.shade(0.8), 6)

            // Front derailleur on a double.
            if g.rings.count > 1 {
                let fd = g.bb + g.seatDir * (ring + 34)
                let cage = pen.curve(fd + V(-34, -8), fd + V(6, 10), fd + V(46, -14))
                pen.stroke(pen.line(cage), parts, 14)
                pen.stroke(pen.line([fd + V(-10, 2), fd - g.seatDir * -26]), parts, 12)
            }
        }

        // Chainrings: the inner ring behind, the big ring with its teeth, a four-arm spider.
        if g.rings.count > 1 { pen.fill(teeth(pen, pitchRadius(g.rings[1]), g.rings[1]), parts.shade(0.85)) }
        if icon {
            pen.fillEO(pen.ring(g.bb, ring * 0.55, ring + 4), parts)
        } else {
            pen.fill(teeth(pen, ring, g.rings[0]), parts)
            pen.stroke(pen.circle(g.bb, ring - 14), parts.shade(1.9), 1.4)
            pen.stroke(pen.circle(g.bb, ring - 26), parts.shade(1.4), 1)
            for i in 0..<4 {
                let a = g.crankAngle + CGFloat(i) * .pi / 2 + .pi / 4
                pen.fill(pen.tube([g.bb, g.bb + V.polar(ring - 22, a)], 20, 14), parts.shade(1.2))
            }
        }
        // Drive-side crank and pedal.
        let pedal = g.bb + V.polar(g.crank, g.crankAngle)
        pen.paint(pen.tube([g.bb, pedal], t(32), t(22)), parts, along: g.bb, pedal, width: t(32), edge: false)
        if !icon {
            pen.stroke(pen.line([g.bb + V.polar(30, g.crankAngle), pedal - V.polar(20, g.crankAngle)]), parts.shade(2.2), 1.6)
            pen.fill(pen.circle(g.bb, 20), metal.shade(0.8))
            if g.type == "mtb" {
                pen.fill(pen.tube([pedal + V(-50, 0), pedal + V(50, 0)], 18, 18), parts.shade(0.8))
                for k in stride(from: -40, through: 40, by: 20) as StrideThrough<CGFloat> {
                    pen.fill(pen.circle(pedal + V(k, 11), 3), metal)
                }
            } else {
                pen.fill(pen.tube([pedal + V(-40, 2), pedal + V(44, -4)], 16, 10), parts.shade(0.8))
                pen.fill(pen.tube([pedal + V(-10, 4), pedal + V(26, 1)], 8, 6), accent)
            }
        }
    }

    /// The outside tangent between two circles (upper or lower), as the points on each.
    private func tangent(_ c1: V, _ r1: CGFloat, _ c2: V, _ r2: CGFloat, upper: Bool) -> (V, V) {
        let v = c1 - c2, d = v.length, u = v.unit
        let side = upper ? u.left : u.left * -1
        let sinB = (r1 - r2) / d, cosB = (1 - sinB * sinB).squareRoot()
        let m = side * cosB - u * sinB
        return (c1 + m * r1, c2 + m * r2)
    }

    /// A chainring outline with its teeth.
    private func teeth(_ pen: Pen, _ r: CGFloat, _ n: Int) -> Path {
        var pts: [V] = []
        for i in 0..<n {
            let a = CGFloat(i) * 2 * .pi / CGFloat(n)
            let step = 2 * .pi / CGFloat(n)
            pts.append(g.bb + V.polar(r - 4, a))
            pts.append(g.bb + V.polar(r + 5, a + step * 0.32))
            pts.append(g.bb + V.polar(r + 5, a + step * 0.62))
        }
        var path = pen.line(pts)
        path.closeSubpath()
        return path
    }
}

// MARK: - Colour helpers

extension UIColor {
    convenience init(rgb: UInt32) {
        self.init(red: CGFloat((rgb >> 16) & 0xFF) / 255, green: CGFloat((rgb >> 8) & 0xFF) / 255,
                  blue: CGFloat(rgb & 0xFF) / 255, alpha: 1)
    }

    /// Darker (f < 1) or lighter (f > 1), like avatar.py's _shade.
    func shade(_ f: CGFloat) -> UIColor {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        getRed(&r, green: &g, blue: &b, alpha: &a)
        func one(_ v: CGFloat) -> CGFloat { f < 1 ? v * f : v + (1 - v) * (f - 1) }
        return UIColor(red: min(1, max(0, one(r))), green: min(1, max(0, one(g))), blue: min(1, max(0, one(b))), alpha: a)
    }

    var isLight: Bool {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        getRed(&r, green: &g, blue: &b, alpha: &a)
        return 0.299 * r + 0.587 * g + 0.114 * b > 0.7
    }
}

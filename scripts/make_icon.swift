// Draws the app icon: "the climb", five columns of dots rising to a yellow summit dot, on graphite,
// standing on the ride card's colour ribbon (19 Nov 2026; mock-ups in the canvas linked from CLAUDE.md).
// usage: swift scripts/make_icon.swift <out.png> [--no-ribbon]   (the app uses --no-ribbon since 19 Nov)
//   e.g. swift scripts/make_icon.swift ios/RideApp/RideApp/Assets.xcassets/AppIcon.appiconset/AppIcon.png
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let args = CommandLine.arguments
let out = URL(fileURLWithPath: args[1]) as CFURL
let ribbon = !args.contains("--no-ribbon")
let size = 1024.0
let k = size / 180  // drawn on a 180-unit grid, as in the mock-ups

func rgb(_ hex: UInt32) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
}

let ctx = CGContext(data: nil, width: Int(size), height: Int(size), bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
// Draw top-down like the SVG mock-ups.
ctx.translateBy(x: 0, y: size)
ctx.scaleBy(x: k, y: -k)

// Graphite ground, full bleed (iOS rounds the corners itself).
ctx.setFillColor(rgb(0x141113))
ctx.fill(CGRect(x: 0, y: 0, width: 180, height: 180))

// The ribbon along the bottom, top to bottom as on the ride card.
if ribbon {
    for (i, c) in [0x4F86E8, 0xD23A55, 0x1B1618, 0xF2C230, 0x3E9B4F].enumerated() {
        ctx.setFillColor(rgb(UInt32(c)))
        ctx.fill(CGRect(x: 0, y: 150 + Double(i) * 6, width: 180, height: 6))
    }
}

// The climb: column i (0-4) is i+1 dots tall; the last column's top dot is the yellow summit.
// Above the ribbon; without it, nudged half-way from the outline's centre towards the dots' own centre
// (the climb's weight sits low and right), so it looks centred.
let lift = ribbon ? -14.0 : -7.0
let shift = ribbon ? 0.0 : -7.0
let r = 9.5
for col in 0..<5 {
    for row in 0...col {
        let x = 46 + Double(col) * 22 + shift, y = 134 - Double(row) * 22 + lift
        ctx.setFillColor(col == 4 && row == 4 ? rgb(0xF2C230) : rgb(0xFFFFFF))
        ctx.fillEllipse(in: CGRect(x: x - r, y: y - r, width: 2 * r, height: 2 * r))
    }
}

let dest = CGImageDestinationCreateWithURL(out, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(dest, ctx.makeImage()!, nil)
CGImageDestinationFinalize(dest)

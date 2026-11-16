#if DEBUG
import SwiftUI

/// Dev only: `-renderBikes` at launch writes every bike type as PNGs into Documents/bikes, to look at the drawing.
enum BikeArtRender {
    @MainActor static func runIfAsked() {
        guard ProcessInfo.processInfo.arguments.contains("-renderBikes") else { return }
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("bikes")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let specs: [(String, BikeSpec)] = [
            ("road", BikeSpec(type: "road", frame: "carbon", accent: "sand")),
            ("road-cobalt", BikeSpec(type: "road", frame: "cobalt", accent: "white")),
            ("gravel", BikeSpec(type: "gravel", frame: "green", accent: "ink", tyres: "tan")),
            ("mtb", BikeSpec(type: "mtb", frame: "orange", accent: "ink")),
            ("indoor", BikeSpec(type: "indoor", frame: "white", accent: "red")),
        ]
        for (name, spec) in specs {
            let big = ImageRenderer(content: BikeArt(spec: spec).frame(width: 370, height: 240).background(Theme.surface))
            big.scale = 3
            try? big.uiImage?.pngData()?.write(to: dir.appendingPathComponent("\(name).png"))
            for selected in [true, false] {
                let icon = BikeIcon.image(spec, selected: selected)
                let framed = ImageRenderer(content: Image(uiImage: icon).foregroundStyle(Theme.ink).padding(4).background(Theme.surface))
                framed.scale = 3
                try? framed.uiImage?.pngData()?.write(to: dir.appendingPathComponent("\(name)-icon-\(selected ? "on" : "off").png"))
            }
        }
    }
}
#endif

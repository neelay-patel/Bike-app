import SwiftUI

/// Merged rides from the backend, newest first.
struct RidesView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var health: HealthSync

    var body: some View {
        NavigationStack {
            List {
                if let error = model.error {
                    Text(error).foregroundStyle(.red).font(.footnote)
                }
                if model.rides.isEmpty && model.error == nil && !model.isLoading {
                    ContentUnavailableView("No rides yet", systemImage: "bicycle",
                                           description: Text("Connect Apple Health or Garmin in Connections."))
                }
                ForEach(model.rides) { ride in
                    NavigationLink { RideDetailView(ride: ride) } label: { RideRow(ride: ride) }
                }
            }
            .navigationTitle("Rides")
            .refreshable {
                await health.syncNew()
                await model.refresh()
            }
        }
    }
}

struct RideRow: View {
    let ride: RideSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(ride.date, format: .dateTime.weekday(.abbreviated).day().month(.abbreviated).year())
                    .font(.headline)
                Spacer()
                Text(ride.date, format: .dateTime.hour().minute()).foregroundStyle(.secondary)
            }
            HStack(spacing: 14) {
                Stat(value: String(format: "%.1f km", ride.summary.km))
                Stat(value: Format.duration(hours: ride.summary.movingH))
                if let avg = ride.summary.avgHr, let max = ride.summary.maxHr {
                    Stat(value: "\(Int(avg.rounded()))/\(Int(max.rounded())) bpm", symbol: "heart.fill")
                }
                if ride.summary.indoor { Stat(value: "Indoor") }
            }
            SourceChips(sources: ride.sources)
        }
        .padding(.vertical, 2)
    }
}

struct RideDetailView: View {
    let ride: RideSummary

    var body: some View {
        List {
            Section("Ride") {
                LabeledContent("Distance", value: String(format: "%.1f km", ride.summary.km))
                LabeledContent("Moving time", value: Format.duration(hours: ride.summary.movingH))
                if let v = ride.summary.avgKmh { LabeledContent("Average speed", value: String(format: "%.1f km/h", v)) }
                if let v = ride.summary.ascentM { LabeledContent("Climbing", value: "\(Int(v.rounded())) m") }
                if let v = ride.summary.avgHr { LabeledContent("Average heart rate", value: "\(Int(v.rounded())) bpm") }
                if let v = ride.summary.maxHr { LabeledContent("Max heart rate", value: "\(Int(v.rounded())) bpm") }
                if let v = ride.summary.avgPower { LabeledContent("Average power", value: "\(Int(v.rounded())) W") }
                if let v = ride.summary.calories { LabeledContent("Calories", value: "\(Int(v.rounded())) kcal") }
            }
            Section("Where each value came from") {
                ForEach(ride.provenance.sorted(by: { $0.key < $1.key }), id: \.key) { key, source in
                    LabeledContent(Format.provenanceLabel(key), value: Format.sourceName(source))
                }
            }
            Section("Use") {
                ForEach(["ai", "share"], id: \.self) { use in
                    if let p = ride.use[use] {
                        LabeledContent(use == "ai" ? "AI insights" : "Sharing",
                                       value: p.allowed ? "Allowed"
                                           : "Not yet (" + p.blockedBy.map(Format.sourceName).joined(separator: ", ") + ")")
                    }
                }
            }
        }
        .navigationTitle(Text(ride.date, format: .dateTime.day().month().year()))
    }
}

struct Stat: View {
    let value: String
    var symbol: String?

    var body: some View {
        HStack(spacing: 3) {
            if let symbol { Image(systemName: symbol).foregroundStyle(.red).imageScale(.small) }
            Text(value)
        }
        .font(.subheadline.monospacedDigit())
    }
}

struct SourceChips: View {
    let sources: [String]

    var body: some View {
        HStack(spacing: 6) {
            ForEach(sources, id: \.self) { s in
                Text(Format.sourceName(s))
                    .font(.caption2.weight(.medium))
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(.quaternary, in: Capsule())
            }
        }
    }
}

enum Format {
    static func duration(hours: Double) -> String {
        let minutes = Int((hours * 60).rounded())
        return String(format: "%d:%02d", minutes / 60, minutes % 60)
    }

    static func sourceName(_ key: String) -> String {
        let base = key.hasPrefix("derived:") ? String(key.dropFirst(8)) : key
        let names = ["apple_watch": "Apple Watch", "iphone": "iPhone", "garmin": "Garmin", "wahoo": "Wahoo",
                     "kickr": "KICKR", "hammerhead": "Hammerhead", "whoop": "WHOOP", "oura": "Oura",
                     "fitbit": "Fitbit", "gpx": "GPX", "hr": "heart rate", "power": "power"]
        let name = names[base] ?? base
        return key.hasPrefix("derived:") ? "worked out from \(name)" : name
    }

    static func provenanceLabel(_ key: String) -> String {
        let names = ["channel:lat": "Route", "channel:lon": "Route (longitude)", "channel:ele": "Elevation",
                     "channel:speed": "Speed", "channel:hr": "Heart rate", "channel:power": "Power",
                     "channel:cadence": "Cadence", "channel:temp": "Temperature",
                     "total:distance_m": "Distance", "total:ascent_m": "Climbing", "total:descent_m": "Descent",
                     "total:moving_s": "Moving time", "total:elapsed_s": "Elapsed time",
                     "total:max_speed_ms": "Max speed", "total:calories": "Calories",
                     "total:avg_hr": "Average heart rate", "total:max_hr": "Max heart rate",
                     "total:avg_power": "Average power", "total:max_power": "Max power"]
        return names[key] ?? key
    }
}

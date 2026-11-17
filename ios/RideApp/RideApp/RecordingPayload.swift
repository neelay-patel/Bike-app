import Foundation

/// One device's recording of one ride, in rideengine's exchange format
/// (rideengine/importers/recording_json.py). Times are unix seconds (UTC).
struct RecordingPayload: Codable {
    static let currentFormat = "rideengine.recording/1"

    var format = RecordingPayload.currentFormat
    var source: String          // rideengine source key: "apple_watch", "whoop", ...
    var device: String
    var start: Double
    var end: Double
    var sport = "cycling"
    var indoor: Bool
    var origin: String          // "healthkit:<workout uuid>"
    var totals: [String: Double]
    var samples: [SamplePayload]
    /// Heart rate in the minutes after the workout ended, for recovery.
    var after: [SamplePayload]?
}

/// A batch of recovery and fitness readings (rideengine.metrics/1).
struct MetricsBatch: Codable {
    var format = "rideengine.metrics/1"
    var metrics: [MetricPayload]
}

/// One VO2 max, HRV, resting heart rate or Cardio Recovery reading.
struct MetricPayload: Codable {
    var id: String          // HealthKit sample uuid
    var kind: String        // vo2max | hrv_sdnn | resting_hr | hr_recovery_1min
    var t: Double
    var value: Double
    var source: String
}

/// A route point or a heart-rate reading. Nil fields are left out of the JSON.
struct SamplePayload: Codable {
    var t: Double
    var lat: Double?
    var lon: Double?
    var ele: Double?
    var speed: Double?
    var hr: Double?
    var power: Double?
    var cadence: Double?
}

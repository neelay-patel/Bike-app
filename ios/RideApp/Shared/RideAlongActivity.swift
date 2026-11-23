import ActivityKit
import Foundation

/// The ride-along's Live Activity (RideAlong.swift): the step you're on, its target, a countdown to the next
/// change and what's next, on the lock screen and in the Dynamic Island, so following a session needs no
/// unlocking. Shared by the app and the KovaLive widget extension.
struct RideAlongAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var step: String          // "Hard"
        var target: String?       // "188–245 W · 95 rpm"
        var next: String?         // "Next: 2 min easy"
        var starts: Date          // when this step started (adjusted for pauses)
        var ends: Date            // when it ends: the countdown runs to here
        var paused: Bool
        var left: Double          // seconds left in the step, for when it's paused
        var work: Bool            // a work step (yellow) or easy riding
        var index: Int            // step number, from 1
        var count: Int
    }

    var title: String             // "Surges"
}

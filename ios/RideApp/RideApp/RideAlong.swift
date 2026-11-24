import ActivityKit
import AVFoundation
import SwiftUI
import UIKit

/// Following a session without looking at the phone (23 Nov 2026), for every rider whatever they wear: Kova
/// speaks each step through AirPods or the speaker ("Hard now. One minute at 188 to 245 watts."), warns ten
/// seconds before the work starts, and keeps going with the phone locked, where the lock screen and the Dynamic
/// Island show the step and a live countdown (KovaLive). It plays alongside Zwift or music, which only dip while
/// it speaks. It records nothing: the ride is still the Watch's or the head unit's.
@MainActor
final class RideAlong: NSObject, ObservableObject {
    static let shared = RideAlong()

    struct Cue: Equatable {
        let label: String        // "Hard"
        let seconds: Double
        let work: Bool
        let watts: [Int]?
        let hr: [Int]?
        let rpm: [Int]?

        /// "188–245 W · 95 rpm", or heart rate when there are no watts.
        var target: String? {
            var parts: [String] = []
            if let w = watts, w.count == 2 { parts.append("\(w[0])–\(w[1]) W") }
            else if let h = hr, h.count == 2 { parts.append("heart rate \(h[0])–\(h[1])") }
            if work, let r = rpm, r.count == 2 { parts.append(r[0] == r[1] ? "\(r[0]) rpm" : "\(r[0])–\(r[1]) rpm") }
            return parts.isEmpty ? nil : parts.joined(separator: " · ")
        }
    }

    @Published private(set) var session: PlanSession?
    @Published private(set) var cues: [Cue] = []
    @Published private(set) var index = 0
    @Published private(set) var running = false     // started (paused or not)
    @Published private(set) var paused = false
    @Published private(set) var finished = false
    @Published private(set) var now = Date()

    /// When the current step started, moved on by the length of any pause.
    private var stepStart = Date()
    private var pausedAt: Date?
    private var timer: Timer?
    private var said: Set<String> = []
    private let voice = AVSpeechSynthesizer()
    private let engine = AVAudioEngine()
    private let silence = AVAudioPlayerNode()
    private var activity: Activity<RideAlongAttributes>?

    // MARK: The session as steps

    static func cues(_ s: PlanSession) -> [Cue] {
        s.steps.flatMap(\.flat).compactMap { st in
            guard let secs = st.seconds, secs > 0 else { return nil }
            let easy = ["Z1", "Z2"].contains(st.zone ?? "")
            return Cue(label: st.label ?? (easy ? "Easy" : "Work"), seconds: secs, work: !easy,
                       watts: st.target?.watts, hr: st.target?.hr, rpm: st.target?.rpm)
        }
    }

    func load(_ s: PlanSession) {
        guard !running else { return }
        session = s
        cues = Self.cues(s)
        index = 0
        finished = false
    }

    var current: Cue? { cues.indices.contains(index) ? cues[index] : nil }
    var nextCue: Cue? { cues.indices.contains(index + 1) ? cues[index + 1] : nil }

    /// Seconds left in the current step.
    var left: Double {
        guard let c = current else { return 0 }
        let ref = pausedAt ?? now
        return max(0, c.seconds - ref.timeIntervalSince(stepStart))
    }

    var totalSeconds: Double { cues.reduce(0) { $0 + $1.seconds } }
    var doneSeconds: Double { cues.prefix(index).reduce(0) { $0 + $1.seconds } + ((current?.seconds ?? 0) - left) }

    // MARK: Controls

    /// The voice for this ride, chosen when it starts: a voice downloaded since the last ride is used.
    private var chosenVoice: AVSpeechSynthesisVoice?

    func start() {
        guard !cues.isEmpty else { return }
        chosenVoice = Self.bestVoice
        running = true
        paused = false
        finished = false
        index = 0
        said = []
        stepStart = Date()
        now = Date()
        startAudio()
        UIApplication.shared.isIdleTimerDisabled = true
        startTimer()
        enter(spoken: true)
        startActivity()
    }

    func togglePause() {
        guard running else { return }
        if let p = pausedAt {
            stepStart = stepStart.addingTimeInterval(Date().timeIntervalSince(p))
            pausedAt = nil
            paused = false
            say("Back to it.")
        } else {
            pausedAt = Date()
            paused = true
            say("Paused.")
        }
        updateActivity()
    }

    func skip(_ by: Int) {
        guard running else { return }
        let i = index + by
        guard cues.indices.contains(i) else { if by > 0 { finish() }; return }
        index = i
        stepStart = Date()
        if pausedAt != nil { pausedAt = Date() }
        said = []
        enter(spoken: true)
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        running = false
        paused = false
        pausedAt = nil
        voice.stopSpeaking(at: .immediate)
        stopAudio()
        UIApplication.shared.isIdleTimerDisabled = false
        endActivity(immediately: true)
    }

    private func finish() {
        finished = true
        index = cues.count - 1
        say("That's the session done. Well ridden. Spin easy for a few minutes.")
        timer?.invalidate()
        timer = nil
        running = false
        UIApplication.shared.isIdleTimerDisabled = false
        endActivity(immediately: false)
        // Let the last words finish before the audio stops.
        DispatchQueue.main.asyncAfter(deadline: .now() + 6) { [weak self] in
            guard let self, !self.running else { return }
            self.stopAudio()
        }
    }

    // MARK: The clock

    private func startTimer() {
        timer?.invalidate()
        let t = Timer(timeInterval: 0.25, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    private func tick() {
        now = Date()
        guard running, pausedAt == nil, let c = current else { return }
        let l = left
        // Into the next step (catching up if the phone held us back).
        if l <= 0 {
            var over = now.timeIntervalSince(stepStart) - c.seconds
            var i = index + 1
            while cues.indices.contains(i), over >= cues[i].seconds {
                over -= cues[i].seconds
                i += 1
            }
            guard cues.indices.contains(i) else { return finish() }
            index = i
            stepStart = now.addingTimeInterval(-over)
            said = []
            enter(spoken: over < 5)
            return
        }
        // Ten seconds before hard work starts: get ready.
        if let n = nextCue, n.work, !c.work || n.label != c.label, c.seconds >= 20, l <= 10.5, !said.contains("ten") {
            said.insert("ten")
            say("Ten seconds. Then \(n.label.lowercased()), \(Self.speak(seconds: n.seconds))\(Self.speak(n, short: true)).")
        }
        // Long steady work: halfway and the last minute.
        if c.work, c.seconds >= 300 {
            if l <= c.seconds / 2, !said.contains("half") {
                said.insert("half")
                say("Halfway. Hold it there.")
            }
            if l <= 60.5, !said.contains("minute") {
                said.insert("minute")
                say("One minute left.")
            }
        }
        // The last seconds of a work step: count it in.
        if c.work, c.seconds >= 20, l <= 3.5, !said.contains("count") {
            said.insert("count")
            say("Three, two, one.")
        }
    }

    /// Say the new step: what it is, how long, and its watts.
    private func enter(spoken: Bool) {
        updateActivity()
        guard spoken, let c = current else { return }
        let length = Self.speak(seconds: c.seconds)
        let text: String
        if index == 0 {
            text = "Starting \(session?.title ?? "the session"). \(c.label), \(length)\(Self.speak(c, short: false))."
        } else if c.work {
            text = "\(c.label) now. \(length)\(Self.speak(c, short: false))."
        } else {
            text = "\(c.label). \(length)\(Self.speak(c, short: false))."
        }
        say(text)
    }

    static func speak(seconds: Double) -> String {
        let s = Int(seconds.rounded())
        if s < 60 { return "\(s) seconds" }
        if s % 60 == 0 { return s == 60 ? "one minute" : "\(s / 60) minutes" }
        if s % 30 == 0 { return "\(s / 60) and a half minutes" }
        return "\(s / 60) minutes \(s % 60)"
    }

    static func speak(_ c: Cue, short: Bool) -> String {
        if let w = c.watts, w.count == 2 { return " at \(w[0]) to \(w[1]) watts" }
        if !short, let h = c.hr, h.count == 2 { return ", heart rate \(h[0]) to \(h[1])" }
        return ""
    }

    // MARK: Sound

    /// Plays with whatever else is playing (Zwift, music), which dips only while Kova speaks. A silent sound
    /// keeps the app awake with the phone locked, so the cues come on time.
    private func startAudio() {
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, options: [.mixWithOthers])
        try? session.setActive(true)
        voice.delegate = self
        if !engine.isRunning {
            engine.attach(silence)
            let format = engine.mainMixerNode.outputFormat(forBus: 0)
            engine.connect(silence, to: engine.mainMixerNode, format: format)
            if let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(format.sampleRate)) {
                buffer.frameLength = buffer.frameCapacity          // zeros: silence
                silence.scheduleBuffer(buffer, at: nil, options: .loops)
            }
            try? engine.start()
            silence.play()
        }
    }

    private func stopAudio() {
        silence.stop()
        engine.stop()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func say(_ text: String) {
        let u = AVSpeechUtterance(string: text)
        u.rate = AVSpeechUtteranceDefaultSpeechRate * 1.02
        u.voice = chosenVoice ?? Self.bestVoice
        voice.speak(u)
    }

    /// The most natural voice on this phone for its language (23 Nov 2026): a Premium voice if the rider has
    /// downloaded one, else an Enhanced one, else the default. Apps can't use Siri's voices or download voices
    /// themselves; the ride-along screen says where to get a better one. Novelty voices and Personal Voice
    /// (which needs its own permission) are left out.
    static var bestVoice: AVSpeechSynthesisVoice? {
        let code = AVSpeechSynthesisVoice.currentLanguageCode()          // "en-CA"
        let lang = String(code.prefix(2))
        let candidates = AVSpeechSynthesisVoice.speechVoices().filter { v in
            v.language.hasPrefix(lang) && !v.voiceTraits.contains(.isNoveltyVoice)
                && !v.voiceTraits.contains(.isPersonalVoice)
        }
        func rank(_ v: AVSpeechSynthesisVoice) -> (Int, Int) {
            let q = v.quality == .premium ? 3 : v.quality == .enhanced ? 2 : 1
            let place = v.language == code ? 2 : v.language.hasPrefix(lang) ? 1 : 0   // the rider's own accent first
            return (q, place)
        }
        return candidates.max { rank($0) < rank($1) } ?? AVSpeechSynthesisVoice(language: code)
    }

    /// "Ava (Premium)", and whether a better voice could be downloaded.
    static var voiceLine: (name: String, canImprove: Bool) {
        guard let v = bestVoice else { return ("the phone's voice", true) }
        let q = v.quality == .premium ? "Premium" : v.quality == .enhanced ? "Enhanced" : nil
        return (q.map { "\(v.name) (\($0))" } ?? v.name, v.quality != .premium)
    }

    // MARK: Lock screen

    private func state() -> RideAlongAttributes.ContentState? {
        guard let c = current else { return nil }
        let n = nextCue.map { "Next: \(Self.say(length: $0.seconds)) \($0.label.lowercased())" + ($0.target.map { " · \($0)" } ?? "") }
        return .init(step: c.label, target: c.target, next: n ?? "Last step", starts: stepStart,
                     ends: stepStart.addingTimeInterval(c.seconds), paused: pausedAt != nil, left: left,
                     work: c.work, index: index + 1, count: cues.count)
    }

    static func say(length seconds: Double) -> String {
        let s = Int(seconds.rounded())
        return s < 60 ? "\(s) s" : s % 60 == 0 ? "\(s / 60) min" : String(format: "%d:%02d", s / 60, s % 60)
    }

    private func startActivity() {
        guard ActivityAuthorizationInfo().areActivitiesEnabled, let st = state() else { return }
        endActivity(immediately: true)
        activity = try? Activity.request(attributes: RideAlongAttributes(title: session?.title ?? "Session"),
                                         content: .init(state: st, staleDate: nil))
    }

    private func updateActivity() {
        guard let a = activity, let st = state() else { return }
        Task { await a.update(.init(state: st, staleDate: nil)) }
    }

    private func endActivity(immediately: Bool) {
        guard let a = activity else { return }
        activity = nil
        let st = state()
        Task {
            await a.end(st.map { .init(state: $0, staleDate: nil) },
                        dismissalPolicy: immediately ? .immediate : .after(Date().addingTimeInterval(300)))
        }
    }
}

extension RideAlong: AVSpeechSynthesizerDelegate {
    // Others' audio dips while Kova speaks, and comes back up after.
    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didStart u: AVSpeechUtterance) {
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio, options: [.mixWithOthers, .duckOthers])
    }

    nonisolated func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) {
        guard !s.isSpeaking else { return }
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio, options: [.mixWithOthers])
    }
}

// MARK: - The screen

/// Big and plain, for a phone on the bars or the floor: the step, its watts, the countdown, what's next.
struct RideAlongView: View {
    let session: PlanSession
    @ObservedObject private var ride = RideAlong.shared
    @Environment(\.dismiss) private var dismiss

    private let summit = Theme.stripes[3]

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                MonoLabel("Ride along · \(session.title)", color: Theme.panelLabel)
                Spacer()
                Button {
                    ride.stop()
                    dismiss()
                } label: {
                    Image(systemName: "xmark").font(.system(size: 17, weight: .semibold)).foregroundStyle(.white)
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel(ride.running ? "End the ride along" : "Close")
            }
            if ride.running || ride.finished { live } else { intro }
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Theme.panel.ignoresSafeArea())
        .preferredColorScheme(.dark)          // light status bar on the dark screen
        .onAppear { ride.load(session) }
    }

    private var intro: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Kova talks you through it").font(Theme.heading(40)).foregroundStyle(.white)
                .fixedSize(horizontal: false, vertical: true)
            Text("Each step is spoken as it starts, with its watts, and you get ten seconds' warning before the work. It plays through your AirPods or speaker alongside Zwift or music, which dip only while Kova speaks.")
                .font(Theme.text(16)).foregroundStyle(Theme.panelLabel).fixedSize(horizontal: false, vertical: true)
            Text("Lock the phone if you like: it keeps going, and the lock screen shows the step and a countdown. Record the ride as you always do, on your Watch or head unit.")
                .font(Theme.text(16)).foregroundStyle(Theme.panelLabel).fixedSize(horizontal: false, vertical: true)
            let v = RideAlong.voiceLine
            VStack(alignment: .leading, spacing: 4) {
                Text("Voice: \(v.name)").font(Theme.mono(12)).foregroundStyle(Theme.panelLabel)
                if v.canImprove {
                    Text("For a more natural voice, download a Premium one in Settings › Accessibility › Read & Speak › Voices › English (Ava or Zoe sound good). Kova uses it next time.")
                        .font(Theme.text(13)).foregroundStyle(Theme.panelLabel.opacity(0.8)).fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer()
            Text("\(ride.cues.count) step\(ride.cues.count == 1 ? "" : "s") · \(Int((ride.totalSeconds / 60).rounded())) min")
                .font(Theme.mono(13)).foregroundStyle(Theme.panelLabel)
            Button { ride.start() } label: {
                Text("Start").font(Theme.text(20, .semibold)).foregroundStyle(Theme.ink)
                    .frame(maxWidth: .infinity, minHeight: 64)
                    .background(summit, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            }
            .disabled(ride.cues.isEmpty)
        }
    }

    private var live: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let c = ride.current {
                Text(ride.finished ? "Done" : c.label).font(Theme.heading(64)).foregroundStyle(c.work && !ride.finished ? summit : .white)
                    .lineLimit(1).minimumScaleFactor(0.5)
                if let t = c.target, !ride.finished {
                    Text(t).font(Theme.text(26, .semibold)).foregroundStyle(.white)
                }
                Text(ride.finished ? "Well ridden." : RideAlong.say(clock: ride.left))
                    .font(Theme.hero(ride.finished ? 48 : 120)).foregroundStyle(.white)
                    .monospacedDigit().lineLimit(1).minimumScaleFactor(0.4)
                    .accessibilityLabel("\(Int(ride.left)) seconds left")
                if let n = ride.nextCue, !ride.finished {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        MonoLabel("Next", color: Theme.panelLabel)
                        Text("\(RideAlong.say(length: n.seconds)) \(n.label.lowercased())" + (n.target.map { " · \($0)" } ?? ""))
                            .font(Theme.text(18, .medium)).foregroundStyle(Theme.panelLabel)
                    }
                }
            }
            Spacer()
            progress
            if !ride.finished {
                HStack(spacing: 14) {
                    control("backward.end.fill", "Previous step") { ride.skip(-1) }
                    Button { ride.togglePause() } label: {
                        Image(systemName: ride.paused ? "play.fill" : "pause.fill").font(.system(size: 28, weight: .bold))
                            .foregroundStyle(Theme.ink).frame(maxWidth: .infinity, minHeight: 72)
                            .background(summit, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                    }
                    .accessibilityLabel(ride.paused ? "Carry on" : "Pause")
                    control("forward.end.fill", "Next step") { ride.skip(1) }
                }
            } else {
                Button("Close") { ride.stop(); dismiss() }.buttonStyle(SecondaryButton())
            }
        }
    }

    /// The whole session, step by step: done in white, the work in yellow, where you are now.
    private var progress: some View {
        GeometryReader { g in
            let total = max(1, ride.totalSeconds)
            HStack(spacing: 2) {
                ForEach(Array(ride.cues.enumerated()), id: \.offset) { i, c in
                    RoundedRectangle(cornerRadius: 2)
                        .fill(i < ride.index ? Color.white.opacity(0.9) : c.work ? summit.opacity(i == ride.index ? 1 : 0.45)
                              : Theme.panelLine)
                        .frame(width: max(2, g.size.width * c.seconds / total - 2), height: c.work ? 22 : 12)
                }
            }
            .frame(maxHeight: .infinity, alignment: .bottom)
        }
        .frame(height: 22)
        .accessibilityHidden(true)
    }

    private func control(_ icon: String, _ label: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon).font(.system(size: 20, weight: .semibold)).foregroundStyle(.white)
                .frame(width: 72, height: 72)
                .background(Theme.panelLine, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        }
        .accessibilityLabel(label)
    }
}

extension RideAlong {
    /// "1:05", "0:09".
    static func say(clock seconds: Double) -> String {
        let s = Int(seconds.rounded(.up))
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}

import BackgroundTasks
import os
import SwiftUI
import UIKit
import UserNotifications

// The coach speaks up (docs/train-tab.md, step 4). The server works out the coach's messages (GET
// /v1/train/inbox: after a ride, a plan change, the Sunday review) with stable ids; the phone shows each new one
// as a notification. Until Kova has push (the paid developer account), messages arrive when the phone wakes Kova:
// Apple Health waking it for a new ride, background refresh now and then, or opening it. The morning brief comes
// with its time, so the phone schedules it itself and it arrives at 07:30 either way. Lock-screen words only:
// the server never puts recovery numbers in a message.

struct CoachInbox: Decodable {
    let items: [CoachMessage]
    let scheduled: [CoachMessage]
}

struct CoachMessage: Decodable, Identifiable {
    let id: String
    let kind: String            // ride | change | review | brief
    let title: String
    let body: String
    let opens: Opens
    let at: String

    struct Opens: Decodable {
        let screen: String      // ride | week | today
        let rideId: String?
        let weekStart: String?
    }
}

/// Where a tapped notification takes the rider.
enum CoachRoute: Hashable {
    case ride(String)
    case week(String)
    case today
}

@MainActor
final class CoachNotifier: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    static let shared = CoachNotifier()
    static let refreshTask = "com.neelaypatel.rideapp.coach"
    /// The kinds of message the rider can turn off, in Settings.
    static let kinds: [(id: String, label: String)] = [("ride", "After every ride"), ("brief", "Morning brief, 07:30"),
                                                       ("change", "When the plan changes"), ("review", "Sunday review")]

    @Published var route: CoachRoute?

    private let center = UNUserNotificationCenter.current()
    private let shownKey = "coach.shown"
    private let log = Logger(subsystem: "com.neelaypatel.rideapp", category: "coach")

    static func enabled(_ kind: String) -> Bool { UserDefaults.standard.object(forKey: "coach.\(kind)") as? Bool ?? true }
    static func setEnabled(_ kind: String, _ on: Bool) { UserDefaults.standard.set(on, forKey: "coach.\(kind)") }

    /// At launch: so a tapped notification reaches the app, even one that launched it.
    func start() { center.delegate = self }

    /// Asked once, the first time Train opens.
    func askPermissionOnce() async {
        guard !UserDefaults.standard.bool(forKey: "coach.asked") else { return }
        UserDefaults.standard.set(true, forKey: "coach.asked")
        _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge])
    }

    /// Fetch the coach's messages and show the new ones. With the app open nothing pops up (Train shows it all);
    /// new messages are just marked as seen. The first time, everything already there is marked seen too.
    func refresh(appActive: Bool) async {
        guard ServerConfig.isConfigured else { return }
        let inbox: CoachInbox
        do { inbox = try await APIClient().trainInbox() } catch {
            log.error("inbox fetch failed: \(error.localizedDescription, privacy: .public)")
            return
        }
        let settings = await center.notificationSettings()
        log.info("inbox: \(inbox.items.count) items, \(inbox.scheduled.count) scheduled, active \(appActive), auth \(settings.authorizationStatus.rawValue)")
        let before = UserDefaults.standard.stringArray(forKey: shownKey)
        var shown = before ?? []
        for m in inbox.items.reversed() where !shown.contains(m.id) {
            shown.append(m.id)
            if before == nil || appActive || !Self.enabled(m.kind) { continue }
            log.info("posting \(m.id, privacy: .public)")
            add(m, at: nil)
        }
        UserDefaults.standard.set(Array(shown.suffix(200)), forKey: shownKey)

        // The morning brief: replace what's scheduled with the latest words.
        let pending = await center.pendingNotificationRequests().map(\.identifier).filter { $0.hasPrefix("brief:") }
        center.removePendingNotificationRequests(withIdentifiers: pending)
        guard Self.enabled("brief") else { return }
        let iso = ISO8601DateFormatter()
        for m in inbox.scheduled {
            if let when = iso.date(from: m.at), when > Date() { add(m, at: when) }
        }
    }

    private func add(_ m: CoachMessage, at date: Date?) {
        let content = UNMutableNotificationContent()
        content.title = m.title
        content.body = m.body
        content.sound = .default
        content.threadIdentifier = "coach"
        content.userInfo = ["screen": m.opens.screen, "ride_id": m.opens.rideId ?? "", "week_start": m.opens.weekStart ?? ""]
        let trigger: UNNotificationTrigger? = date.map {
            UNCalendarNotificationTrigger(dateMatching: Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: $0),
                                          repeats: false)
        }
        center.add(UNNotificationRequest(identifier: m.id, content: content, trigger: trigger))
    }

    /// Ask iOS to wake Kova in the background now and then, to check for the coach's messages.
    func scheduleBackgroundRefresh() {
        let request = BGAppRefreshTaskRequest(identifier: Self.refreshTask)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 45 * 60)
        try? BGTaskScheduler.shared.submit(request)
    }

    // MARK: UNUserNotificationCenterDelegate

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        let screen = info["screen"] as? String ?? "today"
        let ride = info["ride_id"] as? String ?? ""
        let week = info["week_start"] as? String ?? ""
        Task { @MainActor in
            switch screen {
            case "ride" where !ride.isEmpty: CoachNotifier.shared.route = .ride(ride)
            case "week" where !week.isEmpty: CoachNotifier.shared.route = .week(week)
            default: CoachNotifier.shared.route = .today
            }
            completionHandler()
        }
    }

    /// The morning brief firing while Kova is open: show it anyway.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list])
    }
}

/// Settings › The coach: which messages Kova sends.
struct CoachSettingsCard: View {
    @State private var on: [String: Bool] = Dictionary(uniqueKeysWithValues: CoachNotifier.kinds.map { ($0.id, CoachNotifier.enabled($0.id)) })

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            MonoLabel("When the coach speaks up").padding(.bottom, 4)
            ForEach(CoachNotifier.kinds, id: \.id) { k in
                Toggle(k.label, isOn: Binding(get: { on[k.id] ?? true },
                                              set: { on[k.id] = $0; CoachNotifier.setEnabled(k.id, $0) }))
                    .font(Theme.text(15)).tint(Theme.cobalt).frame(minHeight: 44)
            }
            Text("Until Kova can send messages straight to your phone, they arrive when your iPhone wakes Kova: after a ride syncs, now and then in the background, or when you open it. The morning brief always arrives on time.")
                .font(Theme.text(12)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true).padding(.top, 6)
        }
        .padding(16).surfaceCard(radius: 22)
    }
}

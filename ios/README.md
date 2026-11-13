# Ride iPhone app (prototype)

SwiftUI app, iOS 17+, app ID `com.neelaypatel.rideapp`. Three tabs:
- **Rides**: merged rides from the backend (date, distance, moving time, avg/max HR, sources).
  A ride's detail view shows where each value came from and whether it may feed AI or be shared.
- **Connections**: Apple Health (permission, history import, background delivery) and the
  backend's provider list (Garmin personal key now; the rest show as coming soon).
- **Settings**: backend address and dev token. Sign in with Apple replaces the token later.

Apple Health scope: cycling workouts, their routes, and the heart rate, active energy and cycling
distance recorded during them. Read-only. Workouts written by Strava are skipped.

## Files
- `RideApp/HealthKitReader.swift`: queries HealthKit and builds the recording JSON.
- `RideApp/HealthSync.swift`: connect, history import, anchored sync, background delivery.
- `RideApp/APIClient.swift`: backend calls, server settings, Keychain.
- `RideApp/*View.swift`, `RideApp.swift`: screens.
- `Config/Info.plist`, `Config/RideApp.entitlements`: Health permission text, local-network access
  (dev), HealthKit + background delivery.
New Swift files dropped into `RideApp/` join the target automatically (synchronized folder).

## Run it on your iPhone
1. Install the latest Xcode (one that supports iOS 27), open it once, then run
   `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer`.
2. Xcode → Settings → Accounts: add your Apple ID.
3. Open `ios/RideApp/RideApp.xcodeproj`. Target RideApp → Signing & Capabilities → Team: your
   Personal Team (or paid team). Xcode registers the app ID and HealthKit for you.
4. Connect the iPhone by cable, trust the Mac, turn on Settings → Privacy & Security → Developer
   Mode, then pick the phone as the run destination and press Run.
5. On the Mac, from the repo root:
   ```
   python -m backend create-user          # prints the server address and token for the phone
   python -m backend serve --host 0.0.0.0
   ```
   Phone and Mac on the same Wi-Fi. In the app: Settings → paste the address and token → Save.
   Allow local network access when asked.
6. Connections → Connect Apple Health → turn on all five types → Continue → choose **All Recorded
   Data** (iOS 27 asks; "Past 30 Days" would limit the history import) → Allow. History since the
   chosen date uploads; new rides then arrive in the background as long as Settings → General →
   Background App Refresh is on for Ride.

Checked in the Simulator (iPhone 18 Pro, iOS 27.2, 13 Nov 2026): builds with Xcode 27.2, settings
and dev login, Rides list and detail, Connections list, Health permission sheet (exactly the five
read types), connect + background delivery setup. Not yet checked: real workouts (the Simulator
has none) and background wake-ups, which need the iPhone.

Simulator builds without signing can't use the Keychain, so the token won't save; Xcode's Run
signs the app locally and it works.

With a free Apple ID the app stops opening after 7 days until you press Run again.
Background sync to the Mac only works while the phone can reach it (same network, server running).

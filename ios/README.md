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
Done on Neelay's iPhone, 14 Nov 2026 (iOS 27.2, Xcode 27.2, free Personal Team `535NY4Z9DP`, set in the project).
1. Xcode → Settings → Accounts → + → Apple Account. A free account works (Personal Team).
2. Plug the phone in, unlock it, tap **Trust**. If no prompt appears, open Finder and click the phone in the sidebar.
3. **Developer Mode only shows up after Xcode pairs with the phone.** If Settings → Privacy & Security has no
   Developer Mode yet: `xcrun devicectl list devices`, then `xcrun devicectl manage pair --device <identifier>`.
   Turn it on, restart, unlock, tap Turn On.
4. Build and install (or press Run in Xcode with the phone as destination):
   ```
   xcodebuild -project ios/RideApp/RideApp.xcodeproj -scheme RideApp -destination 'platform=iOS,id=<UDID>' -allowProvisioningUpdates build
   xcrun devicectl device install app --device <UDID> <DerivedData>/Build/Products/Debug-iphoneos/RideApp.app
   ```
   First launch fails until you trust yourself: Settings → General → VPN & Device Management → Developer App →
   Apple Development: … → Trust.
5. On the Mac: `scripts/mac-server.sh install` (the server as a login service; or run
   `python -m backend serve --host 0.0.0.0` by hand), and a token for your existing account:
   `python -m backend new-token --user 1 | awk '/^token /{printf "%s", $2}' | pbcopy` (copies it without showing
   it; Universal Clipboard pastes it on the phone). In the app's Settings: server `http://<mac>.local:8000`, paste the
   token, Save. Allow local network access.
6. Sources → Connect Apple Health → turn on every item → **All Recorded Data**. Rides upload, then two years of
   recovery readings. Keep Background App Refresh on for Ride.

With a free account the app stops opening after 7 days: plug in and install again.
Background sync to the Mac only works while the phone can reach it (same network, server running).

Checked in the Simulator (iPhone 18 Pro, iOS 27.2, 13 Nov 2026): builds with Xcode 27.2, settings
and dev login, Rides list and detail, Connections list, Health permission sheet (exactly the five
read types), connect + background delivery setup. Not yet checked: real workouts (the Simulator
has none) and background wake-ups, which need the iPhone.

Simulator builds without signing can't use the Keychain, so the token won't save; Xcode's Run
signs the app locally and it works.

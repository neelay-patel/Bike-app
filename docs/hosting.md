# Hosting and TestFlight: sharing the app with other riders

Written 18 Nov 2026. **Step 4 done 23 Nov 2026 for Neelay**: the backend runs on Fly.io (app `kova-backend`, region
yyz/Toronto, one always-on `shared-cpu-1x` machine with 1 GB, a 3 GB encrypted disk `kova_data` mounted at
`/app/data` with Fly's daily snapshots kept 5 days), at `https://kova-backend.fly.dev`. `Dockerfile`, `fly.toml` and
`scripts/host-start.sh` (which unpacks an uploaded `incoming.tar.gz` of the Mac's data before the server starts,
and serves with no access log since the calendar feed's secret is in its address). Secrets in Fly's store only. The
phone signs in with its existing dev token (moved with the database) until Sign in with Apple; the Mac's server is
retired and its `data/` is a backup. Still to do from below: Sign in with Apple, delete account, object storage and
Litestream (when there are other riders), a domain, Garmin Starter tier, privacy policy, TestFlight.
The rest of this was the plan. The goal: put the app on TestFlight so other riders can use it, and stop
depending on the Mac. Today the backend runs in a terminal on Neelay's Mac mini, and the phone reaches it only on the
home Wi-Fi (`http://Neelays-Mac-mini.local:8000`), so rides recorded away from home arrive only once he's back. A
hosted backend fixes that for him too.

Ruled out: Tailscale (Neelay didn't want it), and public tunnels (ngrok, Cloudflare Tunnel) or router port
forwarding. Those would put ride, health and home data on the open internet, protected only by a dev token.

## What changes

| | Today | Hosted |
|---|---|---|
| Server | Mac mini, terminal tab, home Wi-Fi only | Cloud machine with an HTTPS address, reachable anywhere |
| Sign-in | Dev bearer token pasted into Settings | Sign in with Apple (`users.apple_sub` is already in the schema) |
| App install | Free Personal Team, reinstall every 7 days | TestFlight (paid developer account) |
| Garmin | Personal API key, Neelay's account only | Garmin Connect Developer Program, Starter tier (OAuth + push) for everyone else |
| Apple Health | Phone pushes to the Mac | Phone pushes to the hosted server (no change in the app's logic) |
| Database | SQLite, 288 MB for one rider | SQLite on a disk at first, slimmed; Postgres once there are more riders |
| Ride files | `data/backend/raw/` (112 MB) | Object storage (Cloudflare R2 or S3) |
| Map data | `data/osm/` (256 MB map, 0.8 MB gravel grid), `data/geo/` (21 MB), `data/dem/` (cache) | Built on the Mac, uploaded to the server's disk |

## Steps, in order

### 1. Apple Developer Program
- Join ($99 a year, in Neelay's name). Keep the bundle id `com.neelaypatel.rideapp`.
- This ends the 7-day reinstall and makes TestFlight possible. Neelay can switch to TestFlight builds for himself
  straight away, still pointed at the Mac.
- Turn on the Sign in with Apple capability for the app id.

### 2. Get ready before moving (on the Mac, no hosting needed)
- ~~**Slim the store**~~ (done 20 Nov 2026): rides' and recordings' JSON is stored compressed (`db.pack`), 292 MB
  to 65 MB for 198 rides, and the ride list reads a small stored brief per ride instead of every ride's samples
  (1.7 s to under 0.01 s). The originals in `raw/` stay as they are.
- **Delete account**: one call that removes the rider, every connection, recording, ride, course and file. Apple
  expects in-app account deletion for apps where you create an account.
- **Settings from the environment only**: database, raw files location, secret key, public URL and the Garmin keys
  already come from `backend/config.py` and environment variables. Add the object-storage location, and keep the
  secret key out of files on the server.
- **Health check and logs** fit for a host: `/health` exists. Add request logging without tokens or ride data.

### 3. Sign in with Apple
- App: the Sign in with Apple button (AuthenticationServices) on first open, replacing the server URL and token
  fields. The dev fields stay hidden behind a developer switch for Neelay.
- Backend: check Apple's identity token (its signature against Apple's public keys, the audience, expiry), find or
  create the user by `apple_sub`, and return a session token the app keeps in the Keychain. The CLI keeps dev
  tokens for testing.
- Every API call is already scoped to the signed-in user (`Depends(user)`), so riders can't see each other's data.
  Add a test that one rider can't read another's rides, courses or recovery.

### 4. Host the backend
- **Recommendation: a small app platform with a Toronto region and a disk.** Fly.io (has a Toronto region), Railway or
  Render all fit. A plain server (Hetzner, DigitalOcean) is cheaper but more to look after.
- **One machine for now.** The backend runs its background work on threads in the same process: the insights
  worker, route checks, and the 15-minute Garmin poll. Two machines would each run them. Fine until there are many riders.
- **Database:** SQLite on the machine's disk to start (WAL mode, as now), with continuous backups to object storage
  (Litestream does this). Move to Postgres when it's more than a handful of riders, or before a second machine.
- **Files:** original ride files and route GPX files in object storage (Cloudflare R2 has no download fees). Map
  data (`map.sqlite3`, gravel grid, GeoNames) is built on the Mac (`python -m backend build-map …`) and copied to the
  disk. Elevation tiles cache themselves on first use.
- **Domain and HTTPS:** a domain (for example `api.<name>.app`) pointed at the host, which provides the certificate.
  The same domain serves the privacy policy and the OAuth return addresses.
- **Secrets** in the host's secret store: the encryption key for stored credentials (`backend/crypto.py`), the
  Garmin program keys, later an Anthropic API key (docs/coaching.md section 7).

### 5. Move Neelay's data
- Stop the Mac server, copy the slimmed database and the raw files up, start the hosted one, and point the app at
  the new address (or sign in with Apple and attach his existing user to his Apple id).
- His Garmin personal key keeps working for his own account only. Everyone else uses step 6.
- Check the verified numbers (CLAUDE.md) on the hosted copy before switching off the Mac.

### 6. Garmin for other riders
- **Apply early:** the Garmin Connect Developer Program reopened in Oct 2026 (docs/connectors.md). The Starter tier is
  free for about 1,000 users, with sign in with Garmin (OAuth) and **push only: Garmin sends new activities to our
  webhook. No history**, so a new rider's past rides come from their Apple Health import.
- Build the Starter connector next to `garmin_personal`: the OAuth flow (needs the fixed return address from step 4)
  and the push webhook (needs the public HTTPS address). The 15-minute poll stays for the personal key only.
- Wahoo, Whoop, Oura, Google Health follow the same pattern (CLAUDE.md next steps). Read each one's terms in full and
  fill in `SOURCE_POLICY` before showing their data to anyone or using it with AI.

### 7. Privacy, which TestFlight and Apple check
- **Privacy policy** on the domain. Any app that uses HealthKit must have one. It should say:
  - what we read from Apple Health (the list in CLAUDE.md's rules, nothing more);
  - that the data is stored on our server for the rider's own use;
  - recovery data is never shown to others;
  - no advertising, nothing sold;
  - how to delete it all.
- **App Store Connect privacy answers:** health and fitness, precise location (routes, home), contact info (Apple id
  email, if kept), all linked to the rider, none used for tracking.
- **Apple's health-data rules:** no advertising use and nothing in iCloud. Storing it on our own server with the
  rider's consent is fine.
- **Home and privacy zones:** a rider's home is private. It stays on the server, and ride cards hide the route
  near it (already built). Shared cards ask first when a source isn't cleared for sharing (already built).

### 8. TestFlight
- **Internal testers:** up to 100 people added in App Store Connect get builds immediately, with no review. Start
  with a few riding friends.
- **External testers:** a public link for up to 10,000 people. The first build goes through Beta App Review, which
  needs a "what to test" note, a contact and the privacy policy.
- Builds come from Xcode (Product → Archive → Distribute) or `xcodebuild archive` + upload. Each build lasts 90 days.

## Costs (first months)
- Apple Developer Program: $99 a year.
- Hosting: roughly $10–25 a month for one small machine with a disk.
- Object storage: a few dollars a month at this size.
- Domain: about $15–30 a year.
- Garmin Starter tier: free.

## Decisions for Neelay
1. When to join the Apple Developer Program (it unblocks Sign in with Apple and TestFlight for himself even before
   hosting).
2. Which host (Fly.io is the default choice above) and the domain name.
3. When to apply for the Garmin Starter tier (approval can take weeks; worth doing early).
4. Who the first testers are, and whether they're internal (no review) or a public link.

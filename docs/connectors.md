# Connectors plan

Decided 13 Nov 2026: **ride data from external sources comes first.** Ride summaries, insights and
cards come later, on top. Ingest must be as seamless as possible: the rider signs in to each account
once and every ride arrives on its own, merged.

Connectors needed: **Apple Health, Garmin, Wahoo, Hammerhead, Whoop, Oura, Fitbit (Google).**
Strava stays excluded (terms bar AI use and showing data to others).

## Decisions
- **Direct integrations, not an aggregator.** At our scale the official APIs are free (Garmin up to
  ~1,000 users, Wahoo, Whoop, Oura, Google). They give us original .FIT files, which aggregators
  tend to flatten into summaries. Aggregators cost about $0.50–2 per user per month, and Oura's 2026
  terms specifically stop aggregators passing its data to AI. Aggregator (e.g. Terra) only as a
  fallback for Hammerhead.
- **Hosted backend now** (Python, FastAPI, SQLite in dev and Postgres hosted). OAuth sign-in needs a
  fixed public return address, and Garmin/Wahoo/Whoop/Oura push new rides to webhooks.
- **Apple Health has no web API**: the iPhone app is its connector (HealthKit permission,
  history import, background delivery, upload to the backend).
- **Per-source use flags.** Some providers restrict AI use or showing data to other people. Every
  value already records its source (`Ride.provenance`), so `rideengine/sources.py` holds a policy
  per source and insights/cards check it. Unreviewed = not allowed.

## Providers (checked 13 Nov 2026)
| Source | How the rider connects | What we get | Catch |
|---|---|---|---|
| Apple Health | Permission screen in our iPhone app | Route, HR (~5 s), calories, climbing | Phone only; background delivery for new rides |
| Garmin | Sign in (program reopened Oct 2026, tiers Personal / Starter / Enterprise) | Original .FIT plus JSON summaries | Starter: free, ~1,000 users, push only, **no history**. Enterprise: history, paid. Personal key: one person's own data only, not for multi-user apps |
| Wahoo (KICKR, ELEMNT) | Sign in (OAuth2) | Original .FIT (KICKR power) | App review before production |
| Hammerhead (Karoo) | **No official public API** | — | Ask SRAM/Hammerhead for partner access; fallback Terra |
| Whoop | Sign in (OAuth2, API v2) | Workout summaries: avg/max HR, kJ, zones | **No HR stream**: totals only |
| Oura | Sign in (OAuth2, API v2) | Workouts + HR time series | Membership needed on newer rings; June 2026 terms appear to bar AI use |
| Fitbit | Sign in with Google (Google Health API v4) | Exercise sessions, HR, GPS (TCX) | Fitbit Web API switched off ~30 Oct–2 Nov 2026; all Google Health scopes are Restricted (privacy and security review before launch) |

Terms to read in full before launch: Garmin (a quoted clause bars building AI models from its data;
passing data on to others needs permission), Oura (AI), Whoop, Wahoo, Google (Restricted scopes),
Apple (HealthKit data may not be used for advertising or sold).

## Architecture
```
iPhone app ──(HealthKit JSON upload)──┐
Garmin / Wahoo / Whoop / Oura / Google ──(webhook or scheduled pull)──┤
                                       ▼
backend/  connections (encrypted tokens) → raw file kept → connector.normalize() → Recording
          → rideengine merge (per user, within the ride's time window) → Ride (+ provenance)
```
- `backend/connectors/`: one module per provider, all implementing `base.Connector`
  (connect, fetch new, normalize to `Recording`). `registry` lists every provider with its status, so
  the app's Connections screen can show "available" vs "coming soon".
- Every original file is kept (`data/backend/raw/` in dev, object storage later) so rides can be
  re-processed when the engine improves.
- Re-imports are idempotent: one recording per (user, source, provider activity id).
- Disconnecting deletes that provider's tokens and data.

## Order of work
1. Done 13 Nov 2026: backend skeleton + connector framework; Garmin personal-key connector (pull);
   upload endpoint for Apple Health.
2. Built 13 Nov 2026, not yet run on a device: iPhone app with the Apple Health connector (permission
   for workouts, routes, heart rate, active energy and cycling distance; history import; background
   delivery; upload), Connections and Rides screens, dev login. Next: run it, then Sign in with Apple.
3. Garmin Starter (OAuth + push webhook), so other riders can connect.
4. Wahoo (in time for the KICKR).
5. Whoop, Oura, Google Health. Need a tester who owns each device.
6. Hammerhead once access is agreed, else the aggregator fallback.

## Neelay's to-do (approvals take time)
- Garmin: create a personal API key (connect.garmin.com → Settings → Personal API) now; apply for the
  Starter tier.
- Developer apps: Wahoo, Whoop, Oura; a Google Cloud project with the Google Health API.
- Email Hammerhead/SRAM about partner API access.
- A domain plus a short privacy policy page (every provider asks for one; fixed OAuth return address).
- Apple Developer Program ($99/yr): Sign in with Apple, background delivery, TestFlight.
- The latest Xcode (iOS 27 support) and Python 3.13 on this Mac.

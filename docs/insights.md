# Insights: how they're worked out for every rider

Built 13–14 Nov 2026. The rules live in the engine (`rideengine/analysis/`); the backend
(`backend/insights.py`) stores the results and keeps them up to date as rides arrive. Nothing here is
specific to one rider: home, routes, climbs and their names are all found from each rider's own rides.

## When a ride arrives (sync, upload, or a re-merge)
1. **Features, once.** `features.extract(ride)` reads the samples (the slow part) and keeps a small
   summary: totals, the ~300 m grid cells the route visits, start and finish points, and the climbs
   detected in it. Stored in `ride_features`.
2. **Matched, not searched.** The ride is compared with the rider's known routes (grid cells) and timed
   on their known climbs (only if it visits the cells around both gates). Laps and attempts are stored.
3. **Marked dirty** from the ride's start, and a refresh is scheduled.

## Refresh (a worker thread on the server; inline in tests and the command line)
1. **New routes:** rides that aren't laps of a known route, grouped by shared ground; 3+ make a route.
2. **New climbs:** detections that aren't a known climb, seen on 2+ rides; fixed start and finish gates
   are set, then every ride that might pass is loaded and timed; 3+ attempts make a climb.
3. **Home loop:** the most-ridden route that starts and finishes where most rides start.
4. **Names, once:** from GeoNames, when a route or climb is made. The rider can rename either one
   (`PATCH /v1/routes/{id}`, `/v1/climbs/{id}`); their name always wins.
5. **Notes:** a ride's notes depend only on the rides before it, so only notes from the dirty point
   (less a day) are redone. A late or back-filled ride redoes the notes after it, nothing before.
6. If rides changed while it ran, nothing is written and it runs again.

Routes and climbs keep their ids for good. One whose rides have all gone (a provider disconnected)
is deleted with them. Everything derived can be rebuilt: `python -m backend rebuild-insights --user N`
(the rider's own names are kept).

## Reads
`GET /v1/you` and the notes on `/v1/rides` only read stored rows. `"updating": true` while a refresh is
pending. Dates, years and streaks use the rider's time zone (`PUT /v1/me {"tz": ...}`; the app sends it).

## Checked
- Rides arriving one at a time, in any order, give exactly the same routes, climbs and notes as
  working everything out at once (`tests/test_insights.py`).
- Neelay's 97 rides: built from scratch in ~6 s, once; reads ~0.1 s.

## Still to do before other riders
- **Real job queue and Postgres** when hosted (the worker thread and SQLite are fine for one machine).
- **The rides list** still loads every ride's samples to describe it; serve it from stored rows.
- **Push notifications** for new bests (needs the paid developer account).
- **Thresholds on other terrain:** tuned on Toronto and London; test on mountains and on rides with
  many short climbs before launch.
- **Per-ride time zone** (a ride abroad uses the rider's home zone for now).
- **Privacy zones:** home is now known; share cards must hide the start and finish near it.
- **GeoNames for every country** on the server (the dev machine has cities500 + Canada).

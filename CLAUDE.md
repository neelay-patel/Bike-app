# Bike-app — context for Claude Code

Neelay's cycling app. Built for himself first, hoping for wide adoption; not a business (yet).
He rides gravel and road around Toronto (previously London), records every ride on a **Garmin**
and an **Apple Watch** (Cycling workout started each time; iPhone on iOS 27), currently pushes both to Strava,
and has a **Wahoo KICKR** arriving. No power meter on the bike. He likes to work in a
"vibe coding" style: short iterations, see results, adjust.

## The product idea
Existing apps (Strava, Garmin Connect, Komoot...) keep one recording per ride and give thin,
boastful summaries. This app:
1. **Merges every device's data into one ride**, field by field (Garmin route + climbing,
   Apple Watch heart rate + calories, KICKR power). See `docs/data-sources.md`.
2. **Tells the ride's story** in a beautiful, insight-led share card. See `docs/share-card.md`.
3. **Gives real post-ride value**: trends and coaching organised around what riders want, in
   order: **ride faster, ride further**, fed by **more power** and **climbing faster**.
   See `docs/app-and-insights-plan.md`.

Current focus (from 13 Nov 2026): **ride data from external sources first**. The rider signs in to
each account once and every ride arrives on its own, merged. Connectors: Apple Health, Garmin,
Wahoo, Hammerhead, Whoop, Oura, Fitbit (Google). Direct integrations, not an aggregator.
Summaries, insights and cards come later. See `docs/connectors.md`.
After that, three buckets in order (`docs/roadmap.md`): insight and tallies (started 13 Nov 2026), fun (avatar, rider card,
badges), training and coaching. Notes and coaching text stay rule-based until the providers' AI terms are read.

## Repo layout
- `rideengine/model.py`: canonical format. `Recording` = one device's view; `Ride` = merged, with `provenance`.
- `rideengine/importers/`: `fit.py` (dependency-free FIT decoder), `gpx.py`, `apple_health.py` (streams export.zip, keeps only cycling workouts + heart rate during them), `recording_json.py` (the exchange format the iPhone app uploads: `asdict(Recording)` + `"format": "rideengine.recording/1"`).
- `rideengine/sources.py`: which source wins for each channel/total, and `SOURCE_POLICY` (may a source's data feed AI / be shown to others; unreviewed = no). Change rules here, not in merge code.
- `rideengine/merge.py`: group recordings by time overlap, merge onto the bike computer's timeline.
- `rideengine/places.py`: towns/villages the route passes, offline from GeoNames (data/geo/, git-ignored; `python -m rideengine.places --download` then `--download CA`). Stops of 10+ min rank first. Credit GeoNames (CC BY 4.0).
- `rideengine/clean.py`: leaves out stretches that weren't riding (bike computer left on in a car: sustained >65 km/h, cut between the surrounding long stops). Merge then redoes the affected totals and lists the cut in `Ride.excluded`. `hidden_reasons()`/`visible()` mark false starts and empty recordings (kept, but left out of lists and trends).
- `rideengine/store.py`: JSON file store under `data/store/` (keeps all recordings, rebuilds rides). Placeholder for a real DB.
- `rideengine/analysis/`: `basics` (moving time, stops, summary), `climbs` (detect + match across rides), `fitness` (efficiency, TRIMP, fitness/fatigue), `records` (tallies, streaks, personal bests, and each ride's rule-based notes such as "your longest ride yet", worked out as of the ride's date), `features` (what each ride contributes, extracted once: totals, grid cells, detected climbs), `repeats` (repeated routes incl. the home loop, and repeated climbs timed between fixed start/finish points like segments, named from GeoNames; works incrementally on stored features), `wellness` (heart-rate recovery after rides; HRV, resting HR and VO2 max against the rider's own usual range; see `docs/recovery.md`), `simpower` (SIMULATED power, prototyping only).
- `rideengine/card/`: `ride_card.py`, the collectible ride card in the chosen look (D), from a Ride; `make_card.py` is the older graphite card (prototype). `python -m backend card --user 1 <ride_id>`.
- `design/tokens.json` + `docs/design.md`: the look (direction D, 13 Nov 2026). The app's `Theme.swift` copies the tokens (test checks they match); fonts bundled in `ios/RideApp/RideApp/Fonts/` with their licences.
- `rideengine/__main__.py`: CLI (`python -m rideengine import|rides|show|trends|card`).
- `backend/`: hosted service (FastAPI; SQLite in dev, Postgres later). `service.py` (users, connections, sync, upload, re-merge by time window), `connectors/` (one module per provider on `base.Connector`; `__init__` lists all seven with status), `insights.py` (stored, incremental insights: features per ride, routes, climbs, laps, attempts, notes; background refresh; see `docs/insights.md`), `app.py` (HTTP API), `crypto.py` (credentials encrypted at rest), `__main__.py` (dev CLI). Dev data in `data/backend/`. Dependencies in `requirements-backend.txt`; the engine itself stays stdlib-only.
- `ios/RideApp/`: iPhone app (SwiftUI, iOS 17+, `com.neelaypatel.rideapp`), styled in look D (porcelain, serif titles, Plex text, dot-matrix hero numbers, real halftone elevation profile). Apple Health connector (HealthKit permission, history import, anchored sync, background delivery, upload), Rides (with each ride's notes), You (recovery, tallies, streaks, bests, home loop, repeated routes and climbs with their history), Connections, dev login (server URL + token). Setup: `ios/README.md`.
- `tests/`: `test_engine.py` and `test_recording_json.py` (synthetic, always run), `test_backend.py` (mocked Garmin; skips without backend deps), `fitwriter.py` (tiny FIT writer for tests), `test_real_rides.py` (skips unless Neelay's files are in `data/`).

## Rules
- **Never commit personal data.** Ride files, the Apple Health export and anything derived live in `data/` (git-ignored). Tests that need them must skip when absent.
- From Apple Health, read **only** (Neelay agreed; widened 14 Nov 2026): cycling workouts with their route, heart rate,
  calories and distance; heart rate in the **3 minutes after** each ride (recovery); and **VO2 max, HRV (SDNN), resting
  heart rate and Cardio Recovery** (recovery and fitness insights). Never sleep, other workouts, or anything else.
  Recovery data (`metrics`) is **never shown to other people**, whatever `SOURCE_POLICY` says.
- **Strava is not a data source.** Its API terms bar AI use and showing a user's data to others.
- Prefer device totals (barometric climbing, moving time, wearable calories) over values derived from GPS. Record where every value came from.
- **Simulated power must always be labelled** (SIM) and never feed real totals (calories, load).
- Calories: the wearable wins (Neelay's call), then energy from measured power, then the head unit.
- Python 3.11+, standard library only for the engine (keeps it portable to a backend). pytest for tests.
- Request only the data a ride needs from every provider (workouts and HR during them), keep the original files, and delete a provider's data when the rider disconnects it.
- Garmin's personal API key is for Neelay's own account only (Garmin's terms); other riders connect through the Starter tier.

## Commands
```
python -m pytest -q
python -m rideengine import data/*.fit data/*.gpx data/*.json --apple data/export.zip --since 2025-01-01
python -m rideengine rides
python -m rideengine show <ride_id>
python -m rideengine trends
python -m rideengine you                            # tallies, streaks, personal bests
python -m rideengine card <ride_id> --config examples/card_durham_forest.json --power
# .venv is Python 3.13 (uv-managed, ~/.local/share/uv/python). Apple's /usr/bin/python3 (3.9,
# LibreSSL) can't do TLS 1.3, which Garmin requires. Rebuild: <python3.13> -m venv .venv
.venv/bin/pip install -r requirements-backend.txt
python -m backend create-user                       # dev user + bearer token
python -m backend connect-garmin --user 1 --since 2026-10-01
python -m backend rides --user 1
python -m backend rebuild --user 1                  # re-merge stored rides after an engine change
python -m backend you --user 1                      # same, from the backend (GET /v1/you)
python -m backend rebuild-insights --user 1         # rework routes, climbs, notes (keeps custom names)
python -m backend set-tz --user 1 America/Toronto
python -m backend serve                             # API docs at http://127.0.0.1:8000/docs
```

## Verified numbers (for sanity checks)
- Durham Forest, 3 Oct 2026 (Garmin FIT + Apple Watch): 68.7 km, 1,139 m, 3:55 moving, avg HR ~144, max 173, 1,973 kcal (Apple active).
- Scugog loop, 19 Oct 2026 (Garmin GPX + Apple Watch): 104.5 km, 633 m (from Garmin track), 23.8 km/h, avg HR 142, max 170, 2,463 kcal.
  From the Garmin .FIT via the personal API (13 Nov 2026): 104.3 km, 850 m (device barometric total, which wins over the 633 m GPX-track figure), 4:25 moving.
- Durham Forest via the Garmin personal API (13 Nov 2026): 68.7 km, 1,139 m, 3:55 moving. Matches.

## Next steps (order in docs/connectors.md)
1. Try the Garmin personal-key connector on Neelay's account; compare with the verified numbers.
2. iPhone app: run it on Neelay's iPhone (iOS 27; needs the latest Xcode), connect Apple Health,
   check Durham Forest merges. Then Sign in with Apple (paid developer account) in place of the dev token.
3. Garmin Starter tier (OAuth + push webhook) so other riders can connect; host the backend.
4. Wahoo (KICKR power), then Whoop, Oura, Google Health; Hammerhead once access is agreed.
5. Read each provider's terms in full and fill in `SOURCE_POLICY`.
6. Slim the store before hosting (parked 13 Nov 2026): every ride's per-second samples are stored twice as JSON
   (the recording and the merged ride): 170 MB for 97 rides. Store merged samples once, compactly.

## Linked work in claude.ai (Project "Cycling app")
- Share card canvas: https://claude.ai/artifact/6vEqXrfwo3ozkCh8byzDin
- Ride Trends dashboard: https://claude.ai/artifact/Tu5CgKUFQ84t6EsheDeLey

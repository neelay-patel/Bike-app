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
badges), training and coaching. Coaching is planned in `docs/coaching.md` (15 Nov 2026): data first (every source
automatically, no archive importers; Strava records nothing itself), goals in the rider's words, progress read from
normal riding, an AI coach that explains while the engine calculates. Data strategy: `docs/connectors.md`.

## Repo layout
- `rideengine/model.py`: canonical format. `Recording` = one device's view; `Ride` = merged, with `provenance`.
- `rideengine/importers/`: `fit.py` (dependency-free FIT decoder), `gpx.py`, `apple_health.py` (streams export.zip, keeps only cycling workouts + heart rate during them), `recording_json.py` (the exchange format the iPhone app uploads: `asdict(Recording)` + `"format": "rideengine.recording/1"`).
- `rideengine/sources.py`: which source wins for each channel/total, and `SOURCE_POLICY` (may a source's data feed AI / be shown to others; unreviewed = no). Change rules here, not in merge code.
- `rideengine/merge.py`: group recordings by time overlap, merge onto the bike computer's timeline.
- `rideengine/places.py`: towns/villages the route passes, offline from GeoNames (data/geo/, git-ignored; `python -m rideengine.places --download` then `--download CA`). Stops of 10+ min rank first. Credit GeoNames (CC BY 4.0).
- `rideengine/clean.py`: leaves out stretches that weren't riding (bike computer left on in a car: sustained >65 km/h, cut between the surrounding long stops). Merge then redoes the affected totals and lists the cut in `Ride.excluded`. `hidden_reasons()`/`visible()` mark false starts and empty recordings (kept, but left out of lists and trends).
- `rideengine/store.py`: JSON file store under `data/store/` (keeps all recordings, rebuilds rides). Placeholder for a real DB.
- `rideengine/analysis/`: `basics` (moving time, stops, summary), `climbs` (detect + match across rides), `fitness` (efficiency, TRIMP, fitness/fatigue), `records` (tallies, streaks, personal bests, and each ride's rule-based notes such as "your longest ride yet", worked out as of the ride's date), `features` (what each ride contributes, extracted once: totals, grid cells, detected climbs), `repeats` (repeated routes incl. the home loop, and repeated climbs timed between fixed start/finish points like segments, named from GeoNames; works incrementally on stored features), `wellness` (heart-rate recovery after rides; HRV, resting HR and VO2 max against the rider's own usual range; see `docs/recovery.md`), `simpower` (SIMULATED power, prototyping only).
- `rideengine/analysis/effort.py` (18 Nov 2026): Rides became **Efforts** in the app. An effort is a session: the real
  ride with its false starts folded in (indoor too: a trainer session under 5 min next to a longer one), other rides of
  the same kind in the same outing as parts, and phases read from the samples: warm-up, structured workout (steady
  blocks held within a few watts = trainer in ERG), own riding with harder pushes (power, or torque at held power =
  indoor climbs), pauses, cool-down, heart rate at matched power early vs late, climbs. Rule-based lines; an AI may
  retell them later, only from these numbers. API `GET /v1/efforts/{any ride id}`; `/v1/rides` items carry `effort`.
- `rideengine/analysis/headline.py`: the four headline numbers on top of You (17 Nov 2026): sustained power (FTP),
  punch (best minute), efficiency (W/beat on steady trainer stretches, else m/beat on flat steady outdoor minutes) and
  durability (late vs early efficiency on 2 h+ rides). Targets come from the goal and are kept with it (fixed baseline);
  the goal's markers are these four, nothing route-specific.
- `rideengine/analysis/goals.py`: the coaching engine's goals: options in the rider's words, seasons, the reveal (solo pace, drafting estimate, what to build), markers read from ordinary riding (rating, home loop speed at the same heart rate, climb, power curve). API `/v1/goals/options|preview|current`. See `docs/coaching.md`.
- `rideengine/analysis/plan.py`: training plans: zones (FTP and heart-rate reserve), the workout library (intervals with counts, durations, targets), the plan to the goal (phases, easier weeks, rider's days and times, season), did-you-do-it status, calendar feed (.ics) and Zwift (.zwo) export. API `/v1/plan…`, feed `/calendar/<secret>.ics`. App: Plan tab.
- `rideengine/analysis/collection.py`: the fun bucket's numbers: badges, rider ratings out of 99, season binder, holo rule. `rideengine/card/avatar.py` (avatar drawn in code from parts), `rider_card.py` (you as a trump card). See `docs/fun.md`.
- `rideengine/routes/`: planned routes (17 Nov 2026, `docs/routes.md`): `route.py` (GPX routes), `osm.py` (OpenStreetMap
  roads and stops along a route: our own map first, `data/osm/map.sqlite3` built by `python -m backend build-map
  data/osm/ontario-latest.osm.pbf` (`backend/mapdata.py`, pyosmium; Geofabrik extract), else cached Overpass tiles; surface classes paved/gravel/rough/trail/singletrack/unknown,
  never guessed), `check.py` (the route check: surfaces, singletrack, stops and refuel gaps, busy roads, straights, climbs,
  time at the rider's pace, cue sheet, verdict), `course.py` (FIT course with course points for the Edge, GPX), and tuning: `router.py` (our own bike router
  on the local map, gravel-aware costs), `elevation.py` (Terrarium elevation tiles, cached in data/dem/), `tune.py`
  (new start, add a stop, shorter/longer; each change a version you can undo), and routes from a description
  (18 Nov 2026): `request.py` (the rider's words to a request, rule-based: loop, one way, there and back) and
  `generate.py` (up to three routes on our map, scored, each saved as a checked course); `gravelmap.py` (where the gravel is: offers better starts when a gravel loop from home can't be one). The check picks a few rest stops (`rest_stops`), not every café. Backend `/v1/courses` (+ `/plan`, `/tune`, `/undo`, `/options`); app:
  Routes tab with Describe a ride and a Tune it card.
- `rideengine/card/`: `ride_card.py`, the collectible ride card in the chosen look (D), from a Ride (privacy zone around home, local or Google fonts); `make_card.py` is the older graphite card (prototype). Served at `GET /v1/rides/{id}/card` and shown at the top of each ride in the app, with Share (asks first when a source isn't cleared for sharing). `python -m backend card --user 1 <ride_id>`.
- `design/tokens.json` + `docs/design.md`: the look (direction D, 13 Nov 2026). The app's `Theme.swift` copies the tokens (test checks they match); fonts bundled in `ios/RideApp/RideApp/Fonts/` with their licences.
- `rideengine/__main__.py`: CLI (`python -m rideengine import|rides|show|trends|card`).
- `backend/`: hosted service (FastAPI; SQLite in dev, Postgres later). `service.py` (users, connections, sync, upload, re-merge by time window), `connectors/` (one module per provider on `base.Connector`; `__init__` lists all seven with status), `insights.py` (stored, incremental insights: features per ride, routes, climbs, laps, attempts, notes; background refresh; see `docs/insights.md`), `app.py` (HTTP API; home is the one the rider set in Settings, else where most of the past year's rides start: `Backend.home_point`, used for routes from home, the home loop, local times and the card's privacy zone), `crypto.py` (credentials encrypted at rest), `__main__.py` (dev CLI). Dev data in `data/backend/`. Dependencies in `requirements-backend.txt`; the engine itself stays stdlib-only.
- `ios/RideApp/`: iPhone app (SwiftUI, iOS 17+, `com.neelaypatel.rideapp`), styled in look D (porcelain, serif titles, Plex text, dot-matrix hero numbers, real halftone elevation profile). Apple Health connector (HealthKit permission, history import, anchored sync, background delivery, upload), Efforts (18 Nov 2026: new efforts since you last looked lead as their full ride card, swipeable, with Share and "What you did"; this month in one slim line; then "Your collection": every effort's mini card by month, older years folded, holo for personal bests, empty slots for missed weeks, or a list; `CollectionView.swift`), You (top to bottom: the rider card (top trumps) with Share, avatar and your bike, the four headline numbers with goal targets, fitness and recovery, badges, personal bests, all-time tallies, this year, the home loop; prizes put away until there's an engagement model; the season binder and "Lately" are gone, folded into Efforts; the bike is drawn natively in `BikeArt.swift` and is also the Efforts tab icon). One status line under each title (`StatusLine`, `Problem` in `RideApp.swift`): checking, out of reach (grey), or a real problem (red). Routes tab with the Route Enhancer; Connections, dev login (server URL + token). Setup: `ios/README.md`.
- `tests/`: `test_engine.py` and `test_recording_json.py` (synthetic, always run), `test_backend.py` (mocked Garmin; skips without backend deps), `fitwriter.py` (tiny FIT writer for tests), `test_real_rides.py` (skips unless Neelay's files are in `data/`).

## Rules
- **Never commit personal data.** Ride files, the Apple Health export and anything derived live in `data/` (git-ignored). Tests that need them must skip when absent.
- From Apple Health, read **only** (Neelay agreed; widened 14 Nov and 17 Nov 2026): cycling workouts with their route,
  heart rate, calories and distance, and **power, cadence and speed** from a sensor paired with the Watch (e.g. the KICKR)
  during them; heart rate in the **3 minutes after** each ride (recovery); and **VO2 max, HRV (SDNN), resting
  heart rate and Cardio Recovery** (recovery and fitness insights). Never sleep, other workouts, or anything else.
  Recovery data (`metrics`) is **never shown to other people**, whatever `SOURCE_POLICY` says.
- **Strava is not a data source.** Its API terms bar AI use and showing a user's data to others.
- Prefer device totals (barometric climbing, moving time, wearable calories) over values derived from GPS. Record where every value came from.
- **Simulated power must always be labelled** (SIM) and never feed real totals (calories, load).
- A trainer's km aren't road km, nor its climbing (Zwift's virtual metres, 18 Nov 2026): indoor rides count 0 km and
  0 m in tallies, bests and month totals (17 Nov 2026), and show
  time, power and heart rate instead. Average power is over pedalling time (zeros left out), as Zwift shows it.
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
python -m backend build-map data/osm/ontario-latest.osm.pbf   # our own map for the route check (Geofabrik extract)
python -m backend serve                             # API docs at http://127.0.0.1:8000/docs
scripts/mac-server.sh install|restart|status|logs   # the Mac's server as a login service (launchd): starts at login,
                                                    # restarts if it stops; log in data/backend/server.log.
                                                    # After a backend change: scripts/mac-server.sh restart
```

## Verified numbers (for sanity checks)
- Durham Forest, 3 Oct 2026 (Garmin FIT + Apple Watch): 68.7 km, 1,139 m, 3:55 moving, avg HR ~144, max 173, 1,973 kcal (Apple active).
- Scugog loop, 19 Oct 2026 (Garmin GPX + Apple Watch): 104.5 km, 633 m (from Garmin track), 23.8 km/h, avg HR 142, max 170, 2,463 kcal.
  From the Garmin .FIT via the personal API (13 Nov 2026): 104.3 km, 850 m (device barometric total, which wins over the 633 m GPX-track figure), 4:25 moving.
- Durham Forest via the Garmin personal API (13 Nov 2026): 68.7 km, 1,139 m, 3:55 moving. Matches.

## Where things stand (18 Nov 2026)
Built and on Neelay's iPhone (all pushed to origin/main):
- **Data:** Garmin personal-key connector (matches the verified numbers, 13 Nov); Apple Health (185 Watch rides,
  heart rate after rides, 2 years of HRV/resting HR/VO2 max, 14 Nov); KICKR power read via the Watch (17 Nov).
- **Efforts** (18 Nov): sessions with false starts folded in and phases read from the samples. Indoor km and climbing
  count 0.
- **You tab:** four headline numbers with goal targets, fitness and recovery, tallies with prizes, bests, home loop,
  Binder (rider card, bike, badges, avatar). **Plan tab:** training plan, calendar feed, Zwift export.
- **Routes:** check a GPX (surfaces, singletrack, busy roads, rest stops, time, cue sheet), our own Ontario map, send to
  the Edge (FIT course), tune it (shorter/longer, add a stop, start elsewhere, undo), and **describe a ride** (loops,
  one way, there and back; addresses via Apple Maps; "not much gravel near home" offers better starts).
- **Home:** set in Settings, else where most of the past year's rides start.
- **New rides arrive on their own** (18 Nov): the server pulls Garmin every 15 min (`Backend.start_polling`), and the
  app, each time it opens, sends new Watch rides and asks the server to check Garmin (`POST /v1/refresh`). Needs the
  phone on the home Wi-Fi until the backend is hosted. The Mac's server runs as a login service
  (`scripts/mac-server.sh`, 18 Nov), not in a terminal tab, so it survives sessions ending and restarts itself.

## Next steps
1. **Check Zwift via Garmin** after his next Zwift ride: it arrives as "Zwift (via Garmin)" and virtual climbing stays
   out of totals.
2. **Reinstall the app around 21 Nov 2026** (free Personal Team, 7-day profile). Then Sign in with Apple (paid
   developer account) in place of the dev token.
3. **Engine and AI** (`docs/coaching.md` section 7): agreed in principle, parked until Neelay decides. Order: match
   efforts to the plan, the AI layer (retelling efforts from the engine's numbers; needs an Anthropic API key in the
   backend's environment), re-planning, conversation. He has no goal set yet.
4. **Routes, next:** Garmin Courses API for one-tap sending (with the Starter tier); scenery scoring; starts at a café
   or car park rather than a town centre; move a one-way's destination in tuning; people to ride with
   (`docs/routes.md`).
5. **Other riders and TestFlight** (planned in `docs/hosting.md`, 18 Nov 2026): Apple Developer Program, slim the store
   (every ride's per-second samples are stored twice as JSON), delete account, Sign in with Apple, host the backend
   (also ends the home Wi-Fi limit), Garmin Starter tier (OAuth + push webhook, apply early), privacy policy, TestFlight.
6. **More sources:** Wahoo cloud, Whoop, Oura, Google Health; Hammerhead once access is agreed. Read each provider's
   terms in full and fill in `SOURCE_POLICY`.

## Linked work in claude.ai (Project "Cycling app")
- Share card canvas: https://claude.ai/artifact/6vEqXrfwo3ozkCh8byzDin
- Ride Trends dashboard: https://claude.ai/artifact/Tu5CgKUFQ84t6EsheDeLey
- Goal setting flow (mock-up, approved 15 Nov 2026): https://claude.ai/artifact/JCQyTJQ5XDZi9gvpCkXXcB

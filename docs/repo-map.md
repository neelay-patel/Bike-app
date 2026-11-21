# Repo map: the detail behind CLAUDE.md

CLAUDE.md keeps one line per module and a short list of what's built; this file has the detail (what each
module does, the APIs, the design choices and their dates). Decisions and the reasons for them are in
`docs/decisions.md`. Update this file when a module changes; keep CLAUDE.md to the one-line version.

## Modules in detail
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
- `rideengine/analysis/plan.py`: training plans: zones (FTP and heart-rate reserve), the workout library (intervals with counts, durations, targets), the plan to the goal (phases, easier weeks, rider's days and times, season), calendar feed (.ics) and Zwift (.zwo) export. API `/v1/plan…`, feed `/calendar/<secret>.ics`. App: Plan tab.
- `rideengine/analysis/train.py` (21 Nov 2026, `docs/train-tab.md` step 1): what kind of training each ride was (surges, sweet spot, threshold, VO2, endurance, long, easy, mixed) from 30 s power (heart rate when there's no power), with the reason in plain words; and which planned session each ride counts as, by what it contained, whatever the day (best total fit). Facts stored once in features v10 (`work`). The plan view's `counted`, `rides`, `extra` and `open` status; `PUT`/`DELETE /v1/plan/rides/{id}/counts-as` moves a ride (table `plan_matches`).
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
- `rideengine/card/`: `ride_card.py`, the collectible ride card in the chosen look (D), from a Ride (privacy zone around home, local or Google fonts).
  Redone 19 Nov 2026: name strip, the route map on blue (outdoors only), the numbers in dot-matrix on graphite, the colour
  ribbon, the headline on sand. Indoors there's no map or power trace (Neelay: it told him nothing); the app's indoor icon
  (SF Symbol `figure.indoor.cycle`, swapped in by `CardRenderer.embedFonts` for `indoor-mark.png`) sits in the panel's corner.
  360 wide and as tall as it needs (indoor cards are shorter; the app measures each); long names shrink to fit. `make_card.py` is the older graphite card (prototype). Served at `GET /v1/rides/{id}/card` and shown at the top of each ride in the app, with Share (asks first when a source isn't cleared for sharing). `python -m backend card --user 1 <ride_id>`.
- `design/tokens.json` + `docs/design.md`: the look (direction D, 13 Nov 2026). The app's `Theme.swift` copies the tokens (test checks they match); fonts bundled in `ios/RideApp/RideApp/Fonts/` with their licences.
- `rideengine/__main__.py`: CLI (`python -m rideengine import|rides|show|trends|card`).
- `backend/`: hosted service (FastAPI; SQLite in dev, Postgres later). `service.py` (users, connections, sync, upload, re-merge by time window), `connectors/` (one module per provider on `base.Connector`; `__init__` lists all seven with status), `insights.py` (stored, incremental insights: features per ride, routes, climbs, laps, attempts, notes; background refresh; see `docs/insights.md`), `app.py` (HTTP API; home is the one the rider set in Settings, else where most of the past year's rides start: `Backend.home_point`, used for routes from home, the home loop, local times and the card's privacy zone), `crypto.py` (credentials encrypted at rest), `__main__.py` (dev CLI). Dev data in `data/backend/`. Dependencies in `requirements-backend.txt`; the engine itself stays stdlib-only.
- `ios/RideApp/`: iPhone app (SwiftUI, iOS 17+, `com.neelaypatel.rideapp`), styled in look D (porcelain, serif titles, Plex text, dot-matrix hero numbers, real halftone elevation profile). Apple Health connector (HealthKit permission, history import, anchored sync, background delivery, upload), Efforts (18 Nov 2026: new efforts since you last looked lead as their full ride card, swipeable; tap it for the ride, with Share and "What you did"; this month in one slim line; then "Your collection": every effort's mini card by month, older years folded, holo for personal bests, empty slots for missed weeks, or a list; `CollectionView.swift`), You (top to bottom: the rider card (top trumps) with Share, avatar and your bike, the four headline numbers with goal targets, fitness and recovery, badges, personal bests, all-time tallies, this year, the home loop; prizes put away until there's an engagement model; the season binder and "Lately" are gone, folded into Efforts; the bike is drawn natively in `BikeArt.swift` and is also the Efforts tab icon). `Kova.swift`: the mark, the opening screen and Settings > About Kova. No big titles on the tabs (20 Nov). One status line at the top of each tab (`StatusLine`, `Problem` in `RideApp.swift`): checking, out of reach (grey), or a real problem (red). Routes tab with the Route Enhancer; Connections, dev login (server URL + token). Setup: `ios/README.md`.
- `tests/`: `test_engine.py` and `test_recording_json.py` (synthetic, always run), `test_backend.py` (mocked Garmin; skips without backend deps), `fitwriter.py` (tiny FIT writer for tests), `test_real_rides.py` (skips unless Neelay's files are in `data/`).

## What's built, in detail (as of 20 Nov 2026)
Built and on Neelay's iPhone (all pushed to origin/main):
- **Data:** Garmin personal-key connector (matches the verified numbers, 13 Nov); Apple Health (185 Watch rides,
  heart rate after rides, 2 years of HRV/resting HR/VO2 max, 14 Nov); KICKR power read via the Watch (17 Nov).
  Zwift via Garmin works (19 Nov): "Zwift (via Garmin)" with its climbing and virtual route (Watopia).
- **Kova** (19-20 Nov): the app's name on the phone (Finnish for strong; quick searches found no app of that name;
  Kado and Orka were tried first). Icon: "the climb", five columns of white dots rising to a yellow summit on
  graphite (`swift scripts/make_icon.swift ios/RideApp/RideApp/Assets.xcassets/AppIcon.appiconset/AppIcon.png
  --no-ribbon`). KOVA also stands for **Kilometres. Output. VO₂. Ascent.** (Ascent in the summit's yellow; Ascend
  was tried and dropped). Opening screen at launch (`Kova.swift`): one yellow dot slides up the climb column by
  column to the summit, then KOVA and the meaning, about 4 s, tap to skip, then it fades itself out (a removal
  transition from App state jumped in one frame); graphite launch screen (`LaunchBackground` in `Config/Info.plist`)
  so there's no white flash. Settings > About Kova: "Kova is Finnish for strong. It also stands for the four things
  we will help you build:", Ascent = "Rise to the climb." Mock-ups: https://claude.ai/artifact/LcEQTiwpvgb7D6hy49uFr9.
  Check the trademark before going public.
- **Efforts** (18 Nov): sessions with false starts folded in and phases read from the samples. Indoor km and climbing
  count in every tally, streak and Everest, split out as indoor (19 Nov; All Time shows outdoors/indoors). The tab:
  new efforts since you last looked lead as their full ride card (swipeable; tap it for the ride, with Share and
  "What you did"; no buttons under it since 20 Nov), this month in one slim line, then "Your collection" of every
  effort's mini card by month (holo for bests, empty slots for missed weeks; older years folded; or a list).
- **Ride card** (redone 19 Nov): dot-matrix numbers on graphite with the colour ribbon, the map on top outdoors, the
  indoor icon (and Climbed, when a ride game reports it) indoors. The collection's small cards match: route on blue;
  indoors on pale blue (cobaltSoft, 20 Nov; wine felt harsh) with Zwift's virtual route and world, else the
  session's power or heart-rate shape (`features.trace`). The ride screen: "What you did" has a titled Power (or
  Heart rate) chart with the session's phases, then the Elevation profile for outdoor rides.
- **You tab** (18 Nov): the rider card (top trumps) first with Share, avatar and your bike; then the four headline
  numbers with goal targets (known quirks, left as they are: sustained only moves on a new best 20 min;
  efficiency's baseline came from one ride; durability needs 2 h+ rides, so never indoors, and its bar was full
  from day one), fitness and recovery, badges, bests, tallies, this year, home loop. Prizes are put away (code kept).
  **Plan tab:** training plan, calendar feed, Zwift export.
- **Motion** (19-20 Nov, `Motion.swift`): dot-matrix numbers count up (headline numbers, tallies, month strip); a new
  effort's card springs in with a sheen; when new rides arrive, the all-time tallies slide up from the bottom and count
  on. "New" is tracked by start time, not ride id (ids change when the server re-merges a Watch ride with Garmin's).
- **Cleaner screens** (20 Nov): no big title on any tab (content starts at the top; Plan keeps its week and goal
  line, Sources its settings gear). One status line at the top of each tab: checking for new rides, out of reach
  (grey, with when data last loaded), or a real problem in red that says what to do.
- **Routes:** the Route Enhancer: check a GPX (surfaces, singletrack, busy roads, rest stops, time, cue sheet), our
  own Ontario map, send to the Edge (FIT course), tune it (shorter/longer, add a stop, start elsewhere, undo), and
  **describe a ride** (loops, one way, there and back; addresses via Apple Maps; "not much gravel near home" offers
  better starts).
- **Home:** set in Settings, else where most of the past year's rides start.
- **New rides arrive on their own** (18 Nov): the server pulls Garmin every 15 min (`Backend.start_polling`), and the
  app, each time it opens, sends new Watch rides and asks the server to check Garmin (`POST /v1/refresh`). Needs the
  phone on the home Wi-Fi until the backend is hosted. The Mac's server runs as a login service
  (`scripts/mac-server.sh`), so it survives sessions ending and restarts itself.

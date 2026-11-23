# Kova (Bike-app): context for Claude Code

Neelay's cycling app, **Kova** (the repo, Xcode project and bundle id are still Bike-app/RideApp). Built for himself
first, hoping for wide adoption; not a business (yet). He rides gravel and road around Toronto (previously London),
records every ride on a **Garmin Edge 840** and an **Apple Watch** (Cycling workout each time; iPhone on iOS 27), and
rides indoors on a **Wahoo KICKR** (power via the Watch; Zwift via Garmin). No power meter on the bike. He works in a
"vibe coding" style: short iterations, see results, adjust.

More detail lives in `docs/`: **`docs/repo-map.md`** (every module in detail, what's built), **`docs/decisions.md`**
(product decisions and why), and one doc per area (named below). Keep this file short; put detail there.

## The product idea
Existing apps keep one recording per ride and give thin, boastful summaries. Kova:
1. **Merges every device's data into one ride**, field by field (Garmin route + climbing, Watch heart rate + calories,
   KICKR power). `docs/data-sources.md`.
2. **Tells the ride's story** in a beautiful, insight-led card. `docs/share-card.md`.
3. **Gives real post-ride value**, around what riders want: **ride faster, ride further**, fed by **more power** and
   **climbing faster**. `docs/app-and-insights-plan.md`.
4. **Coaches like a good coach**: the plan follows the riding (a week of jobs any fitting ride can do), and every
   rule serves growth first, then earned encouragement, then teaching why. `docs/train-method.md`.

Order of work (`docs/roadmap.md`): data from every source automatically (`docs/connectors.md`; direct integrations,
not an aggregator), insight and tallies, fun (`docs/fun.md`), training and coaching (`docs/coaching.md`: goals in the
rider's words, progress read from normal riding, an AI coach that explains while the engine calculates).

## Repo map (detail: `docs/repo-map.md`)
- `rideengine/` (stdlib only): `model.py` (`Recording` = one device, `Ride` = merged with `provenance`),
  `importers/` (FIT, GPX, Apple Health export, the app's recording JSON), `sources.py` (which source wins per field,
  `SOURCE_POLICY`; change rules here, not in merge code), `merge.py`, `clean.py` (car stretches, false starts),
  `places.py` (GeoNames, offline), `store.py`.
- `rideengine/analysis/`: `basics`, `climbs`, `fitness`, `records` (tallies, streaks, bests, ride notes), `features`
  (per-ride extract, versioned), `repeats` (routes, home loop, climbs as segments), `wellness` (`docs/recovery.md`),
  `effort` (sessions and phases), `headline` (the four numbers), `goals`, `plan` (training plan, .ics, .zwo),
  `train` (what kind of training a ride was, which session it counts as), `today` (today's session or rest),
  `feedback` (one thing to try after each ride), `collection` (badges, ratings, binder),
  `simpower` (SIMULATED, prototyping only).
- `rideengine/routes/` (`docs/routes.md`): GPX routes, our OSM map, the route check, FIT courses, our router, tuning,
  routes from a description. `rideengine/card/`: the ride card (`ride_card.py`), avatar, rider card.
- `backend/`: FastAPI service (SQLite in dev): `service.py`, `connectors/` (one per provider), `insights.py`
  (`docs/insights.md`), `app.py` (HTTP API), `crypto.py`. Dev data in `data/backend/`. Rides' and recordings' JSON is stored compressed (`db.pack`/`unpack`); each
  ride also has a small `brief` the ride list reads (bump `service.BRIEF_VERSION` if `describe()` changes).
- `ios/RideApp/`: the iPhone app (SwiftUI, iOS 17+, `com.neelaypatel.rideapp`). Tabs: Efforts, Train (plan and
  coach, `TrainView.swift`), Routes, You, Sources. `Kova.swift` (mark, opening screen, About), `Theme.swift` (copies `design/tokens.json`; a test checks),
  `Motion.swift`. Setup: `ios/README.md`. App icon: `swift scripts/make_icon.swift <AppIcon.png> --no-ribbon`.
- `design/tokens.json` + `docs/design.md`: the look (direction D). `tests/`: synthetic tests always run; tests on
  Neelay's own files skip when `data/` is absent.

## Rules
- **Never commit personal data.** Ride files, the Apple Health export and anything derived live in `data/`
  (git-ignored). Tests that need them must skip when absent.
- From Apple Health, read **only**: cycling workouts with their route, heart rate, calories and distance, and
  **power, cadence and speed** from a sensor paired with the Watch during them; heart rate in the **3 minutes after**
  each ride; and **VO2 max, HRV (SDNN), resting heart rate and Cardio Recovery**. Never sleep, other workouts, or
  anything else. Recovery data (`metrics`) is **never shown to other people**, whatever `SOURCE_POLICY` says.
- **Strava is not a data source** (its terms bar AI use and showing a user's data to others).
- Prefer device totals (barometric climbing, moving time, wearable calories) over GPS-derived ones. Record where every
  value came from. Calories: the wearable wins, then energy from measured power, then the head unit.
- **Simulated power must always be labelled** (SIM) and never feed real totals (calories, load).
- **Indoor km and climbing count** in every tally, streak, Everest and month total, split out as `indoor`. Bests and
  single-ride badges stay road rides; no separate indoor bests or virtual segments. Only climbing a ride game reports
  counts, never invented from ERG power. Average power is over pedalling time (zeros left out), as Zwift shows it.
- Python 3.11+, standard library only for the engine. pytest for tests.
- Request only the data a ride needs from every provider, keep the original files, and delete a provider's data when
  the rider disconnects it.
- Garmin's personal API key is for Neelay's own account only; other riders connect through the Starter tier.
- Throwaway test servers run on a **copy** of `data/backend/`, never the real one. Before deleting rides in a copy,
  rewrite its relative `raw_path`s, or the real raw files get deleted.

## Commands
```
python -m pytest -q
python -m rideengine import data/*.fit data/*.gpx data/*.json --apple data/export.zip --since 2025-01-01
python -m rideengine rides | show <ride_id> | trends | you
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
python -m backend ai --user 1 on|off|status         # the AI coach (personal use; key in ~/.config/kova/), spend
python -m backend build-map data/osm/ontario-latest.osm.pbf   # our own map for the route check (Geofabrik extract)
python -m backend card --user 1 <ride_id>
python -m backend compact                           # compress stored rides and recordings (backs up the database first)
python -m backend serve                             # API docs at http://127.0.0.1:8000/docs
scripts/mac-server.sh install|restart|status|logs   # the Mac's server as a login service (launchd); log in
                                                    # data/backend/server.log. After a backend change: restart
```

## Verified numbers (for sanity checks)
- Durham Forest, 3 Oct 2026 (Garmin FIT + Apple Watch): 68.7 km, 1,139 m, 3:55 moving, avg HR ~144, max 173,
  1,973 kcal (Apple active). Same via the Garmin personal API.
- Scugog loop, 19 Oct 2026: 104.3 km, 850 m (Garmin barometric; the GPX track says 633 m), 4:25 moving, avg HR 142,
  max 170, 2,463 kcal.

## Where things stand (21 Nov 2026; detail in `docs/repo-map.md`)
On Neelay's iPhone, all pushed to origin/main:
- **Data:** Garmin (personal key), Apple Health (rides, recovery), KICKR power via the Watch, Zwift via Garmin. New
  rides arrive on their own: the server polls Garmin every 15 min; the app sends Watch rides and asks for a check
  each time it opens. Needs the home Wi-Fi until the backend is hosted; the Mac's server is a login service.
- **Kova:** name, "the climb" icon, opening screen (KOVA's letters rise in after the climb), About Kova.
- **Efforts:** new efforts lead as their full ride card, this month in one line, then the collection by month.
- **Train** (replaced Plan, 21 Nov; `docs/train-tab.md` steps 1-3 built): every ride classified by what it
  contained and counted against the week's sessions whatever the day; Today picks the session or rest (why, how it
  should feel, what's next); after each ride one constructive thing to try; the week as counted; the goal; the plan
  ahead (calendar feed, Zwift export). The coach's notifications (after a ride, 07:30 brief, plan changes, Sunday
  review). Indoors or out is always the rider's choice. Words: `docs/train-words.md`.
- **You:** rider card, the four headline numbers, fitness and recovery, badges, bests, tallies, home loop.
- **Routes:** check a GPX, tune it, the Route Generator (describe a ride, now with a climbing target), send to Edge.

## Next steps (detail: `docs/roadmap.md`)
1. **Reinstall the app by 28 Nov 2026** (free 7-day profile). The paid developer account is waiting on Apple support.
2. **Live with Train** (first session day Mon 23 Nov) and adjust the counting, picking and words from real use.
3. **Train steps 5-7** (`docs/train-tab.md`; notifications and the AI ride story built 21 Nov): the coach's
   morning brief and Sunday review, changing the plan by talking, sending sessions to the bike; and the Method (the
   research behind each rule, a coach's review). Goal: keep up with the fast group by 1 May 2027.
4. **A fun engagement model**, then bring prizes back (`PrizeShelf` in `YouView.swift` is kept). Idea from Neelay's
   son: "meta" (most effective tactic available) for the one thing to work on next.
5. **Routes:** Garmin Courses API, scenery, better starts, people to ride with (`docs/routes.md`).
6. **Other riders and TestFlight** (`docs/hosting.md`): developer account, Sign in with Apple, delete account,
   host the backend, Garmin Starter tier, privacy policy, Kova trademark check.
7. **More sources:** Wahoo, Whoop, Oura, Google Health, Hammerhead; read each provider's terms, fill `SOURCE_POLICY`.

## Linked work in claude.ai (Project "Cycling app")
- Share card canvas: https://claude.ai/artifact/6vEqXrfwo3ozkCh8byzDin
- Ride Trends dashboard: https://claude.ai/artifact/Tu5CgKUFQ84t6EsheDeLey
- Goal setting flow (mock-up, approved 15 Nov 2026): https://claude.ai/artifact/JCQyTJQ5XDZi9gvpCkXXcB
- Name and icon mock-ups (19-20 Nov 2026): https://claude.ai/artifact/LcEQTiwpvgb7D6hy49uFr9
- Train tab mock-up (21 Nov 2026): https://claude.ai/artifact/PqSSKTSmCHpzt5V63k8io2

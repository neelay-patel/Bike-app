# Bike-app — context for Claude Code

Neelay's cycling app. Built for himself first, hoping for wide adoption; not a business (yet).
He rides gravel and road around Toronto (previously London), records every ride on a **Garmin**
and an **Apple Watch** (Cycling workout started each time), currently pushes both to Strava,
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

Current focus (Nov 2026): **get the data right** (sources, merge, storage, automatic arrival).
Insights and dashboards run in parallel on top.

## Repo layout
- `rideengine/model.py`: canonical format. `Recording` = one device's view; `Ride` = merged, with `provenance`.
- `rideengine/importers/`: `fit.py` (dependency-free FIT decoder), `gpx.py`, `apple_health.py` (streams export.zip, keeps only cycling workouts + heart rate during them).
- `rideengine/sources.py`: which source wins for each channel/total. Change rules here, not in merge code.
- `rideengine/merge.py`: group recordings by time overlap, merge onto the bike computer's timeline.
- `rideengine/store.py`: JSON file store under `data/store/` (keeps all recordings, rebuilds rides). Placeholder for a real DB.
- `rideengine/analysis/`: `basics` (moving time, stops, summary), `climbs` (detect + match across rides), `fitness` (efficiency, TRIMP, fitness/fatigue), `simpower` (SIMULATED power, prototyping only).
- `rideengine/card/`: share card generator (`make_card.py`, prototype-quality) and `prepare.py`.
- `rideengine/__main__.py`: CLI (`python -m rideengine import|rides|show|trends|card`).
- `tests/`: `test_engine.py` (synthetic, always runs), `test_real_rides.py` (skips unless Neelay's files are in `data/`).

## Rules
- **Never commit personal data.** Ride files, the Apple Health export and anything derived live in `data/` (git-ignored). Tests that need them must skip when absent.
- From the Apple Health export, read **only cycling workouts and the heart rate recorded during them** (that's what Neelay agreed to). Not resting HR, HRV, sleep, other workouts.
- **Strava is not a data source.** Its API terms bar AI use and showing a user's data to others.
- Prefer device totals (barometric climbing, moving time, wearable calories) over values derived from GPS. Record where every value came from.
- **Simulated power must always be labelled** (SIM) and never feed real totals (calories, load).
- Calories: the wearable wins (Neelay's call), then energy from measured power, then the head unit.
- Python 3.11+, standard library only for the engine (keeps it portable to a backend). pytest for tests.

## Commands
```
python -m pytest -q
python -m rideengine import data/*.fit data/*.gpx --apple data/export.zip --since 2025-01-01
python -m rideengine rides
python -m rideengine show <ride_id>
python -m rideengine trends
python -m rideengine card <ride_id> --config examples/card_durham_forest.json --power
```

## Verified numbers (for sanity checks)
- Durham Forest, 3 Oct 2026 (Garmin FIT + Apple Watch): 68.7 km, 1,139 m, 3:55 moving, avg HR ~144, max 173, 1,973 kcal (Apple active).
- Scugog loop, 19 Oct 2026 (Garmin GPX + Apple Watch): 104.5 km, 633 m (from Garmin track), 23.8 km/h, avg HR 142, max 170, 2,463 kcal.

## Next steps
1. iPhone app prototype (SwiftUI + HealthKit): permission, background delivery of new cycling workouts, history backfill, send to the engine.
2. Replace the JSON store with SQLite, then a hosted backend.
3. Garmin → Apple Health route test (Neelay to try); otherwise an aggregator for Garmin.
4. KICKR power: pair to Garmin (power in the FIT) or Wahoo cloud API; power insights + indoor card.
5. Automatic story for the card: places from stops/towns, headline, map fitted to route shape.

## Linked work in claude.ai (Project "Cycling app")
- Share card canvas: https://claude.ai/artifact/6vEqXrfwo3ozkCh8byzDin
- Ride Trends dashboard: https://claude.ai/artifact/Tu5CgKUFQ84t6EsheDeLey

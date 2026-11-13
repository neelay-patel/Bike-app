# Bike-app

A cycling app that merges every device's data into one ride, tells the ride's story, and turns
your history into real insight: ride faster, ride further, more power, climb faster.

This repo currently holds the **ride engine**: importers, the merge, analysis, and the share card
generator. The iPhone app comes next. Background and decisions: `CLAUDE.md` and `docs/`.

## Setup
Python 3.11+ (standard library only), plus `pytest` for tests.

```
git clone https://github.com/neelay-patel/Bike-app.git
cd Bike-app
python -m pytest -q
```

## Your data (stays on your machine)
Put files in `data/`, which git ignores:
- Garmin rides: in Garmin Connect, open an activity → ⚙ → **Export Original** (a .zip with the .FIT inside). Unzip into `data/`.
- Apple Watch: Health app → your profile picture → **Export All Health Data**. Copy `export.zip` into `data/`. Only cycling workouts and the heart rate recorded during them are read.

Then:
```
python -m rideengine import data/*.fit --apple data/export.zip --since 2025-01-01
python -m rideengine rides            # one line per merged ride
python -m rideengine show <ride_id>   # totals, where each value came from, stops, climbs
python -m rideengine trends           # efficiency, repeated climbs, fitness/fatigue
python -m rideengine card <ride_id> --config examples/card_durham_forest.json --power
```

The real-ride tests (`tests/test_real_rides.py`) run when `data/durham_2026-10-03.fit`,
`data/scugog_2026-10-19.gpx` and `data/export.zip` are present, and skip otherwise.

## Working with Claude Code
Open the folder in Claude Code. It reads `CLAUDE.md` automatically, which carries the decisions
and next steps from the planning sessions in claude.ai.

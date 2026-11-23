# Data sources plan

## Neelay's setup
- Garmin (bike computer/watch) records route, elevation, speed and climbing. Exported as .FIT from Garmin Connect.
- Apple Watch: he starts a Cycling workout on every ride, so heart rate is recorded every few seconds.
- Today both devices push to Strava. Strava keeps one recording per ride; it does not merge fields. Garmin does not currently sync into Apple Health (test planned: turn it on, see whether the route arrives).
- No power meter on the bike. A Wahoo KICKR (smart trainer with built-in power) is arriving soon, for indoor rides.

## Which source wins, per data point
General rule: measured beats estimated, and a dedicated sensor beats a wrist. Calories are the exception, decided by Neelay: the wearable wins.
Implemented in `rideengine/sources.py`.

| Data point | First choice | Fallback |
|---|---|---|
| Route, distance, speed | Garmin | Apple Watch GPS |
| Elevation, climbing | Garmin (barometric) | Watch |
| Heart rate | Apple Watch (any wearable for other riders) | Garmin wrist HR |
| Power, cadence | KICKR / power meter | none. Simulated power is for prototyping only and always labelled SIM |
| Calories | Apple Watch (any wearable for other riders) | Energy from power (kJ ≈ kcal), then the head unit's estimate |
| Temperature | Garmin | none |

## Approach
- One internal ride format (`rideengine/model.py`); every source converts into it.
- Recordings that overlap in time are the same ride (`merge.group`). The bike computer's timeline is the base; wearable heart rate and calories are merged onto it by timestamp (`merge.merge`). Every value records which source it came from (`Ride.provenance`).
- **The ride runs from the first device's riding to the last's** (Neelay, 23 Nov 2026: Watch started while choosing a Zwift course, spinning the warm-up). Where another device was riding right up to the base recording's start (or on after it stopped) with no stop over 2 minutes, its samples carry that stretch (`Ride.added`). Riding means pedalling (power or cadence) or 30 s at 9 km/h or more, so fiddling with a head unit, walking the bike or waiting at the car isn't added; the drive there is cut as before (`clean.py`). At every moment each channel comes from the best source recording it (`fill:<channel>:<source>` in the provenance when the next best filled in); a total from the source that wins it, plus the next best's share for the stretches it didn't record (`extra:<total>`): distance, moving and elapsed time, climbing outdoors only (indoors only the game's climbing counts), energy from power for calories. A total from a device that recorded it all (the Watch's calories) stays as it is. No device names in the merge: `sources.py` ranks them, so it holds for any rider's devices. A ride's id is its start, so it moves when an earlier recording joins; how the ride felt, which session it counts as and the coach's story move with it (`service._move_ride_refs`). A heart rate of 0 is no reading (Zwift via Garmin writes zeros).
- Order of work: build the engine and insights on exported files now; hook up live sources (iPhone app, Wahoo API) as feeders into the same engine.

## Merge test: done (12 Nov 2026)
- The watch logs heart rate about every 5 seconds during Cycling workouts.
- Each ride appears in the Health export as a Cycling workout with its own summary (avg/max heart rate, active calories, distance) and its own GPS route.
- Durham Forest, 3 Oct: average heart rate 144, max 173 at km 4 (opening climb); 1,973 active kcal (Apple). The watch workout started 17 minutes before the Garmin one; that time isn't riding up to the Garmin's start (a stop of more than 2 minutes before it), so the ride is the Garmin's window.
- Scugog loop, 19 Oct: average 142, max 170 at km 66 (the climbs after the Cannington lunch); 2,463 active kcal (Apple).
- Practical notes: the full export is several GB unzipped, so stream it and keep only cycling workouts and the heart rate inside them. Times in the export carry the offset at export time (EST), not the ride's (EDT), so parse them with their offset.

## Not riding: left out of the ride (13 Nov 2026)
- A bike computer left recording in a car shows up as a long stretch above ~65 km/h. `rideengine/clean.py`
  cuts it from the stop before (loading the bike) to the stop after, or to the end. Totals that covered the
  whole recording are worked out again: distance and top speed from the route, climbing as the device's
  barometric total scaled to the part kept, head-unit calories by the share of moving time kept.
  Wearable calories stay as recorded. The ride lists what was left out (`Ride.excluded`), and the app shows it.
- On Neelay's 97 Garmin rides since 2025 this caught two: 30 Jul 2026 (41.7 km in a car at up to 115 km/h;
  the ride is 105.7 km, not 146.9) and 11 May 2025 (38.5 km at up to 117 km/h). Nothing else was touched.

## False starts and empty recordings: hidden, not deleted (13 Nov 2026)
- Empty: under 0.1 km or a minute of riding. False start: under 3 km and 15 min moving, within 90 min
  of a real ride (the computer started, stopped, restarted). A short ride on its own stays visible.
- They stay stored. Lists and trends leave them out (`rideengine/clean.py: visible()`); the API's
  `/v1/rides?include_hidden=true` and `backend rides --all` show them, and the app has a toggle.
- On Neelay's 97 Garmin rides: 19 hidden (13 empty, 6 false starts), 78 shown; smallest shown 5.2 km.

## Power
- Outdoor cards have a vertical power strip down the right side of the map, showing average and max watts. It is hidden when a ride has no power data.
- Until real data exists, power is simulated from speed and gradient (85 kg rider plus bike, gravel tyres, upright position) and tagged SIM.
- KICKR: it broadcasts power over Bluetooth/ANT+. Pairing it to the Garmin puts power straight into the .FIT file. The Wahoo app or Zwift save their own files, and Wahoo's cloud API is a later automated option.
- Indoor rides have power but no route. Idea: make the power trace itself the "map", drawn as a skyline.

## Status of each source (Nov 2026)
- Garmin Connect Developer Program: reopened Oct 2026 with Personal (own data, pull), Starter (free, ~1,000 users, push, no history) and Enterprise (paid, history) tiers. Personal-key connector built (13 Nov 2026); Starter next. See `docs/connectors.md`.
- Apple Health: needs an iPhone app with the user's permission; background delivery of new workouts. The most realistic automated route for heart rate and calories.
- Wahoo: open cloud API with app approval.
- Hammerhead, Whoop, Oura, Fitbit (Google Health API): see `docs/connectors.md`.
- Strava: avoid as a source. Its terms bar AI use and showing a user's data to others.

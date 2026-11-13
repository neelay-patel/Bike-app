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
- Order of work: build the engine and insights on exported files now; hook up live sources (iPhone app, Wahoo API) as feeders into the same engine.

## Merge test: done (12 Nov 2026)
- The watch logs heart rate about every 5 seconds during Cycling workouts.
- Each ride appears in the Health export as a Cycling workout with its own summary (avg/max heart rate, active calories, distance) and its own GPS route.
- Durham Forest, 3 Oct: average heart rate 144, max 173 at km 4 (opening climb); 1,973 active kcal (Apple). The watch workout started 17 minutes before the Garmin one; the merge keeps only the Garmin window.
- Scugog loop, 19 Oct: average 142, max 170 at km 66 (the climbs after the Cannington lunch); 2,463 active kcal (Apple).
- Practical notes: the full export is several GB unzipped, so stream it and keep only cycling workouts and the heart rate inside them. Times in the export carry the offset at export time (EST), not the ride's (EDT), so parse them with their offset.

## Power
- Outdoor cards have a vertical power strip down the right side of the map, showing average and max watts. It is hidden when a ride has no power data.
- Until real data exists, power is simulated from speed and gradient (85 kg rider plus bike, gravel tyres, upright position) and tagged SIM.
- KICKR: it broadcasts power over Bluetooth/ANT+. Pairing it to the Garmin puts power straight into the .FIT file. The Wahoo app or Zwift save their own files, and Wahoo's cloud API is a later automated option.
- Indoor rides have power but no route. Idea: make the power trace itself the "map", drawn as a skyline.

## Status of each source (Nov 2026)
- Garmin Connect Developer Program: new API applications paused, no reopening date. Manual .FIT export for now. Fallback: an aggregator partnered with Garmin (e.g. Terra), paid per user.
- Apple Health: needs an iPhone app with the user's permission; background delivery of new workouts. The most realistic automated route for heart rate and calories.
- Wahoo: open cloud API with app approval.
- Strava: avoid as a source. Its terms bar AI use and showing a user's data to others.

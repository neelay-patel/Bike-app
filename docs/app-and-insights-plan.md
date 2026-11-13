# App and insights plan

Decided 12 Nov 2026: get the data right first (sources, merge, storage), with insights and dashboards developed in parallel. iPhone first.

## What riders want, in order (Neelay)
1. Ride faster
2. Ride further

Two things feed those: more power, and climbing faster. Every insight screen should map to one of these.

## Part 1: data that arrives on its own
Goal: connect accounts once, then every ride shows up merged with no exporting. This is what Strava does as a hub today, except we merge field by field instead of keeping one recording.

- **iPhone app on Apple Health**: one permission screen, then new workouts arrive in the background (HealthKit background delivery). Covers the Apple Watch fully: route, heart rate, calories. Also picks up anything other apps write into Health.
- **Garmin**: official API paused for new applications. Test whether Garmin Connect → Apple Health sharing carries the route (reports say it doesn't). Fallback: an aggregator partnered with Garmin (e.g. Terra), paid per user.
- **Wahoo**: cloud API for KICKR sessions (power). Or pair the KICKR to the Garmin so power lands in the .FIT.
- **Merge engine (the core, built in this repo)**: match recordings by time overlap, apply per-field source rules, store one ride with provenance.
- **Backfill**: on first connection, pull history so trends work on day one. Neelay's export holds 1,100 cycling workouts back to 2015 (most useful: 2024 onward; detailed heart rate from mid-2025).

## Part 2: insights
- **This ride**: automatic climb detection compared with previous attempts; heart-rate drift (fade); a fuelling check; the share card.
- **Faster**: speed and heart rate on repeated routes; efficiency = metres per heartbeat on flat steady sections (works without a power meter).
- **Further**: distance by month and year, longest ride, rides of 50 km or more.
- **Power** (once data exists): best 5 s, 1 min, 5 min, 20 min.
- **Climbing**: times on repeated climbs.
- **Behind it all**: fitness, fatigue and form from training load (heart rate now, power later).
- **Looking forward**: a goal-based plan that adapts to what was actually ridden and to recovery; an AI coach that answers questions from the rider's data.

## First trends dashboard (12 Nov 2026)
https://claude.ai/artifact/Tu5CgKUFQ84t6EsheDeLey, built from the Apple Health export.
- Faster: 35 km home loop (Toronto), 2026: first three rides 23.1 km/h at 111 bpm; last three 25.8 km/h at 135 bpm. Efficiency flat (~3.1 m per beat): the speed came from effort, not fitness.
- Further: outdoor km 1,313 (2024), 1,967 (2025), 1,977 (2026 to 3 Nov). Longest ride 87, 97, 104 km.
- Climbing: Richmond Park climb (2.9 km, Kingston Gate side) from 8:50 (June 2024) to 6:30 (Aug 2024).
- Fitness peaked 19 Oct 2026 (the Scugog ride).

## Known gaps and lessons
- Rides recorded only on the Garmin are missing from Apple Health.
- Detailed (5-second) heart rate only from mid-2025; earlier rides logged it every ~14 minutes.
- Apple's climbing differs from Garmin's (Scugog: 734 m vs 633 m). Source rules decide.
- Climb detection needs a minimum gradient (~1%), a maximum length (6 km), and trimming of flat road before the climb.
- Training-load max heart rate is estimated from rides (169 bpm). A field test would be better.

## Next build steps
1. iPhone app prototype: Apple Health permission, background delivery of new cycling workouts, history backfill, upload into the engine.
2. Move the store from JSON files to a database (SQLite locally, then a hosted one) and run the engine as a backend service.
3. Garmin → Apple Health route test; decide on the aggregator.
4. KICKR: pair to the Garmin or connect Wahoo's API; add power insights and the indoor card.

# Roadmap: after the connectors

Agreed 13 Nov 2026. Connectors stay first (docs/connectors.md). Next come three buckets of work, built
in this order because each one feeds the next:

1. **Insight, tallies and personal bests** (the ego bucket): the numbers everything else uses.
2. **Fun**: avatar, rider card, badges, the season binder. Built on bucket 1's numbers.
3. **Training and coaching**: goals, plans, tracking. Needs heart rate, power and the terms read.

What riders want stays the yardstick (docs/app-and-insights-plan.md): **ride faster, ride further**,
fed by **more power** and **climbing faster**.

## Rules that apply to all three
- **Rule-based text until the terms are read.** Garmin data is marked "not cleared for AI" in
  `SOURCE_POLICY`, so headlines, notes and coaching text are written by our own rules, not an AI model.
  An AI coach comes once the Garmin and Wahoo terms allow it, and only on rides `allowed(..., "ai")`.
- **Honest numbers.** Every tally counts only visible rides (no false starts, no car stretches). Simulated
  power never counts toward a record or a tally.
- **Sharing follows `SOURCE_POLICY["share"]`.** Anything shown to other people (cards, trumps with
  friends) checks the sources first.
- **Training guidance, not medical advice.**

## Bucket 1: insight, tallies, personal bests (started 13 Nov 2026)
Engine: `rideengine/analysis/records.py`. Backend: `GET /v1/you`, and `notes` on every ride.
App: the **You** tab, and each ride's notes on its detail screen.

- [x] **Tallies**: all time, this year, last year, this month: km, hours, climbing, rides.
  Climbing counted in Everests (8,849 m). Distance put in real terms (city pairs as the crow flies).
- [x] **Streaks**: weeks in a row with a ride, longest and current.
- [x] **Biggest month.**
- [x] **Personal bests**: longest ride, most climbing, longest in the saddle, fastest average (rides of
  30 km or more, outdoors), highest average power (measured power only).
- [x] **What's notable**, per ride: ranks against all earlier rides and against the year ("your 2nd
  longest of 2026", "most climbing since June", "your longest ride yet"); milestones crossed ("took
  2026 past 2,000 km", "your 100th ride"); streaks ("5 weeks in a row").
- [x] **Ride card headline** from the top note, when no headline is given (`python -m backend card`).
- [x] **Repeated routes** (`rideengine/analysis/repeats.py`): rides covering mostly the same ground are one
  route; the most-ridden one from home is the home loop. Laps ranked on average speed ("your 2nd fastest home loop").
  Named after the most notable place on them ("Home loop via East Bayfront"). Next: let the rider rename them.
- [x] **Climb bests**: each repeated climb gets fixed start and finish points and every ride over it is timed
  between them, like a segment; named bottom to top from GeoNames ("Regent Park to Leaside"). Next: renaming, and
  heart rate on the climb once Apple Health is connected.
- [ ] **Towns collected**: every town a route passes, counted over a year and all time.
- [ ] **Faster, explained**: efficiency (metres per heartbeat) and heart-rate drift; needs heart rate,
  so it waits on Apple Health on the real phone.
- [ ] **Fitness, fatigue, form** over time (heart rate now, power once the KICKR is in).
- [ ] **Power bests** (5 s, 1 min, 5 min, 20 min) once the KICKR is in.

- [x] **Insights pipeline** (14 Nov 2026, `docs/insights.md`): per-ride features stored once, new rides matched to
  known routes and climbs, discovery and notes in a background refresh, stable ids, renaming, the rider's time
  zone. Rides in any order give the same answers as the batch. Left before other riders: job queue + Postgres,
  rides list from stored rows, push notifications, thresholds on other terrain, privacy zones, GeoNames worldwide.

## Bucket 2: fun
Our own drawing style, not a copy of any existing card game's art.
- [ ] **Avatar builder**: drawn in code from parts (helmet or cap, kit colours, hair and beard, glasses,
  bike type). Consistent, free per image, fits look D.
- [ ] **Rider card**: the avatar plus ratings out of 99 from the rider's own data (Distance, Climbing,
  Speed, Consistency, Endurance) that move as they improve. The ride cards are the set; this is the cover.
- [ ] **Holo ride cards** for personal bests (bucket 1 already knows which rides they are).
- [ ] **Badges**, earned, never handed out: first 100 km, an Everest of climbing in a month, every month
  of a year ridden, a 10-week streak.
- [ ] **Season binder**: the year's ride cards in order, gaps where weeks were missed.
- [ ] **Later, social**: trumps with friends' rider cards. Waits on the providers' sharing terms.

## Bucket 3: training and coaching
- [ ] **Goals**: a distance (a first 150 km day), a date (a gran fondo), a climb time to beat.
- [ ] **Plans that adapt** to what was ridden and how tired the rider is. Needs heart rate (Apple Health
  on the real phone) and power (KICKR).
- [ ] **Send workouts to the devices**: Wahoo's API to the KICKR; Garmin's Training API (Starter tier).
  Plan, ride, analyse, adjust.
- [ ] **AI coach** once the terms allow it, on allowed rides only.

## What only Neelay can unblock
- Run the app on the iPhone and connect Apple Health (heart rate for efficiency, drift, fitness).
- Ride the KICKR (week of 16 Nov 2026) for power.
- Read or skim the Garmin and Wahoo API terms (AI and sharing), so `SOURCE_POLICY` can be filled in.

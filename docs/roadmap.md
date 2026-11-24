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
- [x] **Recovery** (14 Nov 2026, `docs/recovery.md`): heart-rate recovery after rides, HRV and resting heart rate
  against the rider's usual range, VO2 max trend, from Apple Health. Needs checking on the real phone.
- [ ] **Fitness, fatigue, form** over time (heart rate now, power once the KICKR is in).
- [ ] **Power bests** (5 s, 1 min, 5 min, 20 min) once the KICKR is in.

- [x] **Insights pipeline** (14 Nov 2026, `docs/insights.md`): per-ride features stored once, new rides matched to
  known routes and climbs, discovery and notes in a background refresh, stable ids, renaming, the rider's time
  zone. Rides in any order give the same answers as the batch. Left before other riders: job queue + Postgres,
  rides list from stored rows, push notifications, thresholds on other terrain, privacy zones, GeoNames worldwide.

## Bucket 2: fun (built 14 Nov 2026, `docs/fun.md`)
Our own drawing style, not a copy of any existing card game's art.
- [x] **Avatar builder**: drawn in code from parts (skin, face, hair and colour, beard, glasses, helmet or cap,
  kit colours and pattern). Same drawing in the builder, on the rider card, and behind every ride card's map.
- [x] **Rider card**: avatar, ratings out of 99 (Distance, Climbing, Speed, Endurance, Consistency) from the
  last 12 months, overall, rider type (Rouleur, Climber, Flier, Diesel, Metronome), badges earned.
- [x] **Holo ride cards** for all-time bests and firsts (iridescent header, "★ PB").
- [x] **Badges** (24), earned on a ride, never handed out; the rest show how close you are.
- [x] **Season binder**: a tab with the year's cards in order, holo cards, empty slots for missed weeks.
- [ ] The bike choice isn't drawn yet (stored for a later full-body or bike-in-frame drawing).
- [ ] Badge artwork (now icons); share the rider card; binder page-turn animation.
- [ ] **Later, social**: trumps with friends' rider cards. Waits on the providers' sharing terms.

## Housekeeping
- [x] **Delete a ride** (14 Nov 2026): long-press in Rides, or ⋯ on the ride screen. Every recording merged into it
  and its original file go; it's remembered as deleted (`deleted_recordings`) so a Garmin sync or Health upload doesn't
  bring it back. `DELETE /v1/rides/{id}`, `python -m backend delete-ride --user N <id>`. No undo yet.

## Bucket 3: training and coaching (planned 15 Nov 2026, `docs/coaching.md`)
- [ ] **Data first**: every source automatically (Wahoo this week; Zwift via Garmin Connect; Garmin business
  tier; history on day one; sync health; gap spotting). Personal-use AI setting for Neelay's own setup.
- [ ] **Goals**: stronger, further, faster, event; asked in the rider's words, revealed from their own data.
  Design the flow as a mock-up first.
- [ ] **The engine**: power curve and best efforts from normal rides, heart rate against speed and power,
  drift, seasons, plan rules, recovery-driven adjustment; tracking both "did you do it" and "is it working".
- [ ] **Plans that adapt daily**; KICKR workouts sent through Wahoo; strength and mobility reminders only.
- [ ] **AI coach** on top of the engine (explains, reviews, adjusts within limits).
- [ ] Later: Garmin workouts outdoors, events.

## What only Neelay can unblock
- ~~Run the app on the iPhone and connect Apple Health~~ (done 14 Nov 2026).
- ~~Link Zwift to Garmin Connect when Zwift starts~~ (done; Zwift arrives via Garmin, checked 19 Nov 2026).
- ~~Ride the KICKR (week of 16 Nov 2026) for power~~ (done 17 Nov 2026; power arrives via the Watch).
- Read or skim the Garmin and Wahoo API terms (AI and sharing), so `SOURCE_POLICY` can be filled in.


## Order from 24 Nov 2026 (Neelay)
1. Heart rate and zone 2 in Train and the rides. 2. Change the plan by talking. 3. A coach reviews
`docs/training-science.md`. 4. Garmin integration (workouts to the Edge, Courses API). 5. Other riders and TestFlight.
6. The fun engagement model and prizes. Later: routes, more sources. The list below is the earlier detail.

## Next steps in detail (21 Nov 2026)
1. **Reinstall the app by 30 Nov 2026** (free Personal Team, 7-day profile; renewed 23 Nov). Neelay is considering
   the paid Apple Developer Program (individual): one-year builds, TestFlight, then Sign in with Apple in place of
   the dev token.
2. **Live with Kova, the cleaner Efforts and You** (18-20 Nov) and adjust from real use: is the full-size card too
   much on a day with nothing new; does the collection make history feel close at hand; do indoor cards (shorter
   than 9:16) share well, or should they be padded to 9:16 for Instagram.
3. **A fun engagement model**, then bring prizes back into it (`PrizeShelf` in `YouView.swift` and the server's
   milestones are kept). Badges, holo cards and the rider card are the pieces to build on. Idea from Neelay's son:
   "meta" (most effective tactic available) for the one thing to work on next.
4. **Coaching refinement, AI assisted: the Train tab** (Neelay put it on the list 21 Nov 2026; build plan in
   `docs/train-tab.md`, background in `docs/coaching.md` sections 6-7).
   The engine calculates (load, zones, plan rules, progress); an AI coach explains, reviews the week and refines the
   plan within the engine's limits, on Neelay's own data under the personal-use setting. Order: match efforts to the
   plan, the AI layer (retelling efforts from the engine's numbers; needs an Anthropic API key in the backend's
   environment), re-planning, conversation. His goal: keep up with the fast group, ready by 1 May 2027.
5. **Routes, next:** Garmin Courses API for one-tap sending (with the Starter tier); scenery scoring; starts at a café
   or car park rather than a town centre; move a one-way's destination in tuning; people to ride with
   (`docs/routes.md`).
6. **Other riders and TestFlight** (planned in `docs/hosting.md`, 18 Nov 2026): Apple Developer Program, slim the store
   (done 20 Nov: compressed storage and a brief per ride; was 1.7 s for `GET /v1/rides`, the app's blank first
   second or two), delete account, Sign in with Apple, host the backend (also ends the home Wi-Fi limit), Garmin
   Starter tier (OAuth + push webhook, apply early), privacy policy, a trademark check on Kova, TestFlight.
7. **More sources:** Wahoo cloud, Whoop, Oura, Google Health; Hammerhead once access is agreed. Read each provider's
   terms in full and fill in `SOURCE_POLICY`.

# Coaching and training: the product plan

Agreed with Neelay 15 Nov 2026. Nothing here is built yet; this is what we're building toward and why.

**The promise:** one coach that sees every device you ride with, knows how recovered you are, works toward a
goal you actually care about, explains its reasoning, and shows honestly whether it's working.

What sets it apart from TrainerRoad, Garmin Coach, Wahoo SYSTM or TrainingPeaks: they plan from one source
and mostly count what you did. We merge every device, read recovery, and judge progress from ordinary riding.

## 1. All the data, arriving on its own
The coach is only as good as the data, so getting every source **automatically** comes first. No exports,
no uploads: connect once, everything arrives. See `docs/connectors.md` (data strategy).
- Go to where the data is recorded (the device makers), not to aggregators. **Strava records nothing
  itself** apart from its phone app, so it holds nothing we can't get first-hand; it isn't a source.
- Two hubs collect most things without extra work: **Apple Health** on the iPhone (many apps write to it)
  and **Garmin Connect** (Zwift and many apps sync to it).
- **Personal use:** for Neelay's own account, every source counts as cleared for AI, for him alone (he
  takes care of the providers' approvals). To build: a setting for a personal deployment. The product
  default for other riders stays strict (`SOURCE_POLICY`) until each provider's terms are read. Sharing
  with other people is unchanged.

## 2. Goals: where the product wins or loses
Four top-level objectives: **stronger, further, faster, event**. The hard part, and the part to get right,
is finding *the* goal in a way that excites the rider and points at what to work on.
- **Ask in the rider's words, never metrics.** Aspirations people actually say: "keep up on the group ride",
  "ride all day", "own the climbs", "finish my first gran fondo". Nobody wants "raise FTP 8%".
- **Reveal what it means, from their own data.** For Neelay ("faster, to keep up with faster riders"):
  solo he holds ~26 km/h on the home loop; fast groups ride 30–32. In the draft that's roughly 10–15% more
  power held for an hour, plus answering surges of 30 s – 2 min. That names the two things to train:
  **sustainable power** and **repeatable surges**.
- **Behind the scenes, measurable markers** the rider never has to think about (for Neelay: speed against
  heart rate on the flat, home loop and climb times, and once Zwift/KICKR power is in, best 5, 20 and
  60-minute power and 30 s – 2 min efforts).
- Every goal gets a target and a horizon (a date, or a season).
- **Mock-up approved 15 Nov 2026:** https://claude.ai/artifact/JCQyTJQ5XDZi9gvpCkXXcB (six phone screens: pick an
  objective → what it looks like for you, quoting your own bests → a few taps about the target (e.g. the group's
  pace, length, terrain, when) → **the reveal** (the gap, from your rides, and the 2–3 things to build) → your goal
  with the markers we'll watch and your season → first week). Only the Faster path is drawn; the others branch the
  same way. Placeholders in it (targets, the 10% drafting estimate, the sessions) are for the engine to work out.

## 3. The plan, and tracking against it
- **Adapts daily:** a weekly target and suggested sessions that reshuffle when a day is missed, an extra
  ride happens, or recovery (HRV, resting heart rate, heart-rate recovery after rides) says ease off.
- **Indoor and outdoor:** indoor sessions are sent to the KICKR (ERG mode) via Wahoo; outdoor guidance later
  to the Garmin (Training API).
- **Seasons from each rider's own history**, no hemisphere assumptions. Neelay is now in his indoor months:
  winter is a build phase on Zwift and the KICKR, outdoor goals return in spring.
- **Real life:** busy weeks, travel and illness bend the plan instead of breaking it.
- **Safety:** a short health check before the first plan; back off when ill, injured or poorly recovered.
  Always "training guidance from your own data, not medical advice".

## 4. Is it working? Read it from riding, not tests
Two kinds of tracking:
- **Did you do it:** sessions done, missed, swapped; time against the weekly target.
- **Is it working:** judged from ordinary riding (tests are optional, never required):
  - best efforts found in normal rides: power curve (5 s to 60 min), estimated threshold power from it;
  - heart rate at the same speed or power, and how much it drifts late in long rides;
  - repeated climbs and the home loop;
  - recovery: HRV, resting heart rate, heart-rate drop after rides.
  Zwift and the KICKR make winter the cleanest data of the year (steady power, no wind or traffic).
- **Playback is separate from goal setting.** One idea: the rider card's ratings as the progress meter
  ("Speed 67 → 75"), so the card they collect shows the gains.

## 5. Off the bike
Strength and mobility **reminders only**, with an optional "done" tick. No exercise content, and no
widening of what we read from Apple Health, at this stage.

## 6. The AI coach
- **The AI explains; the engine calculates.** Load, fitness, zones, plan rules and progress live in our
  engine. The AI reads those facts, answers "why?", runs the weekly review, and adjusts the plan only
  within limits the engine sets. The plan works without the AI.
- Uses only data cleared for AI (all of Neelay's own, under the personal-use setting). Riders agree
  explicitly before their data goes to an AI service.

### The coach, mocked up (approved 15 Nov 2026, same canvas, second row)
- **Set the goal by talking** (the main way in; tiles become shortcuts): the rider says it in their words, the coach
  shows what it understood as tags (FASTER · KEEP UP WITH A GROUP · SURGES UPHILL), asks only what's missing, then
  leads into the reveal. Voice as well as text.
- **Weekly review:** plan against done, a coach's note tying the week to the goal, what moved, next week.
- **A plan change you can push back on:** today's session changed with its reason (recovery), the rider negotiates
  ("travelling Tue–Thu"), the coach proposes a reshuffled week to accept or decline; quick context buttons (ill,
  something hurts, short on time, feeling great).

## Built so far (15 Nov 2026)
**The goals engine** (`rideengine/analysis/goals.py`, API under `/v1/goals/…`), no app screens yet:
- `options`: the four objectives and their aspirations, quoting the rider's own bests ("Your home loop best:
  26.4 km/h", "My first 120 km ride").
- `seasons`: each month outdoor / indoor / mixed from two years of history; now, and when outdoor riding starts
  (Neelay: outdoors May–September, indoor now, outdoor again from 1 May 2027).
- `reveal`: the gap and what to build, every quoted figure returned with it. Solo pace = median of the last 12
  flat-ish outdoor rides of 25 km+ (Neelay 25.8 km/h); drafting estimate from flat-road physics with the group taking
  ~30% off the aero power (30 km/h in the draft ≈ 12% more power than solo 25.8). Labelled an estimate.
- `markers`: the matching rider-card rating (weekly history), home loop speed **scaled to the same heart rate**
  (lap speed × ((ref − resting) / (lap HR − resting))^⅓, ref = recent median lap HR; Neelay 25.6 km/h at 136 bpm,
  up from 25.1 in September), the main climb's best, longest recent ride, and power markers (best 5 s, 1, 5, 20 min
  from measured power; pending until KICKR/Zwift rides arrive). Targets are proposals (+8 rating, +5% speed,
  −5% climb time, +8% power).
- Goals stored per rider, one active, older kept as history; `ready_by` defaults to the start of the outdoor season.
- Ride features v5 carry each ride's power curve (measured power only).

## Order of work
1. **Data first:** Wahoo (KICKR power) this week; Zwift linked to Garmin Connect when Neelay starts; Garmin
   business tier for other riders; history on day one; sync health and gap spotting.
2. **Goal flow design** (mock-up), then build it.
3. **The engine:** power curve and best efforts, heart rate against speed and power, drift, seasons, plan rules,
   recovery-driven adjustment, both kinds of tracking.
4. **KICKR workouts** sent through Wahoo.
5. **AI coach** on top: chat and a weekly review grounded in the engine.
6. Later: Garmin workouts for outdoors, events.

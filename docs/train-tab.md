# The Train tab: build plan

Agreed with Neelay 21 Nov 2026. The Plan tab and the coach become one tab, **Train** (a working name; Neelay wants
to give it more Kova character later). Mock-up (8 phone screens): https://claude.ai/artifact/PqSSKTSmCHpzt5V63k8io2.
Background and the engine/AI split: `docs/coaching.md` (sections 6 and 7). This doc is the order of work.

## What it has to be (Neelay's words and decisions)
- **The coach speaks up on its own.** It knows about every new ride, acknowledges it, reads it, files it against the
  plan, praises what deserves it and adjusts the plan. A morning brief; a Sunday review. Aware of past and present.
- **Visual about the next session, a sentence about the one after.** The calendar is there to look ahead, not the
  main view. **Rest days are sessions**, shown with the same weight.
- **Easy and simple.** One thing per screen; capability never at the cost of clarity.
- **Words a rider reads right first time:** every card labels what's a fact (What you did), how a ride was filed
  (Counted as), what it means for the goal (What it means) and the next step (What's next). The guide, glossary
  and banned words: `docs/train-words.md`; the AI coach writes in the same format.
- **Grounded in the best training knowledge**, as a credential we can point to (section "Method", below).
- Goal: keep up with the fast group by 1 May 2027. Words: "indoor trainer", never "gym bike".

## How the screens fit
Train opens on **Today**, which is one of two states: a session day (the session, big; how it should feel; why) or
a rest day (rest, big; why rest matters; on Sundays a card to the week's review). From Today: the calendar icon →
**The plan ahead** (phases to 1 May, four weeks of likely days) → a week → **The week, matched** → a session's
detail; "Tell your coach…" → **Talk**. Notifications open the right screen: after a ride → **After a ride**; rest
day and morning brief → Today; Sunday → **Sunday review**. After a ride its note also sits at the top of Today until
"How did it feel?" is answered, and the ride's screen in Efforts says what it counted as.

**Days:** sessions sit on the rider's usual days as a guide (the calendar), but any ride can fill any session, and
Today always shows the best next session from what's left, recovery and the days remaining.

## The order of work
Each step ends on Neelay's phone and in tests (synthetic always; his own data when `data/` is there).

### 1. Engine: what each ride was, and which session it counts as (built 21 Nov 2026)
- `rideengine/analysis/train.py` (new). **Classify a ride** from `effort.phases()` (blocks, their length and
  intensity against FTP or heart-rate zones): surges, sweet spot, threshold, endurance, easy, group ride (varied
  intensity, Zwift or outdoors), race-like, or mixed. With a confidence.
- **Match the week:** each ride goes to the open session it fits best (by kind, then length), whatever the day;
  a second ride the same day can count too; a ride that fits nothing is extra riding. The rider can move a match.
  Replaces `plan.status()` (same day, 60% of the time).
- Each ride's **contribution**: load, and which goal markers it fed (a new best 20 min, a best minute).
- Stored per ride and recomputed when the plan or the ride changes (like `features`).
- Built: `rideengine/analysis/train.py` (`work` stored in features v10, `classify`, `match_week`), the plan view's
  `counted`, `rides` and `extra` per week and the `open` status (earlier this week, still to do), and
  `PUT`/`DELETE /v1/plan/rides/{ride_id}/counts-as` to move a ride (table `plan_matches`). Contribution (load,
  markers fed) moves to step 2.
- His real week 1 (16-22 Nov, FTP 147 W), as the engine read it: Tue 8 hard efforts of 40 s to 2 min → surges;
  Wed a 6-block ERG workout at ~129 W → sweet spot; Thu 42 minutes at ~151 W → threshold, counted as the group
  ride; Sat 85 min mostly steady with climbs → counted as endurance. (The mock-up had Tue and Sat the other way
  round; the engine is right.) A test checks this when `data/` is present.

### 2. Engine: today's session, rest, adapting, and feedback on every ride (built 21 Nov 2026)
- Built: `rideengine/analysis/today.py` (`plan_today`: today's session, rest or done, why, how it should feel, what's
  next, sessions moved; `greeting`), `rideengine/analysis/feedback.py` (`pointers`: one thing to try; `contribution`:
  load and new bests), features v11 (cadence, the climbs' pushes, heart-rate drift). API: `GET /v1/train/today`,
  `GET /v1/train/week?start=`, `GET /v1/train/rides/{id}` (the ride note: what you did, counted as, what it means,
  what's next, one thing to try). Before the plan's first week, Today says when it starts. Not yet: the change log
  stored over time (moves are worked out fresh each day), and "how did it feel" feeding back (step 5).
- **Each session's own page** (Neelay, 22 Nov 2026: "Surges, 5 × 1 min. Not much to work with"): What's Next lists
  the sessions it names (`next` on `/v1/train/today`), each a tap away from its page (`SessionView.swift`, also from
  Today and the week): why, how it should feel with watts, the shape with a time scale (tap Warm up, Main set or Cool
  down to light it up), then each part with how to ride it (`today.guide`) and every step's targets (watts, heart
  rate for efforts over 2 minutes, cadence from `plan.CADENCE`, effort out of 10), where, and what to bring. No "FTP"
  or "load" on it.
- **One reading of what was ridden** (Neelay, 23 Nov 2026, after the first surges: "I would expect the ride card
  analysis and the Training analysis to be aligned"): `effort.find_sets` finds interval sets in the power (hard
  efforts of about the same length with about the same easy riding between, by contrast with the riding around them,
  no FTP needed; harder with cadence well down is the trainer's climbs, not intervals). The ride's page (phases
  "intervals", its lines), Train's reason (`train.classify`) and planned against ridden (`train.against`: set by
  set, done of planned, watts against the targets the ride was ridden to, and the riding after the sets) all use
  them; the ride card takes the session's name indoors and "5 × 1 min and 5 × 30 s hard, as planned."
- **How a hard session felt moves the watts** (same day): "easy" on a hard session raises the targets 5% above what
  that session's started from (stored with the tap, `ride_feel.ftp_w`); good or hard keeps them there; wrecked eases
  back 5%; never below the estimate, never more than 15% above it (`service._aim`). The estimate itself (what you
  could hold for an hour) is unchanged; the ride note says what changed with the next hard session's watts, and the
  AI coach is told.
- **Feedback that makes a better rider** (Neelay, 21 Nov 2026): after every ride, one constructive thing to try,
  from what the ride contained (cadence, pacing, easy days too hard, fuelling), in `docs/train-words.md`'s format.
  His Saturday Zwift ride, counted as endurance: "Keep easy days easy" (43 of 81 minutes near his limit), then
  "Spin a lighter gear on the climbs" (down to 55 rpm on 3 climbs).
- **Pick today:** from the week's open sessions, the best next one given: what's done, the last few days (no hard
  days back to back; rest after three or four riding days), readiness from `wellness.readiness()` (strained → easy
  or rest), and days left in the week. Rest is a real result with its reason.
- **When a week goes sideways:** a missed key session moves to the next free day; an easy one drops; two misses in a
  row and the coach asks before changing more. Recovery swaps are automatic and said; bigger changes ask first.
- **Limits** the AI can never cross: weekly load within the phase's range, no more than two hard days in a row of
  any kind, an easier week every fourth (kept from `plan.build_plan`).
- A **change log** (what changed, when, why), shown as one line where it matters.
- Each ride's **contribution** (from step 1): load, and which goal markers it fed (a new best 20 min, a best minute).
- API: `GET /v1/train/today`, `GET /v1/train/week?start=`.

### 3. App: the Train tab, with rule-based words (built 21 Nov 2026)
- Built: `ios/RideApp/RideApp/TrainView.swift`. The Train tab replaces Plan: Today (the coach's line; the session
  big with How it should feel and Why, or Rest, or Ride's in), What's next (with sessions moved), the latest ride's
  note in brief, This week, the goal with its numbers; the calendar icon opens the plan ahead (the old Plan screen,
  `PlanView(embedded: true)`). The ride note (What you did, Counted as with Change, What it means, What's next, One
  thing to try) and the week as counted (each session with the ride that counted and why; open ones open their
  detail). Checked in the Simulator against a copy of Neelay's data. Not yet: a ride's screen in Efforts saying what
  it counted as.
- Design pass (21 Nov 2026, Neelay: "optimising and impact"): one dark hero per day with its key numbers in the
  dot-matrix type (session: minutes, the main set, watts; ride's in: km, climbing, best minute, counted as, one
  thing to try, replacing the separate "after your ride" card); the session's shape in the summit's yellow; feel and
  why as one line each; "indoors or out" as a chip with the advice behind it; the week as a seven-day strip; the
  goal's numbers in Doto with an "aim met" badge.
- Replaces the Plan tab. Today (session day and rest day), the "then" line, the goal bar, The plan ahead (reusing
  `MonthCalendar`), The week matched, session detail (reusing `SessionDetail`, `IntervalChart`). Rule-based text
  for now, so it works before any AI, and keeps working without it.
- Efforts: a ride's screen says what it counted as.
- Then Neelay lives with it for a week or two before the AI goes on top.

### 4. The coach speaks up: events and notifications (built 21 Nov 2026)
- Built: `GET /v1/train/inbox` (`service.train_inbox`): messages worked out fresh with stable ids (ride:<id>,
  change:<date>, review:<week>) plus the morning brief as `scheduled` (07:30 local, the phone schedules it itself).
  App: `CoachNotifications.swift` shows new messages as local notifications when Apple Health wakes Kova for a ride,
  on background refresh (`com.neelaypatel.rideapp.coach`) or when it opens (then just marked seen); tapping opens
  the ride's note, the week, or Today; Settings › When the coach speaks up turns each kind off. Ride messages cover
  today and yesterday only (older "best yet" news may no longer be true). Checked in the Simulator (posting and
  tapping); the background wake-up itself can only be seen on the phone. No change log stored yet.
- Backend events: a ride arrives (Garmin poll or Apple Health upload), the morning (07:30 his time), Sunday evening.
  Each makes an **inbox item** (`GET /v1/train/inbox`): kind, title, text, the screen it opens, read or not.
- **Until the paid developer account:** local notifications. The app wakes on Apple Health background delivery
  (already on for workouts) and background refresh, fetches the inbox and posts what's new. Garmin-only rides reach
  the phone the next time it wakes.
- **With the paid account:** push from the server (APNs), so every event arrives at once.
- Settings: after every ride, morning brief, plan changes, Sunday review (all on by default).

### 5. The AI coach: words on top of the engine (first part built 21 Nov 2026)
- Built: `backend/coach.py`. For each ride the engine's facts packet (no GPS, place names or recovery numbers;
  nothing that changes day to day) goes to Claude Opus 5.5 (effort low, structured JSON, server-side refusal
  fallback); it writes a headline and the WHAT IT MEANS story; the number check throws out any reply with a number
  not in the facts; results are saved by input hash (`coach_texts`) and written in the background, so the screen
  shows the engine's words first; every call is logged with its cost (`coach_usage`). Policy gate:
  `python -m backend ai --user 1 on|off|status` (on for Neelay since 21 Nov). Key: `~/.config/kova/anthropic_api_key`.
  "How did it feel?" (`PUT /v1/train/rides/{id}/feel`, table `ride_feel`): wrecked means easy or rest next,
  something hurting means rest (and see a professional if it persists); the coach's story takes it in.
  Measured on his rides: about 0.7-0.9 cents and 3 seconds a story. Not yet: the morning brief and Sunday review
  in the coach's words.
- `backend/coach.py` (new): the engine builds a **facts packet** (the ride's class and match, its numbers, recent
  weeks, the goal and markers, readiness as a word, never HRV values or GPS); the model writes in a fixed format; a
  **number check** rejects any figure not in the packet; results saved by input hash; a cost log; the rule-based
  text is the fallback whenever the AI is off, slow or rejected.
- **Policy:** a personal-use setting marks all of Neelay's sources as cleared for AI, for him only
  (`docs/coaching.md` section 1). Other riders stay on `SOURCE_POLICY` and agree explicitly first.
- Order: the ride note with "How did it feel?" (fed back to the engine: Wrecked after an easy day means ease off),
  the morning brief line, the Sunday review.
- Needs: an Anthropic API key in the backend's environment (Neelay makes it; never in the repo), the `anthropic`
  package. Model: Claude Opus 5.5 to start; a cheaper model for ride notes is Neelay's call once we see the cost.

### 6. Talk: change the plan in your own words
- Words → structured constraints (away Tue-Thu, indoor trainer without power, short on time, ill, something hurts)
  through a fixed schema; the engine re-plans within its limits; the AI explains; the rider accepts or declines.
  Quick buttons for the common ones. Voice through iOS dictation. "Something hurts" and "ill" always back off and
  say to see a professional if it persists.

### 7. Send the session to the bike, and follow it without looking at the phone
Built 23 Nov 2026, after Neelay rode the surges with his phone propped up to read the steps. One session in the
engine, one sender per device (like the merge): each sender only translates the session's steps and targets.
- **Spoken cues, for every rider** (built, `RideAlong.swift`): "Ride it with spoken cues" on a session's page.
  Each step is spoken as it starts with its watts, ten seconds' warning before the work, halfway and one minute
  left on long steady steps, "three, two, one" at the end of hard ones. Plays with Zwift or music (they dip only
  while it speaks), keeps going with the phone locked (background audio), and the lock screen and Dynamic Island
  show the step, its target, a live countdown and what's next (a Live Activity, the `KovaLive` widget extension).
  It records nothing. The fallback for Whoop riders and anyone without a screen on the wrist or the bars.
- **Apple Watch** (built, `WatchWorkout.swift`): WorkoutKit puts the session in the Watch's Workout app, under
  Scheduled, with every step timed, the watts as a range the Watch nudges you back into, and a tap at each change.
  "Send to Apple Watch" on a session's page; or "Sessions on my Apple Watch" in Settings keeps the coming week's
  sessions there, re-sent each time Kova opens, so they follow the plan as it changes. The ride records as the
  Watch's own Cycling workout, so the merge doesn't change. (No partnership needed; it can't set the trainer's
  resistance.)
- **Garmin watches and the Edge:** next, once the developer access comes through; a FIT workout file shared by
  hand is the stopgap if wanted sooner.
- **Whoop:** as far as we know its API is read-only (no workouts sent, no buzzing the strap): spoken cues cover it.
  Check when we read Whoop's terms.
- **KICKR:** Wahoo Cloud API (public, OAuth, `workouts_write` / plans): the session appears in the Wahoo app, which
  runs it in ERG. Needs a Wahoo developer app (Neelay registers it).
- **Zwift:** .zwo export stays (Mac/PC Workouts folder). Easier uploads parked by Neelay, 23 Nov 2026. Automatic
  sync needs Zwift's Training API, partners only: apply once the backend is hosted.
- **Edge 840:** Garmin Training API with the business tier (`docs/hosting.md`); the Edge can drive the KICKR too.

### Method: the credential (alongside, any time)
- `docs/train-method.md` (draft 23 Nov 2026, for Neelay to edit): the philosophy and rules. The plan follows the
  riding: a week of jobs that any fitting ride can do, re-planned after every ride within fixed limits; the AI
  proposes inside the rules, the engine checks.
- `docs/training-science.md`: every rule in steps 1-2 with the published research behind it, in plain words
  (intensity distribution, progressive overload and easier weeks, fitness/fatigue load models, HRV-guided training,
  interval formats with evidence).
- A **Method** page in the app; "Why?" on a session links to its rule.
- A qualified cycling coach reviews the rules before other riders use Train; again each year. New research changes
  the rules only through us; the AI may summarise it, never apply it.

## AI across the app (analysis 21 Nov 2026; order agreed, starting 22 Nov)
Same pipeline as the ride story (engine facts -> Claude writes -> number check, saved by hash, cost log, background,
rule-based fallback, personal-use gate), generalised into a small "AI jobs" layer, with a 10-15 ride quality check
before going wide. The AI never calculates, changes the plan unchecked, gives medical advice or invents numbers.
1. The coach's morning brief and Sunday review; ride card stories and names (Efforts).
2. Route Generator: the AI reads free-form descriptions into the router's request (the regex stays as fallback).
3. "Ask your coach": answers from read-only tools over the rider's data; then changing the plan by talking (step 6).
4. Goals by talking (the 15 Nov mock-up); this month's "meta"; then the effort retold, the AI settling rides the
   rules are unsure of, a pre-ride route briefing, and recovery trends (only with Neelay's explicit OK: recovery
   data was agreed to stay out of the AI at first).
Rough cost for Neelay: $1-3 a month; a story for every past ride about $1-1.50 with the Batch API.

## What only Neelay can do
- Create an Anthropic API key for the backend (step 5).
- Register a Wahoo developer app (step 7).
- The paid Apple developer account (push notifications, step 4).
- Name the tab when he's ready.

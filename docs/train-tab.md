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

### 2. Engine: today's session, rest, and adapting
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

### 3. App: the Train tab, with rule-based words
- Replaces the Plan tab. Today (session day and rest day), the "then" line, the goal bar, The plan ahead (reusing
  `MonthCalendar`), The week matched, session detail (reusing `SessionDetail`, `IntervalChart`). Rule-based text
  for now, so it works before any AI, and keeps working without it.
- Efforts: a ride's screen says what it counted as.
- Then Neelay lives with it for a week or two before the AI goes on top.

### 4. The coach speaks up: events and notifications
- Backend events: a ride arrives (Garmin poll or Apple Health upload), the morning (07:30 his time), Sunday evening.
  Each makes an **inbox item** (`GET /v1/train/inbox`): kind, title, text, the screen it opens, read or not.
- **Until the paid developer account:** local notifications. The app wakes on Apple Health background delivery
  (already on for workouts) and background refresh, fetches the inbox and posts what's new. Garmin-only rides reach
  the phone the next time it wakes.
- **With the paid account:** push from the server (APNs), so every event arrives at once.
- Settings: after every ride, morning brief, plan changes, Sunday review (all on by default).

### 5. The AI coach: words on top of the engine
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

### 7. Send the session to the bike (later: Neelay left the Send buttons out for now, 21 Nov 2026)
- **Apple Watch, first:** WorkoutKit schedules the session into the Workout app with its steps and targets (no
  partnership needed; it can't set the trainer's resistance).
- **KICKR:** Wahoo Cloud API (public, OAuth, `workouts_write` / plans): the session appears in the Wahoo app, which
  runs it in ERG. Needs a Wahoo developer app (Neelay registers it).
- **Zwift:** .zwo export stays (Mac/PC Workouts folder). Automatic sync needs Zwift's Training API, partners only:
  apply once the backend is hosted.
- **Edge 840:** Garmin Training API with the business tier (`docs/hosting.md`); the Edge can drive the KICKR too.

### Method: the credential (alongside, any time)
- `docs/training-science.md`: every rule in steps 1-2 with the published research behind it, in plain words
  (intensity distribution, progressive overload and easier weeks, fitness/fatigue load models, HRV-guided training,
  interval formats with evidence).
- A **Method** page in the app; "Why?" on a session links to its rule.
- A qualified cycling coach reviews the rules before other riders use Train; again each year. New research changes
  the rules only through us; the AI may summarise it, never apply it.

## What only Neelay can do
- Create an Anthropic API key for the backend (step 5).
- Register a Wahoo developer app (step 7).
- The paid Apple developer account (push notifications, step 4).
- Name the tab when he's ready.

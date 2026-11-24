# How Train coaches: the philosophy and the rules

Agreed with Neelay, 23 Nov 2026 (his five decisions are folded in; see the end). Nothing here is built yet beyond
what's marked **(built)**. It extends the
line agreed on 18 Nov (`docs/coaching.md` section 7): the engine decides what must be right, the AI interprets and
talks, and the AI never changes anything directly. The research behind each rule goes in `docs/training-science.md`
(the "Method" credential in `docs/train-tab.md`), and a qualified coach reviews these rules before other riders use
Train.

## The question that started it
A rider sees "Surges" and rides a comparable but different Zwift workout instead. Do we try to fit that ride to the
plan, or does the plan follow the riding? **The plan follows the riding.** The people we build for are aspiring
riders, not pros: they pick a Zwift workout they like, join a group ride, or take the hilly loop because the sun is
out. A plan that grades them against a script loses them; a plan that counts what they did and works out what's
left keeps them.

## What the coach is for
Every rule below serves three aims, in this order. Riders should be **getting better, feeling good and learning**.
1. **Growth.** The rider gets measurably better: the goal's numbers move. The plan leans toward a bit more, not a
   bit less, inside the limits that keep the rider fresh. We're here for gains.
2. **Encouragement, the way a good coach gives it.** Specific and earned ("219 W on the last minute, higher than the
   first: that's control"), honest when a ride fell short, never gushing, never guilt. Praise names what was done
   well, and every note points at what's next.
3. **Education.** Every suggestion says why it works in a sentence, so the rider learns how training works and can
   make good choices without us. One new thing at a time, never a lecture.

## Principles
1. **Riding is the plan's input, not its test.** Every ride counts for what it did, read from the ride itself
   (power, heart rate, the sets in it). Nothing is ever "missed", "failed" or "off plan".
2. **A week is a set of jobs, not a list of workouts.** The goal decides the jobs; a suggested workout is one good
   way to do a job, never the only one.
3. **The rest of the week re-plans around what's left**, after every ride, within limits that keep the rider safe
   and fresh.
4. **The rider's choice wins**: which workout, indoors or out, which day, whether to ride at all. The plan bends and
   says how; it doesn't nag.
5. **The plan learns from evidence, in small steps it explains**: how sessions felt, recovery, the goal's numbers
   moving or not, the jobs that keep getting skipped.
6. **The engine calculates, the AI explains and proposes.** The AI never counts a ride, never makes up a number and
   never crosses a limit; the engine checks everything it proposes.
7. **Plain words** (`docs/train-words.md`): what the ride did, what's left, why. No FTP, TSS, zones by number,
   "compliance" or guilt.

## The jobs
Each goal's week is a mix of these (from `plan.FOCUS`; today each job has one suggested workout):

| Job | What it builds, in the rider's words | Done by (any of these) | Counts as done when |
|---|---|---|---|
| **Punch** | Answering accelerations, closing gaps | Surges; any workout of short hard efforts; sprints; a hard group ride | The hard minutes the week's suggested workout asks (at least 5), in efforts of 10 s to 2½ min |
| **Top end** | The hardest few minutes: a long climb, a breakaway | VO2 max sets | The hard minutes the week asks (at least 10), in efforts of 2½ to 8 min near the top |
| **Hold** | The power you can keep for the whole ride | Sweet spot; threshold; over-unders; a long steady climb | The steady minutes the week asks (at least 20), just below or at what you could hold for an hour, in stretches of 3 min or more |
| **Long** | Endurance for long rides | One ride of at least 80% of the week's long-ride time, and never under 90 min | One ride long enough |
| **Easy** | The base everything sits on, and recovery | Any easy ride | Any easy riding |
| **Rest** | Where the fitness is actually built | A day off the bike | At least one a week (more by the limits below) |
| **Strength and mobility** | Staying injury-free | Off the bike, 20 min | Ticked by the rider |

The thresholds in the last column are starting points to check against the research and against real weeks.
How the engine reads them: `train.jobs_done` **(built 23 Nov, step 1)**; how much each workout asks:
`plan.job_minutes`. Rides with heart rate only are a rough read and say so: rises to near the limit stand in for
hard efforts, and steady work is read only on rides under 2½ hours (heart rate drifts up on long ones).

The jobs keep these names for now (decided 23 Nov). Workouts keep their own names (Surges, Sweet spot) as the
suggested way to do a job.

- **One ride can do two jobs, when it's long enough for both.** A three-hour group ride with hard surges does punch
  and long; a 90-minute one with the same surges does punch only. Two hard jobs only on a ride of 90 min or more,
  the second done in full; on a shorter ride the harder job counts and the other is said ("Also 20 min of steady
  riding at about 152 W: good hold work on top; the week's hold job is still to come"). A ride never does the same
  job twice.
- **Partly done leaves the rest open: we lean toward more.** Three hard minutes instead of five: "Punch: 3 of 5 min
  done. 2 more finishes it." The rest stays on the week. When it's small (half the job or less) it's folded into a
  ride already planned that can take it without breaking a limit: a few hard efforts in the last hour of the long
  ride, or added to the next hard day; never onto an easy day or the day after a hard one. When there's no room,
  it's said once and dropped, not carried over as a debt.
- **More than the job asked counts for more.** Extra hard minutes are credited ("Punch, and then some: 12 min of
  hard efforts against 5"). They count toward the week's hard days, so the next day is easy as the limits say, but
  the rest of the week's jobs stay as they are.
- **Jobs grow with the rider (progression)** **(built 23 Nov)**. A job done fully and felt good or easy (or with no
  tap) steps up next time: a quarter of the way from the lightest to the hardest version (surges 5 to 6 reps, sweet
  spot 2 × 10 to 2 × 11 min). Partly done, missed or felt hard: same again. Wrecked or something hurts: a step
  back. Base weeks grow at most halfway, build and sharpen all the way (sharpen starts halfway); easier weeks,
  the taper, easy, long and group rides don't grow.

## Zone 2 (24 Nov 2026, `rideengine/analysis/zone2.py`)
Neelay's call: use the term **zone 2**, the one zone name every rider knows; plain words for the rest.

- **What it is:** the hardest you can ride while still below your first threshold, where breathing and lactate first
  start to rise (`zone2` in `docs/training-science.md`). The everyday check: easy enough to talk in full sentences.
- **The range:** 60-70% of heart rate reserve (resting and max, as Apple's zones appear to work; Garmin defaults to %
  of max, which reads far too low for a trained rider). The rider can set their own (a lab test, or the zone 2 on
  their Watch or Edge) under Train › Zone 2; every ride and every session's heart-rate target follows it.
- **Checked from normal riding:** a steady ride with power of 40 min or more whose heart rate drifts under 5% at the
  same watts stayed aerobic. Only rides ridden near the range count (a steady threshold workout says nothing about
  zone 2). It says "fits", "may top out lower" or "may reach higher"; it never changes the range on its own.
- **After every ride, one key number:** % of moving time in zone 2, with how much was above and below (stops don't
  count). It's shown on every ride; words only where zone 2 was the point (a zone 2, long or easy ride): earned
  praise at 70% or more in, one thing to change when 25% or more was above (spin the climbs in a low gear; ease the
  trainer down), or when it was mostly below (raise the trainer). Hard days: the split, nothing said.
- **The week:** its share above zone 2, against about 20% (polarized training, `easy-most`).
- **The plan:** Endurance is now **Zone 2**; the long ride is zone 2 the whole way. On the Watch, zone 2 riding of 10
  min or more has heart rate as the ceiling (a nudge when you pass the top, never for riding easier); watts stay
  the target for the hard work. Recoveries inside sets keep no alert.
- **The proof it works:** watts at zone 2 heart rate, month by month (rides with power: the trainer, for now).
- **The AI coach** gets the split as percentages, never the range (it's worked out from resting heart rate).

## The rules
### Limits no plan change and no AI can cross (most are built)
- No hard days back to back **(built)**.
- At most 4 riding days in a row; rest after 3 when the week allows **(built)**.
- Something hurts: rest, and see someone if it doesn't settle **(built)**. Wrecked: the next day is easy **(built)**.
- Recovery lower than usual in the morning: easy or rest **(built)**. Recovery numbers are never shown to anyone
  else and never sent to the AI (CLAUDE.md).
- Watt targets move at most 5% per tap and stay within 15% above the estimate of what the rider could hold for an
  hour **(built)**.
- The week's riding time stays within the hours the rider gave, plus 10%. Every fourth week is easier, and the
  last week before the goal tapers **(built in the plan)**.
- Indoors or out is always the rider's choice **(built)**.

### After every ride (automatic, said in a line)
1. Read what the ride did: its kind and sets **(built)**, then which jobs it did and how much (new: jobs, not one
   session).
2. Work out the jobs left this week.
3. Place them on the days left, hardest job first, within the limits. If they don't all fit, drop the least
   important for the goal, and say so ("No room for the long ride this week; it comes first next week").
4. Re-pick the suggestion for each job to fit the day: shorter on a busy day, indoors when the rider usually rides
   indoors that day.
5. Never carry a missed job into next week as a debt. The Sunday review decides next week afresh.
6. **Say what changed, lightly.** The week lays itself out again on its own (decided 23 Nov), so the rider always
   sees when it looks different and why, in a line, without having to approve anything. See "When the plan
   changes" below.

### Week to week (the Sunday review; a bigger change needs the rider's OK)
- How hard sessions felt moves the watts **(built)**: easy raises them 5%, good or hard keeps them, wrecked eases
  them back.
- A job skipped two weeks running: offer a different way to do it (a group ride instead of surges, outside instead
  of the trainer), not more of the same.
- A goal number that hasn't moved in 4 weeks: shift the week's emphasis toward the job that builds it, and say why.
- Riding more than planned and feeling good: grow the week slowly (up to 10% more time). Feeling tired: an easier
  week early.
- Phases follow the plan **(built)**: base, build, sharpen, an easier week every fourth, taper.

## What the AI does, inside these rules
- **Reads messy input**: a Zwift workout's name, or "club ride Saturday, away Tue–Thu, knee's sore". It turns it into
  facts the engine can use.
- **Proposes**: the rest of the week when riding went off the suggestions, next week's emphasis at the Sunday review,
  a different way to do a skipped job. Proposals come in a fixed format (the change, the reason, the rules it relies
  on); the engine checks them against the limits; small changes apply automatically and are said in a line; bigger
  ones (the week's hours, the mix of jobs, the goal) wait for the rider's OK.
- **Explains**: the ride's story, why today's suggestion, the weekly review, "why?" on anything.
- **Never**: counts a ride, makes up or changes a number, crosses a limit, gives medical advice, or sees recovery
  numbers.

## What the rider sees
- After a ride: **what it did** ("Punch: done. 6 × 45 s and 4 × 2 min, 12 min of hard efforts") and **what's left
  this week** ("Still to come: hold, and the long ride on Saturday").
- **Planned against ridden** only when the ride was the suggested workout (its sets line up), as a detail under it.
- The **ride card names what the ride was**: the suggested session's name when it was that workout, else the kind
  of work ("Punch"), or the Zwift workout's name when we have it.
- The **week shows jobs done and left**, with today's suggestion for each, not a list of sessions ticked or not.
- **Today** stays one suggestion with its why, how it should feel and what's next. Under it, the job's shape in
  words, so any workout the rider likes can do it: "Or any ride with 5 to 10 min of hard efforts of 30 s to 3 min,
  easy between." No Zwift or other app's workout names (decided 23 Nov).
- **Every note teaches one thing.** The ride note and Today each carry one "why it works" line, varied so it doesn't
  repeat: "Short hard efforts with short rests train you to recover while still riding: exactly what a group's
  surges ask." The research behind each line lives in `docs/training-science.md`.
- **Every note encourages like a coach**: one specific thing done well, from the ride's own numbers, then what's
  next. Never "great job!" on its own, never a comparison that shames.

### When the plan changes
The week is laid out fresh from what's still open each time it's read: nothing is "moved", and no history of
moves is kept (simplified 24 Nov 2026). A session done sits on the day it was ridden; one still open sits on the day
the fresh layout puts it. The plan's dates are only its first sketch, never shown as "planned Wednesday".
The rider should notice a new layout without being interrupted:
- **One line on Today**, shown until seen, when a session still to ride lands on another day than last shown:
  the week as it is now, and the reason in a few words. "Your week now: sweet spot Wednesday, group ride Friday.
  Tuesday's ride did the punch." Tap it for the week. Only the last layout shown is kept, to compare with. A ride
  that just did a session isn't news.
- **A notification only for a bigger change** (a job let go for the week, the long ride on another day); the
  rest stays in the app.
- The line names the evidence, never the rule: "Tuesday's ride did the punch", not "re-planned per rule 3".
- **The Apple Watch** has the coming 7 days' sessions on their days, all from the morning brief's time (06:00
  unless the rider changes it): Apple asks for a time, but any of them can be started whenever the rider likes,
  so a different session than the day's is always there too.

## What changes in what's built
- `train.match_week`: from one ride to one session, to a ride doing one or more jobs, with how much of each.
- `today.plan_today`: picks the next job, not the next session, then the suggestion for it.
- `train.against`: shown only when the sets line up with the suggestion; otherwise the ride's own sets and its hard
  time against the job.
- The ride card and the ride note: the job and what the ride was, not the session's title by default.
- The week view and What's Next: jobs done and left.
- The Garmin connector: read the activity's name (Zwift puts the workout name there), if the data has it.
- The plan itself: weeks of jobs, each with a suggested workout, instead of weeks of workouts.

## Decided, 23 Nov 2026
1. **Names:** punch, top end, hold, long, easy, for now.
2. **Two jobs from one ride:** yes, if it's long enough for both.
3. **Partly done:** lean the rider toward more, not less; don't overdo it, but we're here for gains. The rest of
   the job stays open and is folded in where a limit allows.
4. **Alternatives:** describe the shape; no Zwift workout names.
5. **What moves on its own:** the week's remaining jobs, automatically, with a light, elegant line saying what
   changed and why. Hours, the mix of jobs and the goal still need the rider's OK.

## Build plan
Each step ships on its own, with tests on synthetic weeks and a check on Neelay's real week.
1. **Jobs from a ride** (engine) **(built 23 Nov)**. `train.jobs_done(work)`: which jobs a ride did and how much of each (hard minutes
   by effort length, steady minutes, longest ride), from the sets and phases it already reads. Shown alongside
   today's session counting at first, so the two can be compared on real rides.
2. **A week of jobs** (engine and backend) **(built 23 Nov)**: `train.count_jobs` fills the week's sessions by job
   (a session's job: `plan.JOB_OF`; the group ride is punch); a session is done when its job is done in full, by
   one ride or several, and partly done shows what's left. Sessions grow from the evidence (`plan.grown`,
   `Backend._grow`/`_learn`): each job's sessions take their size from earlier weeks only, from the plan's
   `grow_from` day on, so sessions already shown keep their size; a step up or back is said on the session's page.
   The week view shows each session's job and how much is done. As planned: Plan weeks list jobs, each with its suggested workout and its shape;
   `match_week` counts jobs (two from one ride, partly done with the rest open); progression by evidence
   (`level` per job, stepped by done-and-felt). The week view in the app shows jobs done and left.
3. **Re-plan after every ride** (engine and backend) **(built 23 Nov)**: `today.plan_today` lays the week out
   again each time it's read (`Backend._replan` in the plan view): leftovers of half a job or less become a set
   (`plan.leftover`) in the next hard day or the long ride, taking the place of its filler riding; when the open
   sessions don't fit, the one that matters least for the goal is let go, one at a time. When the layout differs
   from the last one shown (`plan_snapshots` keeps only that), a note is kept with its evidence (`plan_changes`;
   `Backend._plan_changes`), e.g. "Your week now: sweet spot Friday" because "Wednesday went by without a ride";
   `changes` on Today (the newest), marked seen with `POST v1/train/changes/seen`. Since 24 Nov each session has
   `on`, the day it's on (ridden, or laid out), which the week, the calendar and the Watch use. As planned: Place the jobs left on the days left within the limits; fold
   small remainders; drop and say when there's no room; store each change with its reason.
4. **What the rider sees** (app) **(built 23 Nov; simplified 24 Nov)**: the "Your week now" line on Today with
   its reason, shown until seen (a few seconds on screen, or tapped, which opens the week); a notification only
   for a bigger change (a session let go, the long ride on another day). Every riding session carries its job's shape (`plan.shape`: "Or any ride with 7.5 min or
   more of hard efforts of 30 s to 2 min…"), on Today and the session's page. The ride note says what's left this
   week. Planned against ridden only when every planned set is in the ride (`Backend._ridden_against`); the card
   names the session then, else the kind of work ("Punch"). As planned: The ride note's "what it did, what's left"; the card names what the ride was;
   planned vs ridden only when the sets line up; Today's shape line; the line when the week's layout changes.
5. **Coach's voice** (backend and AI) **(built 23 Nov)**: `rideengine/analysis/voice.py` (`learn`, `done_well`),
   the research in `docs/training-science.md` (a first pass, to be reviewed by a coach and each reference checked),
   the words in `docs/train-words.md`. The AI gets `done_well` as the only praise it may give. As planned: The "why it works" line and the specific praise, from the engine's facts,
   in the AI's words when it's on and from `docs/train-words.md` when it's off; the research for each in
   `docs/training-science.md`.
6. **The Sunday review** **(built 23 Nov)**: `rideengine/analysis/review.py` (`review`, `check`), the backend's
   `train_review` / `decide_proposal` (`GET v1/train/review`, `POST v1/train/review/proposals/{id}`), the review
   screen and a card on Today from Sunday evening to Tuesday; the Sunday notification opens it. Proposals come only
   from the rules below and are checked before they apply; the AI coach (when on) writes the summary and each
   change's why, and its reply is refused if it adds or drops a change or uses a number not in the facts.
   Free-form proposals from the AI wait for "changing the plan by talking". As planned (with step 5 of
   `docs/train-tab.md`): skipped jobs offered another way, emphasis shifted
   when a goal number stalls, the week grown or eased; the AI proposes in a fixed format, the engine checks, bigger
   changes wait for the rider's OK.

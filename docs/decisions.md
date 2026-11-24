# Decisions, and why

Product decisions Neelay made, with the reasons, newest first within each topic. The rules that follow from them are
in CLAUDE.md; this is the background, for when a rule is questioned or a change touches one.

## Data
- **Strava is not a data source** (13 Nov 2026). Its API terms bar AI use and showing a user's data to others. Strava
  records nothing itself, so every ride is available from the device's own source anyway.
- **All data arrives automatically; no archive importers** (15 Nov 2026, `docs/coaching.md`). The rider signs in once
  per source and every ride arrives on its own.
- **Apple Health: read only what's needed.** Agreed 14 Nov 2026 (workouts, routes, heart rate, calories, distance;
  heart rate in the 3 minutes after each ride; VO2 max, HRV, resting heart rate, Cardio Recovery), widened 17 Nov 2026
  to power, cadence and speed from a Watch-paired sensor (the KICKR). Recovery data is never shown to other people.
- **Calories: the wearable wins** (Neelay's call), then energy from measured power, then the head unit.
- **Device totals beat GPS-derived ones** (barometric climbing, moving time, wearable calories). Scugog loop: the
  Garmin's 850 m barometric total wins over the 633 m from the GPX track.

## Zone 2 (24 Nov 2026)
- **Call it zone 2** (Neelay), the one zone name riders know; plain words for everything else.
- **One key number after a ride:** % of moving time in zone 2, then above and below, not every zone mapped.
- **The range:** 60-70% of heart rate reserve until the rider sets their own; checked from steady rides' drift, never
  changed by the engine on its own. Details: `docs/train-method.md` "Zone 2".

## Indoor riding
- **Indoor km and climbing count** (19 Nov 2026, replacing the 17-18 Nov "count 0" rule). Neelay: "As a rider I want
  credit", and hill training on Zwift is real work against gravity. They count in every tally, streak, Everest and
  month total, split out as `indoor`; All Time shows outdoors/indoors side by side.
- **Bests and single-ride badges stay road rides**, and there are no separate indoor bests or virtual segments: Neelay
  found them too cluttered. A Zwift hour shouldn't take "longest ride" from a real 105 km.
- **Only climbing a ride game reports counts** (Zwift, Rouvy); never invented from ERG power or Watch-only trainer
  sessions. Indoor rides never match real routes or climbs.
- **The indoor ride card has no power trace** (19 Nov 2026): Neelay found it told him nothing. It shows time, power
  and heart rate, plus Climbed when a ride game reports it.
- **Indoor mini cards**: a picture like the outdoor ones (Zwift's virtual route, else the session's power or heart-rate
  shape). First on wine (19 Nov), changed to pale blue with cobalt lines (20 Nov): wine felt aggressive or negative,
  and a whole new colour would have been out of place.

## Training (the Train tab, `docs/train-tab.md`)
- **Indoors or out is always the rider's choice** (21 Nov 2026). The plan's season only suggests the trainer in
  winter; sessions are named neutrally (Group ride, not Zwift group ride), Today says "indoors or out" with advice on
  where each suits, the tab icon is rising bars (not a trainer), Zwift export is offered for any structured session,
  and outdoor rides without power count by heart rate (long steady stretches at a sweet-spot or threshold heart rate).

## The four headline numbers (You)
- Reviewed 19 Nov 2026; Neelay chose to **leave them as they are** for now, with these known quirks:
  sustained power only moves on a new best 20 minutes in 120 days; efficiency's baseline came from one ride, so
  ordinary noise reads as below baseline; durability needs rides of 2 h or more, so never indoors, and its baseline
  and target were both 100, so its bar was full from day one. Proposed and declined: indoor durability from heart-rate
  drift at matched power on 90+ min trainer rides; "holding at 100%" instead of a bar.

## Name and look
- **The app is Kova** (19-20 Nov 2026). Finnish for strong (*kova kunto*: in top shape). Neelay wanted two syllables
  or fewer, made up or foreign to avoid trademarks, and likes how Strava works as a name (a foreign verb for the act).
  Tried first: Kado (felt "better than nothing" among his other icons), Orka (an Orka multi-sport training app exists),
  Spinta (still free in a quick search). Quick searches found no app called Kova; a KOVA trademark exists for physical
  sporting goods, not software. Check properly before going public.
- **KOVA also stands for Kilometres. Output. VO₂. Ascent.** (20 Nov 2026), sparked by Neelay's son explaining "meta" as
  "most effective tactic available". Ascend was tried for a day, then back to Ascent. Ascent is in the summit dot's
  yellow. About Kova: "Kova is Finnish for strong. It also stands for the four things we will help you build:", with
  Ascent = "Rise to the climb." (weighed against "Crush those hills" and "Reach your goals", which felt generic).
- **The icon is a symbol, not a letter**, like Strava's chevrons: "the climb", five columns of dots rising to a yellow
  summit on graphite. Tried on the colour ribbon, then the ribbon was dropped. Mock-ups:
  https://claude.ai/artifact/LcEQTiwpvgb7D6hy49uFr9.
- **The opening screen**: one yellow dot slides up the climb (redrawing the yellow per column didn't read as
  movement), then KOVA letter by letter, each rising and sharpening out of a blur, about 4 s in all (2 s was too
  quick), tap to skip. The meaning line under the name was dropped on 21 Nov 2026; it stays in About Kova. It fades itself out on its own
  opacity: a removal transition from the App's state jumped in one frame.
- **Cleaner screens** (20 Nov 2026): no big titles on the tabs and no buttons under the Efforts hero card, so content
  starts higher. The ride screen keeps Share and What you did.
- **The look is direction D** (13 Nov 2026, `docs/design.md`): porcelain, serif titles, Plex text, dot-matrix heroes,
  the collectible ride card.

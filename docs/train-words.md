# Train: how the words work

Agreed direction 21 Nov 2026 (Neelay: "get the text on the cards optimised for clear interpretation: what is
analysis, what is matching, what is motivational direction for immediate next steps"). This guide is for the
rule-based text and is the fixed format the AI coach writes in (`docs/train-tab.md`, step 5). Mock-up:
https://claude.ai/artifact/PqSSKTSmCHpzt5V63k8io2.

## Four kinds of words, always in this order, each under its own label
A rider should always know whether they're reading a fact, how Kova filed it, what it means, or what to do next.

| Label | What it is | Rules | Example |
|---|---|---|---|
| **WHAT YOU DID** | Facts from the engine | Numbers with units, no adjectives, no judgement | 35.6 km on Zwift · 392 m climbed · best minute 273 W |
| **COUNTED AS** | How the ride was filed against the plan | The session's name, then the reason in the ride's own terms, then what was planned. Tap to change | Surges (planned for Monday). Each climb was a hard minute or so, with easier riding after |
| **WHAT IT MEANS** | The link to the goal | One or two sentences. Names the goal or a marker. Says honestly whether it moved, held or dropped. Praise lives here | Punch is your best hard minute, and 273 W is past the 223 W you were aiming for by May |
| **WHAT'S NEXT** | One clear step | Starts with the day or the verb. One action, with when. Doable today | Tomorrow: rest. Wednesday: sweet spot, 3 × 12 min |

Plus **ONE THING TO TRY** (after a ride, when there is one; added 21 Nov 2026 at Neelay's request): constructive
coaching from what the ride contained, to make the rider better. One per ride on the card (the rest a tap away).
It says what we saw, with the numbers; what to try; and why it helps, in the rider's terms. Coaching, never
criticism. Example: "On 3 of the climbs your cadence dropped to as low as 55 rpm. Try a lighter gear and keep it
at 75 rpm or more: grinding a big gear tires your legs faster, while a quicker cadence shares the work with your
heart and lungs, so you've more left at the top." What we look for, most useful first: an easy day ridden hard;
going out too hard on the first of a set of efforts; cadence on the climbs; sweet spot drifting into threshold;
heart rate climbing at the same power late in long rides (drink and eat); no warm-up before hard work; cadence on
steady riding too low or too high (`rideengine/analysis/feedback.py`).

Plus **ASK**: one question, answered with one tap ("How did it feel?").

A session that's still to come uses the same idea in its own order: **the session** (name, and what it is in one
line), **HOW IT SHOULD FEEL** (feel words first, then the numbers), **WHY** (the goal), then **WHAT'S NEXT**.

## Rules
- **Plain words first, numbers second:** "the power you could hold for about an hour (147 W)". A number on its own
  only where the label already says what it is.
- **One name per thing, everywhere.** A session is always called the same; the first time it appears on a screen it
  carries its one-line meaning (glossary below). Tap any session name for it.
- **No jargon:** never FTP, TSS, CTL, ATL, zones by number (Z2), ERG, compliance, "matched", "load". Say "the power
  you could hold for an hour", "how much training", "easy", "hard".
- **Praise is specific and earned:** it names the thing and why it matters for the goal. Never "Great job!",
  "Crushed it", "Beast mode".
- **Honest:** say when a ride didn't count, when a number isn't moving yet, and when we'll be able to tell
  ("too early to call; I'll judge the trend from week 4").
- **Motivation is a clear next step plus why it matters, never guilt.** A missed session: "No problem: it moves to
  Thursday." Never "You missed…".
- **Short:** one idea per sentence, two sentences per block at most. "You" for the rider; the coach says "I" only
  when it decided something.
- **Indoors or out is the rider's choice** (Neelay, 21 Nov 2026). Never assume where a session is ridden: no
  "indoor" in session names, no trainer icon. Where to ride is advice ("Indoors or out. The trainer makes the
  efforts easy to hit; outside, pick a quiet road…"), and outdoor rides without a power meter are ridden and judged
  by feel and heart rate.
- **Privacy on the lock screen:** notifications never show HRV, resting heart rate or other recovery numbers;
  "your recovery looks normal" is enough. Inside the app, the rider sees their own.

## Glossary: sessions (name, what it is, how it should feel)
| Session | What it is | How it should feel |
|---|---|---|
| Surges | Hard efforts of 30 seconds to 2 minutes, easy riding between. Builds the punch to stay on when the group speeds up | Hard parts 8–9 out of 10, too hard to talk; the rest easy |
| Sweet spot | Long steady blocks just below your limit. Raises the power you can hold for the whole ride | 7 out of 10: comfortably hard, short sentences only |
| Endurance | Steady and easy, for a long time. Builds the base everything else sits on | 4 out of 10: you could chat all the way |
| Group ride | Riding with others at their pace (Zwift in winter). Practice for the real thing | Varied: sit in, then answer the surges |
| Easy spin | Short and very light. Helps you recover | 2–3 out of 10 |
| Rest | No riding. When the fitness from hard days is built | — |
| Strength and mobility | 20 minutes off the bike | — |

## Glossary: what we measure
| Name | Plain meaning |
|---|---|
| Sustained power | The power you could hold for about an hour: what keeps you with the group |
| Punch | Your best hard minute: closing a gap, getting over a rise |
| Recovery | Whether your body looks ready for hard work, from HRV and resting heart rate against your usual range |

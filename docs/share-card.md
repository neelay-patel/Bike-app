# Ride story share card

**Update 13 Nov 2026:** the look changed to direction D (docs/design.md). The share card is now the
collectible ride card (`rideengine/card/ride_card.py`): name strip with the ride's number in the year,
real route on a cobalt field, stripe band, serif headline, dot-matrix stats. The graphite card below
(`make_card.py`) is kept for reference; its story ideas (headline from stops, towns, HR peak) carry over.

Canvas with the current prototypes: https://claude.ai/artifact/6vEqXrfwo3ozkCh8byzDin
(Scugog loop, 19 Oct 2026; Durham Forest loop, 3 Oct 2026). Generator: `rideengine/card/make_card.py`.

## Decisions (12 Nov 2026)
- Built first: the storytelling/sharing piece, ahead of coaching, routes and group rides.
- Format: one punchy 9:16 share card.
- Look: monochrome silver on graphite, not Strava-style. Readable on a phone: nothing under 11 px at the 540 px design width.
- Headline from the ride itself, e.g. "Uxbridge for coffee. Cannington for lunch." (two longest stops) or "1,139 m in 69 km. Lunch in Uxbridge, earned."
- One continuous route (no out/back split), with town labels for context (only towns the route actually passes within ~300 m of) and a heart-rate peak marker.
- Full elevation profile with town ticks, shown throughout.
- Animation: the route draws while a progress dot moves along the map and, in sync, along the elevation profile; then the dial arcs sweep up. Respects reduced motion.
- Five open-arc dials (gap at the bottom, label in the gap): distance; speed (average, thin inner band for max); metres climbed; heart rate (average, max); calories (Apple Watch active).
- Power: a vertical strip down the right of the map, average and max watts only, hidden when there's no power data, tagged SIM when simulated.

## Open items
- Pick places, stops and the headline automatically for any ride.
- Fit the map to each route's shape (tall, narrow routes leave empty space).
- Dial scales are placeholders (0–160 km, 0–60 km/h, 0–1,500 m, 0–200 bpm, 0–3,000 kcal); make them relative to the rider's own bests.
- Indoor (KICKR) card: power trace as the "map".
- Not built yet: wind, road surface, photos.

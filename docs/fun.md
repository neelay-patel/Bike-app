# The fun bucket: avatar, rider card, badges, holo cards, binder

Built 14 Nov 2026. Everything comes from the rider's own rides, by rules (`rideengine/analysis/collection.py`).
Our own drawing style, not a copy of any existing card game's art.

## Avatar (`rideengine/card/avatar.py`)
- Drawn in code as SVG from parts: skin (6), face (3), hair (5) and colour (6), beard (none, stubble, goatee, short,
  full) and moustache (none, moustache, handlebar) as two choices so any pair works, glasses (4), helmet / cap / none
  and its colour, jersey and stripe colours (10 each), pattern (band, sash, hoops, plain). Bike is stored, not drawn yet.
  Specs saved before beard and moustache were split keep their look (`clean()`).
- **Until a rider makes one**: the rider card shows a plain silhouette (never a default face), ride cards have no
  background figure, and the Binder shows "Make your avatar". The first Binder visit opens **four quick questions**
  (skin, hair, beard or moustache, helmet or cap) and the name; "More options" opens the full builder.
- One drawing everywhere: the builder's live preview (`POST /v1/avatar/preview`, swapped in place, no reload), the rider
  card, and **big and quiet behind every ride card's map** (tints of the map's blue, half opacity, under dots and route).
- Saved on the user (`PUT /v1/me {"name", "avatar"}`; `{"avatar": null}` removes it); unknown parts fall back to defaults.

## Rider card (`rideengine/card/rider_card.py`, `GET /v1/rider/card`)
- Ratings out of 99 from the **last 12 months**: Distance (top 3 rides, log scale 20 to 200 km), Climbing
  (top 3, 150 to 2,500 m), Speed (best average on a 30 km+ outdoor ride, 18 to 35 km/h), Endurance (longest
  time riding, 1 to 6 h), Consistency (weeks with a ride out of the last 26). Overall is the average.
- Rider type is the strongest rating: Rouleur, Climber, Flier, Diesel, Metronome. Neelay: Diesel, 80.

## Badges (24)
Distance (50 to 200 km rides), Climbing (1,000 and 2,000 m days, an Everest month), Tally (1,000 to 10,000 km,
50 to 250 rides), Consistency (4, 10, 26-week streaks; every month of a year), Speed (fast fifty, thirty club),
Routes (10 and 50 home-loop laps, 10 times up a climb), Dawn patrol (started before 6:30 local time; rides far
from home use the local time there). Each records the ride and date it was earned; the rest show progress.

## Holo cards
A ride is holo when it set an **all-time best** (distance, climbing, time, speed, power) or a **first** (first
100 km...), as of the ride's date. Climb times, home-loop laps and streaks don't count (too frequent). About 7 a
season for Neelay. Holo ride cards get an iridescent header that slowly shimmers (still with reduced motion).

## Season binder (`GET /v1/collection`, Binder tab)
One page per year: every ride's card in order (number in the year, route outline, name, distance), holo
cards marked, and an **empty slot for every week with no ride**. Tap a card for the ride. The rider card sits at
the front, then badges, then the binder.

## Privacy
Route outlines in the binder are only shown to the rider. Shared ride cards still cut the route around home.

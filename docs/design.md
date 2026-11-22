# The look (direction D)

Chosen 13 Nov 2026 from four directions on the design canvas
(https://claude.ai/artifact/9djB8PLRtvKuNPAuGcrqqQ, row D). Mostly direction C, built from Neelay's
references (dot-matrix climb overlays, a training app with deep cards and serif headings, collectible
cycling cards), with direction B's calm everyday type. Values live in `design/tokens.json`.

## Rules
- **Ground:** porcelain. Content sits on light cards (`surface`, 1 px `line`, radius 16–22).
  Deep cobalt cards are for one hero per screen (e.g. this month's total). The dark `panel` is for
  the ride's profile and its big totals.
- **Type:**
  - Instrument Serif for screen and ride titles only.
  - IBM Plex Mono, upper case, tracked 0.16 em, for small labels (dates, LENGTH, AVG HEART RATE).
  - IBM Plex Sans for everything people read: sentences, list rows, buttons, list numbers.
  - Doto (dot-matrix) **only for hero numbers**: a month total, a ride's main totals, the insight
    figure, the ride card's stats. Never in lists or running text.
- **Colour meaning:** heart rate is always `heart` (burgundy). Cobalt marks the hero and "now/after"
  in comparisons. No other accents.
- **Charts:** elevation is a halftone dot fill under a thin line, fading downwards, on the dark panel,
  with the heart-rate peak marked. Before/after comparisons are two-point dumbbells.
- **Honesty:** every value says where it came from (source chips); simulated values are tagged SIM;
  stretches left out (car) and hidden false starts are stated, not silent.
- **Readable:** nothing under 11 px; text contrast at least 4.5:1; touch targets at least 44 pt.

## The ride card (sharing)
Map (decided 13 Nov 2026): the route fills the map; behind it a faint dot grid with dots a real
distance apart (1 km, or 2/5 km on long rides) and no legend, so dense dots mean a big ride. No
decorative lines. Up to two town or village names the route went through, from GeoNames offline
(`rideengine/places.py`): places where the rider stopped 10+ minutes first (coffee, lunch), then the
biggest; the start/finish town only if nothing else. Labels get a cobalt halo and avoid each other.
Collectible format: name strip (serif name, "NO. 34 · 2026"), the route on a cobalt field with the
km dot grid, towns and the heart-rate peak, a five-colour stripe band, the headline in serif on a sand
panel, then the stats (mono labels, dot-matrix values). Rides are numbered within their year.

## Fonts
All under the SIL Open Font License; each licence ships beside the fonts in
`ios/RideApp/RideApp/Fonts/`.
- Instrument Serif and IBM Plex Mono: Google Fonts' files, unmodified.
- IBM Plex Sans 400/500/600: IBM's own static files (github.com/IBM/plex), unmodified. "Plex" is a
  Reserved Font Name, so never ship a modified Plex (e.g. cut from the variable font) under that name.
- Doto 900 with round dots (ROND 100): cut from the variable font (fontTools instancer). Doto has no reserved name.
PostScript names for code: `InstrumentSerif-Regular`, `IBMPlexSans`, `IBMPlexSans-Medm`,
`IBMPlexSans-SmBld`, `IBMPlexMono-Regular`, `IBMPlexMono-Medium`, `Doto-Black`.

## Credits (CC BY / OFL require them)
Place names: GeoNames (geonames.org), CC BY 4.0. Shown in the app's Settings → Credits.

## Motion (21 Nov 2026; `ios/RideApp/RideApp/Motion.swift`)
Motion helps you read the screen; it is never decoration. Most of it plays as things come into view, and again each
time you open the tab (`tabVisit`); returning from a ride's screen doesn't replay it. Only
signposts keep moving, and they move slowly. Reduce Motion stills everything.
- **Arriving:** cards fade and rise in turn (`arrive`).
- **Charts draw in left to right, the way you'd ride them:** session shapes and interval charts grow bar by bar.
  Ride power and elevation, route surfaces and sparklines are revealed from left to right.
- **Route lines trace themselves** from start to finish: route rows and collection cards (`DrawnRoute`).
- **Numbers count up:** tallies, headline numbers, goal markers. A met aim pops in after its bar fills.
- **Signposts that keep moving:**
  - Train: a light runs from today down to what's next (`FlowThread`).
  - The week's next session ripples (`Ripple`).
  - A rest day breathes (eight-second swell).
  - Sources: a connected source's live dot breathes.
  - The Route Generator's wand twinkles while it works.

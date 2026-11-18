# Routes

Decided 17 Nov 2026. How Neelay plans rides today: he drives out for gravel (little near home) and for long road
rides, prefers routes that are 50–70% gravel, navigates with a Garmin Edge 840, and researches heavily before
committing. When a route goes wrong it's boring, has nowhere to refuel, or the off-road turns out to be endless
singletrack. So the job isn't drawing a line: it's **cutting the research** and giving him confidence before the day.

## The plan, in order (each step usable on its own)

1. **Route check** (built 17 Nov 2026). Bring in a GPX (Ride with GPS, Komoot, Garmin Connect), get the research
   in one page, send it to the Edge.
2. **Tuning** (built 17 Nov 2026): move the start, add a coffee stop, shorten or lengthen by N km while keeping
   the gravel share. See "Tuning" below.
3. **Generating loops** from a description (built 18 Nov 2026): "60–70 km gravel loop near Uxbridge, café halfway"
   → three checked loops. Our own router on our own map, no outside routing engine. See "Loops from a description".
4. **The chat** on top: Claude understands the request, asks the qualifying questions and explains the options;
   the engine draws and checks routes (the AI explains, the engine calculates, as in coaching).
5. **Planned rides other people can join**: distance, an honest pace band from real rides, date, start. This is
   the same object as a route, and matches people on the three things that keep him riding alone
   (distance, pace, availability).

## The route check (`rideengine/routes/`)

- `route.py`: `Route` (points with elevation, no times), `read_route()` from GPX tracks or routes,
  `from_samples()` for a ride's own track.
- `osm.py`: the OpenStreetMap roads and stops around the route, and how to read their tags.
  - **Surface classes**: paved, gravel, rough, trail, singletrack, unknown.
    - *Trail* is a path the map says nothing more about (a wide forest trail, or singletrack). We don't guess.
    - *Singletrack* needs evidence: mtb:scale, a narrow width, sac_scale, or a natural surface on a path.
    - Rail trails (fine gravel, or named "Rail Trail") are gravel.
    - Unclassified roads without a surface tag are *unknown*. In rural Ontario they're often gravel, but we
      don't guess.
    - "Assumed" km (classed from the kind of road) are reported separately.
  - **Busy roads**: trunk and primary roads, and secondary roads at 70 km/h or more.
  - **Stops**: cafés, bakeries, restaurants, shops, fuel stations, water, toilets, bike shops, viewpoints.
  - **Our own map first** (17 Nov 2026): `data/osm/map.sqlite3`, built from Geofabrik's Ontario extract (~1 GB
    .osm.pbf) by `python -m backend build-map data/osm/ontario-latest.osm.pbf` (`backend/mapdata.py`, pyosmium).
    - It keeps every road and trail with the tags the check reads, and the stops, indexed by ~4 km tile.
    - Reads are instant and offline. Rebuild from a fresh extract to update.
  - **Overpass** for routes outside it: the public API in tiles, cached under `data/osm-cache/tiles/`.
    - Only the map area is sent, nothing about the rider.
    - The public servers are often at capacity and ask automated users to run their own copy, which is why the
      local map comes first.
  - Credit "© OpenStreetMap contributors (ODbL)" wherever a report is shown.
- `check.py`: the report.
  - Every 20 m point is snapped to the nearest road heading the same way. Sidewalks are ignored, and footpaths
    beside a road lose to the road.
  - What it gives:
    - surfaces in km;
    - singletrack, trail, busy and straight stretches with their km;
    - stretches ridden twice;
    - climbs (same detection as rides);
    - stops grouped by village (GeoNames names), the halfway coffee stop, and the longest gap with nowhere to refuel;
    - how much of it he's ridden before (grid cells shared with his rides);
    - his time, from his own rides' flat speed scaled per surface, plus climbing;
    - a cue sheet (each change of road, with the turn and the surface);
    - verdict lines (good / warn / info).
- `course.py`: export.
  - A **FIT course** (CRC-checked): stops as food and water course points, climb tops as summits, singletrack
    starts as danger. The Edge 840 shows them in Up Ahead and uses the elevation for ClimbPro. Turns come from
    the Edge's own maps.
  - A **GPX** with the same points as waypoints.

Backend: `courses` table and `/v1/courses` (upload a GPX, check in the background, list, detail, rename, recheck,
delete, `course.fit` / `course.gpx`). App: the **Routes** tab (import a GPX, the route page with the map coloured
by surface, the profile with a surface strip, what to know, stops, climbs, cue sheet, Send to Edge).

## Tuning (built 17 Nov 2026)

On any checked route, in the app's **Tune it** card:
- **Shorter or longer** (−20 … +20 km):
  - Shorter takes a shortcut between two points on the route; longer takes a way round, out to the side.
  - Candidates are scored on hitting the asked-for length first, then the roads this rider likes, then not
    riding the same road twice.
  - Stops the rider added stay on the route.
- **Add a stop**: cafés, shops and water within 3 km of the route. The ones that fill the longest stretch with no
  food come first. The detour that adds least leaves and rejoins the route within 4 km either side.
- **Start elsewhere**: a café or town on the route, or any point tapped on the map.
  - A loop just begins there, or rides there and back to join it.
  - A point-to-point route joins at the nearest place.

Each change is a version (`course_versions`), checked straight away, listed in words ("10.6 km shorter: a
shortcut from km 63.4 to km 86.6 (88% off pavement)") and undoable one at a time. Version 0 is the file as it
came in.

Under it:
- `rideengine/routes/router.py`: our own bike router on the local map (A*, stdlib).
  - A road's cost is its length × the rider's preference (`Prefs`): gravel 0.8, paved 1.0, singletrack 5,
    busy ×3. A road rider (under 25% gravel) prefers tarmac.
  - Motorways, private roads, steps and sidewalks are left out, and one-way streets are respected.
- `rideengine/routes/elevation.py`: ground heights from the public Terrarium elevation tiles (AWS Open Data,
  ~27 m at zoom 12).
  - PNGs are decoded in stdlib and cached in `data/dem/`.
  - Tuned routes take all their heights from the tiles, for consistency. On Durham Forest the tiles are within
    ~5 m of the Garmin's barometric heights.
- `rideengine/routes/tune.py`: the operations (`move_start`, `add_stop`, `change_length`).
- API: `GET /v1/courses/{id}/options`, `POST /v1/courses/{id}/tune`, `POST /v1/courses/{id}/undo`.

## Known limits and next

- **Outside Ontario** the check falls back to the public Overpass servers (slow at busy times; it retries and
  can be run again). Add other regions' extracts to the local map when needed. The same extract feeds the
  routing engine in step 3.
- **Pace** is a first estimate: his recent flat-equivalent speed, scaled by fixed surface factors. Next, match his
  past rides to surfaces and learn his real gravel and road speeds.
- **One-tap sending to the Edge** needs Garmin's Courses API, part of the Connect Developer Program we're applying
  to for the Starter tier anyway. Until then: share the FIT file to Garmin Connect, or import it at
  connect.garmin.com.
- **"Boring"** is only long straights and stretches ridden twice so far. Scenery (water, forest, viewpoints along
  the way) comes next.
- **Opening in the app from Ride with GPS** (share → RideApp) needs document types in the app's Info.plist.


## Routes from a description (built 18 Nov 2026)

In the app's **Describe a ride** box on Routes (`POST /v1/courses/plan`):
- `request.py` reads the words, rule-based (engine first; Claude can take the free-form leftovers later, as in
  `docs/coaching.md` section 7):
  - distance ("60-70 km", "about 80k", miles);
  - surface: gravel (50–70% off pavement by default, his mix), mixed, road, or "40-60% gravel";
  - the start: an Ontario place name from GeoNames, or "from home" (his usual start, from his rides). Words that are
    also place names ("Halfway", "Gravel Hill") are skipped;
  - café halfway / a coffee stop, flat / hilly, singletrack wanted;
  - the shape, from the places' roles (the word before each: from/near/in = start, to = destination,
    via/through = a place to pass): **loop** ("loop", "via Goodwood", "to Port Perry and back a different way"),
    **one way** ("from Uxbridge to Port Perry"), **there and back** ("out and back to Port Perry", "40 km there and
    back", "to Port Perry and back").
  It shows what it understood as tags (LOOP · 60–70 KM · GRAVEL 50–70% · FROM UXBRIDGE · CAFÉ HALFWAY) and asks
  only for what's missing: start, where to (one way), distance (a loop with no place to pass, or a there-and-back
  with no destination), surface. "One way" / "point to point" say the shape on their own.
- **Addresses and places we don't know** (18 Nov 2026): a street address ("to 48 Sample Cres in Markham",
  "from 4321 Concession Rd 7, Uxbridge"), a business in a town ("the Port Perry bakery") or other words after "to"
  aren't in GeoNames or our map, so the request keeps them as a `guess` and asks "Where to?" pre-filled with them.
  The app looks them up in Apple Maps as you type (suggestions, biased to southern Ontario) and sends back the
  coordinates; typed words with no suggestion are looked up in Apple Maps, then our own place list.
- **Not much gravel near the start** (18 Nov 2026): a gravel or mixed loop from home in the city can't be one
  (within 20 km of Leaside under 5% of roads are unpaved; the best loop found was 8%). `gravelmap.py` keeps a
  coarse grid of road km by surface per map tile (built from our map in ~5 s, cached in
  `data/osm/gravel_grid.json`). Loops come out at about 3x the area's share (Leaside 1.5% -> 8%; Uxbridge 25% ->
  60-83%), so below a quarter of the share wanted it asks first: "Not much gravel near home", with up to three
  starts that have plenty (towns of 500+ or places he has ridden from, which count as 15 km closer; not across
  the lake), or "From home anyway".
- In the app the description stays editable (changing it drops what was understood; Find routes again), Start over
  clears it, Cancel stops a search, and the keyboard has Done (or drag the list down).
- `generate.py` makes the loops:
  - Each candidate: start → one side → a far point → the other side → back, routed with surface costs for the request
    (gravel cheap for a gravel ride; singletrack very dear unless asked for).
  - The far point is a café when one is wanted (local cafés over chains), else twelve directions. The side points sit
    on an ellipse sized to the distance, then nudged once by the length the router actually found. Points are moved
    onto the main road network (rural roads can be 2 km apart).
  - Scored on: the distance, the off-pavement share, busy roads, singletrack, trails the map doesn't describe,
    riding the same road twice, where the café falls; flat or hilly re-ranks the best dozen by climbing.
  - The best three that don't overlap each other much are kept.
  - **One way:** the best route, plus ones that bend out to one side to make up a longer distance (side points on an
    ellipse with the start and end as its foci), plus, for a café, one café per town about halfway.
  - **There and back:** to the destination and back the same way (the repeat isn't counted against it), a café to turn
    round at if asked, a variant out by other roads, and one "back a different way" option (a loop through it). With
    only a distance it picks the turn: a café or town at about half the distance, else twelve directions.
- Each loop is saved as a course (source "generated", with what was asked and why), checked like any route, and can
  be tuned and sent to the Edge. The best is at the top. About 10 s for three, including the checks.
- **Where to stop** (18 Nov 2026): the check used to list every café within reach (43 on a 60 km city loop) and
  put one in the cue sheet every 4 km and on the Edge every 2 km. Now `check.rest_stops` picks: by riding time
  none under 1:30 (but a good local café about halfway if there is one), one about halfway to 4:30, two to 7 h,
  then one every 3 h; the best place near each (local café or bakery, then chain café, takeaway, restaurant or
  pub, shop, water); the rider's own stops (the café asked for, stops added in tuning) always; the last food
  before a 35 km+ stretch with none; elsewhere only where nothing else is listed for 25 km (the countryside).
  These go in the verdict, cue sheet, Edge course points and map; the full list is one tap away in the app.
  `python -m backend recheck-courses --user 1` checks saved routes again after a change like this.
- Known limits: starts and ends at a town's centre (move the start with Tune → Start elsewhere); Ontario only (our
  map); scenery isn't scored yet; getting home from a one-way is up to the rider.

# Routes

Decided 17 Nov 2026. How Neelay plans rides today: he drives out for gravel (little near home) and for long road
rides, prefers routes that are 50–70% gravel, navigates with a Garmin Edge 840, and researches heavily before
committing. When a route goes wrong it's boring, has nowhere to refuel, or the off-road turns out to be endless
singletrack. So the job isn't drawing a line: it's **cutting the research** and giving him confidence before the day.

## The plan, in order (each step usable on its own)

1. **Route check** (built 17 Nov 2026). Bring in a GPX (Ride with GPS, Komoot, Garmin Connect), get the research
   in one page, send it to the Edge.
2. **Tuning**: move the start, add a coffee stop, shorten or lengthen by N km while keeping the gravel share.
3. **Generating loops** from a description ("60–70 km gravel loop near Uxbridge, café halfway"): a routing engine
   with surface preferences (GraphHopper custom models, or Valhalla) makes 20–30 candidates, the route check scores
   them, the best three are shown.
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

"""Tallies, personal bests and what's notable (rideengine.analysis.records). Synthetic rides only."""
from datetime import date, datetime, timezone

from rideengine.analysis import records
from rideengine.model import Ride, Sample

UTC = timezone.utc


def ride(day: str, km: float, up: float = 100, hours: float | None = None, indoor: bool = False,
         power: float | None = None) -> Ride:
    t = datetime.fromisoformat(day).replace(hour=9, tzinfo=UTC).timestamp()
    hours = hours if hours is not None else km / 25
    totals = {"distance_m": km * 1000, "ascent_m": up, "moving_s": hours * 3600}
    prov = {"total:distance_m": "garmin", "total:ascent_m": "garmin", "total:moving_s": "garmin"}
    if power:
        totals["avg_power"] = power
        prov["channel:power"] = "kickr"
    return Ride(start=t, end=t + hours * 3600, sport="cycling", indoor=indoor, samples=[Sample(t=t)],
                totals=totals, provenance=prov, recordings=["test"])


def weekly(n: int, start: str = "2026-03-02", km: float = 40, **kw) -> list[Ride]:
    """n rides, one each Monday."""
    d0 = date.fromisoformat(start)
    return [ride(date.fromordinal(d0.toordinal() + 7 * i).isoformat(), km, **kw) for i in range(n)]


def texts(rides, which: Ride) -> list[str]:
    return [n["text"] for n in records.notes_by_ride(rides, UTC)[records.ride_id(which)]]


def test_crow_flies():
    assert records.crow_flies(100) is None
    assert records.crow_flies(520) == "Toronto to Montreal"
    assert records.crow_flies(1100) == "Toronto to Montreal and back"
    assert records.crow_flies(3513) == "Toronto to Vancouver"
    assert records.crow_flies(80150) == "2.0 times around the Earth"


def test_tallies_streaks_and_bests():
    rides = weekly(7) + [ride("2025-06-01", 90, up=1500), ride("2026-04-20", 60, up=300, indoor=True)]
    y = records.you(rides, today=date(2026, 4, 22), tz=UTC)
    assert y["all"]["rides"] == 9 and y["all"]["km"] == 370  # the indoor ride's 60 km are trainer km: not counted
    # ... nor its 300 m of (virtual) climbing
    assert y["all"]["ascent_m"] == 2200 and y["all"]["everests"] == round(2200 / 8849, 2)
    assert y["year"]["rides"] == 8 and y["last_year"]["km"] == 90
    assert y["month"]["label"] == "April 2026" and y["month"]["rides"] == 3
    assert y["since"] == "2025-06-01"
    # Seven Mondays in a row (2 Mar to 13 Apr), then the ride on 20 Apr makes it eight.
    assert y["streak"] == {"longest_weeks": 8, "longest_from": "2026-03-02", "current_weeks": 8}
    best = {b["kind"]: b for b in y["bests"]}
    assert best["distance"]["value"] == 90 and best["distance"]["date"] == "2025-06-01"
    assert best["climbing"]["text"] == "1,500 m"
    # Speed bests leave out indoor rides; power only comes from measured power.
    assert best["speed"]["ride_id"] != records.ride_id(rides[-1])
    assert "power" not in best


def test_streak_ends_after_a_missed_week():
    es = records.entries(weekly(3), UTC)
    assert records.streaks(es, date(2026, 3, 30))["current_weeks"] == 0
    assert records.streaks(es, date(2026, 3, 22))["current_weeks"] == 3


def test_longest_yet_and_first_100():
    rides = weekly(6) + [ride("2026-04-15", 101)]
    t = texts(rides, rides[-1])
    assert "Your longest ride yet" in t and "Your first 100 km ride" in t
    top = records.notes_by_ride(rides, UTC)[records.ride_id(rides[-1])][0]
    assert top["pb"] and top["detail"] == "101.0 km"
    assert records.headline([top]) == "Your longest ride yet."
    # Time in the saddle repeats distance, so it isn't said as well.
    assert not any("by time" in x for x in t)


def test_too_little_history_says_nothing_about_bests():
    rides = weekly(3) + [ride("2026-03-25", 80)]
    assert not any("ride yet" in x for x in texts(rides, rides[-1]))


def test_year_rank_and_since():
    last_year = [ride("2025-06-01", 95)]
    this_year = weekly(12, km=30) + [ride("2026-05-20", 70), ride("2026-05-27", 60)]
    rides = last_year + this_year
    assert "Your longest ride of 2026 so far" in texts(rides, rides[-2])
    assert "Your 2nd longest ride of 2026 so far" in texts(rides, rides[-1])
    # 70 km in May was the longest since June 2025.
    long_ago = last_year + weekly(4, km=30) + [ride("2026-04-20", 70)]
    assert "Your longest ride since June 2025" in texts(long_ago, long_ago[-1])


def test_notes_stay_as_they_were_when_later_rides_arrive():
    rides = weekly(6) + [ride("2026-04-15", 101)]
    before = texts(rides, rides[-1])
    assert texts(rides + [ride("2026-05-01", 150)], rides[-1]) == before


def test_milestones():
    rides = weekly(12, km=45)  # 540 km, 12 rides
    t = [texts(rides, r) for r in rides]
    passed = [i for i, x in enumerate(t) if "Took 2026 past 500 km" in x]
    assert passed == [11]
    fiftieth = weekly(50, start="2025-03-03", km=20)
    assert "Your 50th ride on record" in texts(fiftieth, fiftieth[-1])
    climbs = weekly(9, up=1000)
    assert "A full Everest of climbing in 2026" in texts(climbs, climbs[-1])


def test_streak_notes():
    rides = weekly(6)
    assert "4 weeks in a row with a ride: your longest streak yet" in texts(rides, rides[3])
    # Not every week: 5 isn't a round number and isn't a new record when the old one was longer.
    older = weekly(8, start="2025-03-03") + weekly(5)
    assert not any("weeks in a row" in x for x in texts(older, older[-1]))
    assert "4 weeks in a row with a ride" in texts(older, older[-2])


def test_a_tie_is_not_a_best():
    rides = weekly(12, km=45)
    assert not any("so far" in x for x in texts(rides, rides[-1]))


def test_at_most_four_notes():
    rides = weekly(49, start="2025-03-03", km=20) + [ride("2026-03-02", 210, up=3100, hours=9)]
    assert len(texts(rides, rides[-1])) == records.MAX_NOTES


def test_report_runs():
    out = records.report(records.you(weekly(8) + [ride("2026-05-01", 101)], today=date(2026, 5, 2), tz=UTC))
    assert "Personal bests:" in out and "101.0 km" in out


def test_milestones_for_tallies_that_only_go_up():
    rides = weekly(12, km=50, up=800, hours=2.5)          # 600 km, 30 h, 9,600 m, 12 rides
    ms = {m["kind"]: m for m in records.milestones(records.entries(rides, UTC))}
    h = ms["hours"]
    assert [e["value"] for e in h["earned"]] == [10, 25] and h["next"]["value"] == 50
    assert h["next"]["to_go"] == 20 and h["next"]["progress"] == 0.2
    assert h["earned"][1]["ride_id"] == records.ride_id(rides[9])    # 25 h reached on the 10th ride
    assert [e["value"] for e in ms["km"]["earned"]] == [100, 500] and ms["rides"]["next"]["value"] == 25
    assert ms["everests"]["earned"][0]["text"] == "1 Everest" and ms["everests"]["next"]["text"] == "2 Everests"
    assert "milestones" in records.you(rides, date(2026, 6, 1), UTC)

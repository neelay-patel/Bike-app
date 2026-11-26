"""Steady reps against their targets: where they fell short and one thing for next time (rideengine/analysis/
pacing.py). Synthetic power, shaped like Neelay's sweet spot of 26 Nov 2026 (2 × 11 min at 140–149 W asked)."""
from rideengine.analysis import pacing, train
from rideengine.analysis import plan as p

TARGET = [140, 149]


def stream(minutes, cad=89):
    """[(minutes, watts)] -> the 10-second power and cadence streams."""
    p30, c30 = [], []
    for m, w in minutes:
        for _ in range(round(m * 6)):
            p30.append(w)
            c30.append(cad if w > 0 else 0)
    return p30, c30


def ride(rep1, rep2, cad=89):
    """Warm-up 10 min, rep 1 (11 one-minute values), 5 min easy, rep 2, 8 min easy."""
    parts = [(10, 90)] + [(1, w) for w in rep1] + [(5, 100)] + [(1, w) for w in rep2] + [(8, 95)]
    return stream(parts, cad)


SESSION = p.targets(p.workout("steady", 0.0, 50, True), 159, None)
ON = {**next(st for st in SESSION["steps"] if st.get("repeat"))["steps"][0], "seconds": 660}


def test_the_reps_are_found_and_the_shortfall_placed():
    # Neelay's ride, minute by minute: rep 1 dipped twice, rep 2 held the range.
    p30, c30 = ride([145, 128, 137, 137, 140, 129, 136, 142, 146, 143, 137],
                    [136, 143, 143, 142, 145, 150, 146, 142, 141, 146, 143])
    rd = pacing.read({**ON, "target": {"watts": TARGET}}, 2, p30, c30)
    assert [s for s, _ in rd["spans"]] == [60, 156]                  # 10 min in, and after the 5 min easy
    r1, r2 = rd["reps"]
    assert r1["watts"] == 138 and r1["pattern"] == "dipped" and r1["dips"][0] == {"watts": 128, "minute": 2}
    assert r2["pattern"] == "on"
    assert rd["lines"][0] == "Rep 1: 138 W, 6 of 11 min under 140 W. It dipped to 128 W in its 2nd minute and 129 W in its 6th minute."
    assert rd["lines"][1] == "Rep 2: 143 W, inside the 140–149 W."
    assert rd["lines"][2].startswith("Cadence held 89 rpm, so it wasn't the gears")
    tip = pacing.next_time(rd, indoor=True, feel="easy")
    assert tip["id"] == "pacing_even" and tip["title"] == "Hold 145 W, minute by minute"
    assert tip["text"].startswith("Rep 1: the watts eased off in minute 2 (128 W) and minute 6 (129 W), under 140 W.")
    assert "ERG to 145 W" in tip["text"]
    assert "KICKR" not in pacing.next_time(rd, indoor=False)["text"]  # outdoors, no trainer advice
    # Both reps dipped: the worse is named, and its dips are its own.
    p30, c30 = ride([145, 128, 137, 137, 140, 129, 136, 142, 146, 143, 137],
                    [136, 135, 143, 142, 145, 150, 146, 142, 141, 146, 143])
    rd = pacing.read({**ON, "target": {"watts": TARGET}}, 2, p30, c30)
    assert pacing.next_time(rd, indoor=True)["text"].startswith(
        "Rep 1 most (rep 2 too, less so): the watts eased off in minute 2 (128 W)")


def test_each_way_of_falling_short():
    def tip(rep1, rep2, cad=89):
        p30, c30 = ride(rep1, rep2, cad)
        rd = pacing.read({**ON, "target": {"watts": TARGET}}, 2, p30, c30)
        return rd, pacing.next_time(rd, indoor=True, feel="easy")

    rd, t = tip([132] * 11, [131] * 11)
    assert [r["pattern"] for r in rd["reps"]] == ["under", "under"] and t["id"] == "pacing_under"
    assert t["text"].startswith("Every rep was under: 132 and 131 W against 140–149 W. It felt easy")
    rd, t = tip([150, 148, 147, 146, 144, 140, 136, 132, 130, 128, 126], [144] * 11)
    assert rd["reps"][0]["pattern"] == "faded" and t["id"] == "pacing_fade" and "Start the rep at the bottom of the range, 140 W" in t["text"]
    rd, t = tip([125, 128, 131, 134, 144, 145, 146, 145, 146, 144, 145], [144] * 11)
    assert rd["reps"][0]["pattern"] == "started_low" and t["id"] == "pacing_start"
    rd, t = tip([144] * 11, [145] * 11)
    assert t is None and all(r["pattern"] == "on" for r in rd["reps"])
    # The cadence went down with the watts: shift down.
    p30, c30 = ride([145, 128, 129, 130, 144, 145, 130, 128, 144, 145, 144], [144] * 11)
    c30 = [76 if 130 > w > 0 and 60 <= i < 126 else c for i, (w, c) in enumerate(zip(p30, c30))]
    rd = pacing.read({**ON, "target": {"watts": TARGET}}, 2, p30, c30)
    assert rd["lines"][-1] == "Your cadence went down with the watts: 81 rpm in the minutes under, 89 rpm on the target."
    assert pacing.next_time(rd, indoor=False)["id"] == "pacing_cadence"


def test_against_reads_steady_sets():
    p30, c30 = ride([145, 128, 137, 137, 140, 129, 136, 142, 146, 143, 137],
                    [136, 143, 143, 142, 145, 150, 146, 142, 141, 146, 143])
    session = {**SESSION, "steps": [st if not st.get("repeat") else
                                    {**st, "repeat": 2, "steps": [{**st["steps"][0], "seconds": 660,
                                                                   "target": {"watts": TARGET}}, st["steps"][1]]}
                                    for st in SESSION["steps"]]}
    a = train.against(session, {"basis": "power", "p30": p30, "c30": c30, "sets": []}, indoor=True, feel="easy")
    row = a["sets"][0]
    assert row["done"] == 2 and row["power"] == 140 and row["verdict"] == "below" and row["watts"] == [138, 143]
    assert a["lines"][0] == "2 × 11 min steady: all 2, 140 W on average; 1 of 2 under the 140–149 W planned."
    assert a["summary"] == "Every set done, some under the targets."
    assert a["lines"][1].startswith("Rep 1: 138 W") and a["next_time"]["id"] == "pacing_even"
    # Not ridden at all: the set is missing, as before.
    flat = stream([(50, 100)])
    assert train.against(session, {"basis": "power", "p30": flat[0], "c30": flat[1], "sets": []})["sets"][0]["verdict"] == "missing"

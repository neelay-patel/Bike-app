"""Efforts: false starts folded in, and a session split into phases (synthetic, no personal data)."""
import random

from rideengine.analysis import effort
from rideengine.clean import hidden_reasons
from rideengine.model import Ride, Sample

T0 = 1_795_000_000.0


def trainer(start, parts, seed=1):
    """An indoor ride from [(seconds, watts, rpm, noise_w)], one sample a second, heart rate following power."""
    rnd = random.Random(seed)
    samples, t, hr = [], start, 95.0
    for secs, watts, rpm, noise in parts:
        for _ in range(secs):
            w = max(0.0, watts + rnd.uniform(-noise, noise)) if watts else 0.0
            hr += ((90 + 0.42 * w) - hr) / 40            # heart rate drifts towards a level set by power
            samples.append(Sample(t=t, power=w, cadence=rpm if watts else 0, hr=round(hr), speed=rpm * 0.41 / 3.6))
            t += 1
    return Ride(start=start, end=t - 1, sport="cycling", indoor=True, samples=samples, totals={},
                provenance={"channel:power": "apple_watch", "channel:hr": "apple_watch"}, recordings=["test"])


def session(start=T0):
    """Today's shape: warm-up, a workout of steady blocks, a breather, own riding with two climbs, cool-down."""
    parts = [(6 * 60, 80, 78, 25)]
    for _ in range(5):
        parts += [(3 * 60, 130, 89, 1.5), (2 * 60, 85, 87, 1.5)]
    parts += [(40, 0, 0, 0)]
    for _ in range(2):
        parts += [(6 * 60, 140, 86, 25), (2 * 60, 140, 62, 25), (4 * 60, 140, 85, 25)]
    parts += [(4 * 60, 70, 75, 10)]
    return trainer(start, parts)


def test_short_trainer_sessions_before_the_real_one_are_false_starts():
    stub1 = trainer(T0 - 420, [(110, 40, 30, 10)])
    stub2 = trainer(T0 - 280, [(130, 55, 35, 10)])
    real = session(T0)
    rides = [stub1, stub2, real]
    assert hidden_reasons(rides) == {0: "false_start", 1: "false_start"}
    groups = effort.group(rides)
    assert len(groups) == 1 and groups[0]["main"] == 2 and sorted(groups[0]["folded"]) == [0, 1]
    # A short trainer session on its own is a real (short) one.
    assert hidden_reasons([trainer(T0, [(200, 120, 85, 10)])]) == {}


def test_phases_of_a_workout_then_own_riding():
    p = effort.phases(session())
    kinds = [f["kind"] for f in p["phases"]]
    assert kinds[0] == "warm_up" and "structured" in kinds and kinds[-1] == "cool_down"
    work = next(f for f in p["phases"] if f["kind"] == "structured")
    assert 22 <= work["minutes"] <= 27
    hard = [b for b in work["blocks"] if b["power"] > 110]
    assert len(hard) == 5 and all(abs(b["power"] - 130) <= 2 for b in hard)
    riding = [f for f in p["phases"] if f["kind"] == "riding"]
    assert riding and sum(f["minutes"] for f in riding) >= 20
    # The two climbs: same watts, cadence down (more force on the pedals).
    assert len(p["pushes"]) == 2 and all(x["cadence"] < 75 for x in p["pushes"])
    text = " ".join(p["lines"])
    assert "structured workout" in text and "5 work blocks" in text and "own riding" in text
    assert "likely the climbs" in text and "power held" in text


def test_heart_rate_only_ride_has_no_structured_blocks():
    r = session()
    for s in r.samples:
        s.power = None
    r.provenance = {"channel:hr": "apple_watch"}
    p = effort.phases(r)
    assert p["basis"] == "heart_rate" and all(f["kind"] != "structured" for f in p["phases"])
    assert p["lines"] and not p["pushes"]

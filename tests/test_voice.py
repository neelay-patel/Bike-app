"""Train step 5: the coach's voice. "Why it works" lines vary and each has its research; praise is specific and
earned, from the ride's own numbers, and never contradicts the ride's one thing to try."""
import os
import re

from rideengine.analysis import train, voice
from test_effort import T0, trainer
from test_train import FTP, surges_as_planned, warm

DOCS = os.path.join(os.path.dirname(__file__), "..", "docs", "training-science.md")


def test_every_line_has_its_research_and_varies_day_to_day():
    science = open(DOCS).read()
    for job, lines in voice.LEARN.items():
        for key, text in lines:
            assert f"`{key}`" in science, key                      # each line's research is written down
            assert not re.search(r"\b(FTP|TSS|zone \d|Z\d)\b", text)  # plain words
        if len(lines) > 1:
            assert voice.learn(job, 10)["text"] != voice.learn(job, 11)["text"]
    assert voice.learn(None, 1) is None


def test_praise_names_the_thing_and_why():
    w = train.work(surges_as_planned())
    j = train.jobs_done(w, FTP, 180, 50, want={"punch": 7.5})
    d = voice.done_well(w, j, None, FTP, "surges", 58)
    assert d and d["key"] == "paced-set" and "as strong as your first" in d["text"]
    # The ride's one thing to try asked to start the efforts easier: then pacing isn't praised.
    d = voice.done_well(w, j, None, FTP, "surges", 58, tips=[{"id": "pacing"}])
    assert d is None or d["key"] != "paced-set"


def test_easy_kept_easy_and_nothing_to_say():
    w = train.work(trainer(T0, [(45 * 60, 85, 88, 8)]))
    j = train.jobs_done(w, FTP, 180, 50)
    assert voice.done_well(w, j, None, FTP, "easy", 45)["key"] == "kept-easy"
    assert voice.done_well(w, j, None, FTP, "easy", 45, tips=[{"id": "easy_too_hard"}]) is None
    # A middling ride with nothing specific done well: no praise at all, never "Great job!".
    parts = warm() + [(30 * 60, 125, 70, 30)]
    w = train.work(trainer(T0, parts))
    assert voice.done_well(w, train.jobs_done(w, FTP, 180, 50), None, FTP, "mixed", 40) is None


def test_no_praise_from_a_rough_heart_rate_read():
    from test_train import hr_ride
    w = train.work(hr_ride(60, 165))
    j = train.jobs_done(w, FTP, 180, 50)
    assert j["jobs"][0]["status"] == "more" and voice.done_well(w, j, None, FTP, "threshold", 60) is None

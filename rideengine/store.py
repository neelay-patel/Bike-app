"""Tiny file store: every imported recording is kept, and rides are rebuilt from all of
them, so a ride recorded on two devices merges no matter which file arrives first.

Layout (under data/, which git ignores):
  data/store/recordings/<source>_<start>.json
  data/store/rides/<start>.json
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import asdict

from .merge import build_rides
from .model import Recording, Ride, Sample


class Store:
    def __init__(self, root: str = "data/store"):
        self.rec_dir = os.path.join(root, "recordings")
        self.ride_dir = os.path.join(root, "rides")
        os.makedirs(self.rec_dir, exist_ok=True)
        os.makedirs(self.ride_dir, exist_ok=True)

    def add(self, recs: list[Recording]) -> int:
        n = 0
        for r in recs:
            path = os.path.join(self.rec_dir, f"{r.source}_{int(r.start)}.json")
            if not os.path.exists(path):
                n += 1
            with open(path, "w") as f:
                json.dump(asdict(r), f)
        return n

    def recordings(self) -> list[Recording]:
        out = []
        for p in sorted(glob.glob(os.path.join(self.rec_dir, "*.json"))):
            d = json.load(open(p))
            d["samples"] = [Sample(**s) for s in d["samples"]]
            d["after"] = [Sample(**s) for s in d.get("after") or []]
            out.append(Recording(**d))
        return out

    def rebuild(self) -> list[Ride]:
        rides = build_rides(self.recordings())
        for p in glob.glob(os.path.join(self.ride_dir, "*.json")):
            os.remove(p)
        for r in rides:
            with open(os.path.join(self.ride_dir, f"{int(r.start)}.json"), "w") as f:
                f.write(r.to_json())
        return rides

    def rides(self) -> list[Ride]:
        return [Ride.from_json(open(p).read()) for p in sorted(glob.glob(os.path.join(self.ride_dir, "*.json")))]

    def ride(self, ride_id: str) -> Ride:
        return Ride.from_json(open(os.path.join(self.ride_dir, f"{ride_id}.json")).read())

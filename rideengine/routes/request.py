"""What the rider asked for, read from their words: rule-based for now (engine first; Claude can read the
free-form leftovers later, docs/coaching.md section 7).

    read("60-70km gravel loop near Uxbridge, cafe halfway")
    -> Ask(km=(60, 70), surface="gravel", start=Uxbridge, stop="midway", ...), with `missing` naming what
       we still need to ask ("start", "end", "km", "surface") and `tags` saying what we understood.

Three shapes: a loop ("loop", "via Goodwood", "to Port Perry and back a different way"), one way ("from
Uxbridge to Port Perry"), and there and back ("out and back to Port Perry", "30 km there and back").
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .. import places as places_mod

# Surface wanted: share of the known roads that are off pavement (gravel, rough, trail).
SURFACES = {"gravel": (0.5, 0.7), "mixed": (0.25, 0.55), "road": (0.0, 0.15)}
# Words in ride requests that are also Ontario place names ("Halfway", "Gravel Hill"...).
NOT_PLACES = {"halfway", "midway", "gravel", "loop", "road", "lake", "forest", "coffee", "cafe", "hills", "hilly",
              "flat", "long", "short", "centre", "center", "north", "south", "east", "west", "home", "park"}


@dataclass
class Ask:
    km: tuple[float, float] | None = None
    surface: str | None = None                  # gravel | mixed | road
    gravel: tuple[float, float] | None = None   # off-pavement share wanted
    start: dict | None = None                   # {"name", "lat", "lon"}
    shape: str = "loop"                         # loop | oneway | out_back
    end: dict | None = None                     # where a one-way ends, or where a there-and-back turns round
    via: dict | None = None                     # a place a loop goes through
    stop: str | None = None                     # "midway" | "any" | None
    hills: str | None = None                    # "flat" | "hilly" | None
    singletrack: bool = False                   # wanted? (no by default)
    stay: bool = False                          # start here even with little gravel around (the rider said so)
    guess: dict = field(default_factory=dict)   # {"end": "48 Sample Cres, Markham"}: words we couldn't place
                                                # ourselves (a street address); the app looks them up (Apple Maps)
    text: str = ""
    missing: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Ask":
        a = Ask(**{k: v for k, v in d.items() if k in Ask.__dataclass_fields__})
        a.km = tuple(a.km) if a.km else None
        a.gravel = tuple(a.gravel) if a.gravel else (SURFACES.get(a.surface) if a.surface else None)
        a.refresh()
        return a

    def refresh(self) -> "Ask":
        """Recompute what's missing and the tags (after the rider answers a question)."""
        need = [("start", self.start)]
        if self.shape == "oneway":
            need.append(("end", self.end))
        elif self.shape == "out_back":
            need.append(("km", self.km or self.end))
        else:
            need.append(("km", self.km or self.via or self.guess.get("via")))
        need.append(("surface", self.surface))
        for role in ("via", "end", "start"):        # words we couldn't place: ask where exactly
            if self.guess.get(role) and getattr(self, role) is None:
                need.insert(0, (role, None))
        self.missing = list(dict.fromkeys(k for k, v in need if not v))
        tags = [{"loop": "LOOP", "oneway": "ONE WAY", "out_back": "THERE AND BACK"}[self.shape]]
        if self.km:
            lo, hi = self.km
            tags.append(f"{lo:.0f} KM" if lo == hi else f"{lo:.0f}–{hi:.0f} KM")
        if self.surface:
            g = self.gravel or SURFACES[self.surface]
            tags.append(self.surface.upper() + (f" {g[0] * 100:.0f}–{g[1] * 100:.0f}%" if self.surface != "road" else ""))
        if self.start:
            tags.append(f"FROM {self.start['name'].upper()}")
        elif self.guess.get("start"):
            tags.append(f"FROM {self.guess['start'].upper()}?")
        if self.end:
            tags.append(f"TO {self.end['name'].upper()}")
        elif self.guess.get("end"):
            tags.append(f"TO {self.guess['end'].upper()}?")
        if self.via:
            tags.append(f"VIA {self.via['name'].upper()}")
        if self.stop:
            tags.append("CAFÉ HALFWAY" if self.stop == "midway" else "CAFÉ STOP")
        if self.hills:
            tags.append(self.hills.upper())
        self.tags = tags
        return self


def _km(text: str):
    t = text.lower().replace("–", "-").replace("—", "-")
    unit = r"\s*(km|kms|k|kilomet(?:er|re)s?|mi|miles?)\b"
    m = re.search(r"(\d{1,3})\s*(?:-|to)\s*(\d{1,3})" + unit, t)
    if m:
        lo, hi, u = float(m.group(1)), float(m.group(2)), m.group(3)
    else:
        m = re.search(r"(?:about|around|~)?\s*(\d{1,3})" + unit, t)
        if not m:
            return None
        v, u = float(m.group(1)), m.group(2)
        lo, hi = v * 0.92, v * 1.08
    if u.startswith("mi"):
        lo, hi = lo * 1.609, hi * 1.609
    return (round(min(lo, hi)), round(max(lo, hi)))


def read(text: str, home: dict | None = None, find=places_mod.find) -> Ask:
    """The rider's words to an Ask. `home`: {"name": "home", "lat", "lon"} for "from home"."""
    a = Ask(text=text.strip())
    low = text.lower()
    a.km = _km(text)
    pct = re.search(r"(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})\s*%\s*(gravel|off[- ]road|unpaved)", low)
    if pct:
        a.surface, a.gravel = "gravel", (int(pct.group(1)) / 100, int(pct.group(2)) / 100)
    elif re.search(r"\bmixed\b|\bsome gravel\b|\bbit of gravel\b", low):
        a.surface = "mixed"
    elif re.search(r"\bgravel\b|\bunpaved\b|\bdirt\b|\boff[- ]road\b|\bgrav\b", low):
        a.surface = "gravel"
    elif re.search(r"\broad (ride|bike|loop|route)\b|\bpaved\b|\btarmac\b|\bon the roads?\b|^road\b|,\s*road\b|\broad\s*$", low):
        a.surface = "road"
    if a.surface and not a.gravel:
        a.gravel = SURFACES[a.surface]
    if re.search(r"(caf[eé]|coffee|bakery|lunch|food stop|refuel)\w*\s+(stop\s+)?(half ?way|mid ?way|in the middle)"
                 r"|(half ?way|mid ?way)\s+(caf[eé]|coffee|bakery|lunch)", low):
        a.stop = "midway"
    elif re.search(r"caf[eé]|coffee|bakery|lunch stop|food stop", low):
        a.stop = "any"
    if re.search(r"\bflat\b|\bno (big )?hills\b|\beasy\b", low):
        a.hills = "flat"
    elif re.search(r"\bhilly\b|\bclimb(s|ing)?\b|\bhills\b", low):
        a.hills = "hilly"
    if re.search(r"\bsingle ?track\b", low) and not re.search(r"\bno single ?track\b", low):
        a.singletrack = True
    _places_and_shape(a, text, home, find)
    return a.refresh()


ROLE_WORDS = {
    "start": ("from", "near", "around", "in", "at", "starting", "start", "leaving", "out of"),
    "end": ("to", "towards", "toward", "into", "ending", "finish", "finishing"),
    "via": ("via", "through", "past", "by way of"),
}


def _role(before: str) -> str | None:
    words = [w for w in before.strip().split() if w not in ("the", "a")] or [""]
    for n in (3, 2, 1):
        tail = " ".join(words[-n:]) if len(words) >= n else None
        if not tail:
            continue
        for role, ws in ROLE_WORDS.items():
            if tail in ws:
                return role
    return None


STREET = (r"street|st|road|rd|avenue|ave|crescent|cres|cr|drive|dr|court|ct|boulevard|blvd|lane|ln|way|place|pl|"
          r"trail|trl|circle|cir|line|sideroad|side road|concession|terrace|terr|gate|grove|parkway|pkwy|square|sq|"
          r"highway|hwy|heights|hts|crossing|row|path|mews|close|common|green|hill|park")
# "48 Sample Cres in Markham", "4321 Concession Rd 7, Uxbridge": a number, words, a street type, then
# perhaps a number ("Concession Rd 7") and the town it's in.
ADDRESS = re.compile(r"\b(\d{1,6}[a-z]?)\s+(?!(?:km|kms|k|mi|miles?|kilomet\w*|minutes?|mins?|hours?|hrs?|percent)\b)"
                     r"((?:(?!(?:in|to|from|and|with|via|near|then|for)\b)(?:[a-z]{1,3}\.|[a-z][\w'-]*)\s+){0,4}(?:" + STREET + r"))\b\.?(\s+\d{1,3}\b)?"
                     r"(?:\s*(?:,|\bin\b)\s*([a-z][\w'-]*(?:\s+[a-z][\w'-]*){0,2}?)(?=\s*(?:[.,;]|$|\b(?:with|via|and|then|for|road|gravel|on|to|from)\b)))?",
                     re.I)


BUSINESS = re.compile(r"\s+(?:'s\s+)?(bakery|caf[eé]|coffee|brewery|brewing|restaurant|diner|pub|store|shop|market|farm|"
                      r"general store|cycles|bikes?|bike shop|conservation area|provincial park|station|plaza|mall)\b")


def _addresses(text: str) -> list[tuple[int, int, str]]:
    """(start, end, "48 Sample Cres, Markham") for each street address in the text."""
    out = []
    for m in ADDRESS.finditer(text):
        words = (m.group(1) + " " + m.group(2) + (m.group(3) or "")).strip()
        town = (m.group(4) or "").strip()
        out.append((m.start(), m.end(), words + (", " + town if town else "")))
    return out


def _places_and_shape(a: Ask, text: str, home: dict | None, find) -> None:
    """Who is the start, the destination, the place to pass; and so the shape."""
    low = " " + re.sub(r"[^a-z0-9' -]", " ", text.lower()) + " "
    found = []          # (position, role, place)
    addresses = _addresses(text)
    for s0, s1, words in addresses:     # an address isn't one of our places: the app looks it up
        found.append((s0 + 1, _role(low[:s0 + 1]) or "end", {"address": words}))
    for p in find(text):
        if p["name"].lower() in NOT_PLACES:
            continue
        m = re.search(r"\b" + re.escape(p["name"].lower()) + r"\b", low)
        if not m or any(s0 <= m.start() - 1 < s1 for s0, s1, _ in addresses):   # "in Markham" of an address
            continue
        biz = BUSINESS.match(text.lower(), m.end() - 1)   # "the Pine Valley bakery": somewhere in Pine Valley
        if biz:
            found.append((m.start(), _role(low[:m.start()]), {"address": text[m.start() - 1:biz.end()].strip()}))
            continue
        found.append((m.start(), _role(low[:m.start()]), {"name": p["name"], "lat": p["lat"], "lon": p["lon"]}))
    if home:
        for m in re.finditer(r"\b(home|my (house|place)|the doorstep)\b", low):
            found.append((m.start(), _role(low[:m.start()]) or "start", dict(home)))
    found.sort(key=lambda f: f[0])
    for _, role, place in found:
        role = role or ("start" if a.start is None and not a.guess.get("start") else
                        "end" if a.end is None and not a.guess.get("end") else None)
        if role not in ("start", "end", "via") or getattr(a, role) is not None or a.guess.get(role):
            continue
        if "address" in place:
            a.guess[role] = place["address"]
        elif role != "end" or place != a.start:
            setattr(a, role, place)
    # Where to, in words we don't know ("to the Pine Valley bakery"): the app can look it up.
    low = text.lower()
    if a.end is None and not a.guess.get("end"):
        m = re.search(r"\b(?:to|towards)\s+(?!\d+\s*(?:km|k|mi|miles?|%)\b)(?!home\b|the doorstep\b)"
                      r"([a-z0-9][\w' &-]*?)\s*(?=[.,;]|$|\b(?:and back|and|with|via|then|on|for|from|road|gravel)\b)", low)
        if m and not re.fullmatch(r"\d+(\s*-\s*\d+)?", m.group(1)) and m.group(1) not in NOT_PLACES:
            a.guess["end"] = text[m.start(1):m.end(1)].strip()
    # Shape.
    has_end = bool(a.end or a.guess.get("end"))
    if re.search(r"different way back|back (a|another) (different )?way|back by (a )?different", low):
        a.shape = "loop"
        if a.end and not a.via:
            a.via, a.end = a.end, None
        if a.guess.get("end"):
            a.guess["via"] = a.guess.pop("end")
    elif re.search(r"out[- ]and[- ]back|there[- ]and[- ]back|same way back|\band back\b|turn(ing)? (a)?round", low):
        a.shape = "out_back"
    elif re.search(r"\bone[- ]?way\b|\bpoint[- ]to[- ]point\b|\bcommute\b", low) or (has_end and not re.search(r"\bloop\b", low)):
        a.shape = "oneway"
    elif a.end:        # "a loop to Port Perry": through it
        a.via, a.end = a.end, None
    elif a.guess.get("end"):
        a.guess["via"] = a.guess.pop("end")
    if a.end and a.start and a.end == a.start:
        a.end = None
    if len(found) > 3:
        a.notes.append("Heard several places; using " + ", ".join(
            x for x in (a.start and f"from {a.start['name']}", a.end and f"to {a.end['name']}",
                        a.via and f"via {a.via['name']}") if x) + ".")


QUESTIONS = {
    "start": {"q": "Where do you want to start?", "hint": "A town, or a café to park at"},
    "end": {"q": "Where to?", "hint": "A town, café or address"},
    "via": {"q": "Through where?", "hint": "A town or a café"},
    "km": {"q": "How far?", "choices": [[40, 50], [60, 70], [80, 90], [100, 120]]},
    "surface": {"q": "What kind of roads?", "choices": ["gravel", "mixed", "road"]},
}

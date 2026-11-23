"""The AI coach (docs/train-tab.md, step 5): words on top of the engine.

The engine calculates; the AI only writes. For each ride the backend builds a facts packet (what kind of training
it was, what it counted as, the numbers, new bests, the goal and its numbers, the last two weeks of riding, how it
felt, what's next). Claude writes a headline and a short story in the fixed format of docs/train-words.md. Then:

- the **number check**: every number in the reply must appear in the facts packet, or the reply is thrown away and
  the engine's own words stay;
- results are **saved by the hash of their inputs** and only redone when the facts change;
- each call's tokens and cost go in a **cost log**;
- the **policy gate**: only riders with the personal-use setting on (`python -m backend ai --user N on`) ever have
  data sent to an AI service. The packet never holds GPS, place names, or recovery data (HRV, resting heart rate);
- the rule-based words are always the fallback: no key, the setting off, a slow or failed call, a refusal, a
  rejected reply.

The key is read from ANTHROPIC_API_KEY or ~/.config/kova/anthropic_api_key (never in the repo or the logs).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Optional

log = logging.getLogger("uvicorn.error")

MODEL = "claude-opus-5-5"
PRICE_PER_MTOK = {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00}   # Claude Opus 5.5
KEY_FILE = os.path.expanduser(os.environ.get("KOVA_ANTHROPIC_KEY_FILE", "~/.config/kova/anthropic_api_key"))
PROMPT_VERSION = 3           # bump when the instructions change, so saved stories are written again

SYSTEM = """You are the coach in Kova, a cycling app. You write the short words on a rider's ride note. The app's
engine has already worked everything out; you turn its facts into words the rider reads right the first time.

Write two things:
- headline: at most 7 words. What this ride was, for this rider. Specific, never hype.
- story: one to three short sentences, about 40 words in all, for the card labelled WHAT IT MEANS: the link
  between this ride and the rider's goal, said honestly (moved, held or dropped). Praise only what's earned, and name it. If something isn't
  moving yet, say when we'll be able to tell, only if the facts say so.

Rules (Kova's words guide):
- Use only numbers that appear in the facts, written the same way. Never calculate new numbers (no differences,
  percentages, totals or averages of your own). It is fine to use no numbers at all.
- Plain words. Never: FTP, TSS, CTL, zones by number, ERG, "load", "compliance", "matched". Say "what you could hold
  for about an hour", "your best hard minute", "easy", "hard".
- Never empty praise ("Great job!", "Crushed it", "Beast mode"). Never guilt about missed sessions.
- Speak to the rider as "you". Use "I" only for a decision the coach made.
- Indoors or out is the rider's choice: never suggest one is better.
- Don't give medical advice. Don't mention recovery numbers.
- If the rider said how the ride felt, take it into account; when the facts say what changed because of it (the
  targets going up after a hard session felt easy), say so in a few words.
- Praise only what the facts' done_well names, in your own words (its numbers as written); if done_well is empty,
  praise nothing. Never a comparison that shames.
- Don't repeat the "one thing to try" or "what's next": the card shows those separately. But stay consistent
  with the one thing to try: never praise what it asks the rider to change (an easy day ridden hard is not "good
  steady work").
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "At most 7 words."},
        "story": {"type": "string", "description": "One to three short sentences for WHAT IT MEANS."},
    },
    "required": ["headline", "story"],
    "additionalProperties": False,
}

REVIEW_SYSTEM = """You are the coach in Kova, a cycling app. You write the Sunday review of a rider's week. The app's
engine has already worked everything out: how the week went, and the changes it proposes for next week, each made by
a fixed rule and checked against the plan's limits. You put it into words the rider reads right the first time.

Write two things:
- summary: two to four short sentences, about 60 words: how the week went, honestly, and what it means for the goal.
  Praise only what's earned, and name it; never guilt about what was missed or let go.
- proposals: for each proposed change in the facts, its id and one sentence on why it helps, in plain words. Keep
  every proposal: you may not add a change, drop one, or change what it does.

Rules (Kova's words guide):
- Use only numbers that appear in the facts, written the same way. Never calculate new numbers.
- Plain words. Never: FTP, TSS, CTL, zones by number, ERG, "load", "compliance". Say "what you could hold for about
  an hour", "your best hard minute", "easy", "hard".
- Never empty praise ("Great job!", "Crushed it"). Speak to the rider as "you"; "I" only for a decision the coach
  made. Indoors or out is the rider's choice. No medical advice; never mention recovery numbers.
"""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Two to four short sentences."},
        "proposals": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "why": {"type": "string"}},
            "required": ["id", "why"], "additionalProperties": False}},
    },
    "required": ["summary", "proposals"],
    "additionalProperties": False,
}

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w])")


def api_key() -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    try:
        with open(KEY_FILE) as f:
            return f.read().strip() or None
    except OSError:
        return None


def numbers_in(value) -> set[str]:
    """Every number in a facts packet, in the forms a reply might write it ("1,139", "1139", "25.8", "26")."""
    out: set[str] = set()

    def add(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            f = float(x)
            for v in {f, round(f), round(f, 1)}:
                s = f"{v:g}" if isinstance(v, float) else str(v)
                out.add(s)
                out.add(s.replace(".0", ""))
                if abs(v) >= 1000:
                    out.add(f"{int(round(v)):,}")
            return
        if isinstance(x, str):
            for m in _NUM.finditer(x):
                out.add(m.group(1))
                out.add(m.group(1).replace(",", ""))
            return
        if isinstance(x, dict):
            for v in x.values():
                add(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                add(v)

    add(value)
    return out


def check_numbers(text: str, facts: dict) -> list[str]:
    """Numbers in `text` that aren't in the facts packet (an empty list means it passes)."""
    allowed = numbers_in(facts)
    bad = []
    for m in _NUM.finditer(text):
        n = m.group(1)
        if n not in allowed and n.replace(",", "") not in allowed:
            bad.append(n)
    return bad


class Coach:
    """The AI layer: one per backend. `db` is the backend's sqlite connection, `lock` its lock."""

    def __init__(self, db, lock, client=None):
        self.db = db
        self.lock = lock
        self._client = client          # tests pass a fake
        self._pending: set[str] = set()
        self._plock = threading.Lock()

    # --- the policy gate ------------------------------------------------------------------------------
    def allowed(self, user_id: int) -> bool:
        with self.lock:
            row = self.db.execute("SELECT ai_personal FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row and row["ai_personal"]) and (self._client is not None or api_key() is not None)

    def set_allowed(self, user_id: int, on: bool) -> None:
        with self.lock:
            self.db.execute("UPDATE users SET ai_personal = ? WHERE id = ?", (1 if on else 0, user_id))

    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key(), timeout=60.0, max_retries=2)
        return self._client

    # --- the ride story --------------------------------------------------------------------------------
    def ride_story(self, user_id: int, ride_id: str, facts: dict, wait: bool = False,
                   key: Optional[str] = None) -> Optional[dict]:
        """The saved story for these facts, or None. If there is none yet, it's written in the background (or
        now, with `wait`), so the screen shows the engine's words first and the coach's on the next look."""
        if not self.allowed(user_id):
            return None
        key = key or f"ride:{ride_id}"
        h = _hash(facts)
        with self.lock:
            row = self.db.execute("SELECT input_hash, output FROM coach_texts WHERE user_id = ? AND key = ?",
                                  (user_id, key)).fetchone()
        if row and row["input_hash"] == h:
            out = json.loads(row["output"])
            return out if out.get("ok") else None
        if wait:
            return self._write(user_id, key, h, facts)
        with self._plock:
            if (user_id, key, h) in self._pending:
                return None
            self._pending.add((user_id, key, h))
        threading.Thread(target=self._write_bg, args=(user_id, key, h, facts), daemon=True).start()
        return None

    def _write_bg(self, user_id, key, h, facts):
        try:
            self._write(user_id, key, h, facts)
        except Exception:
            log.exception("coach story failed for %s", key)
        finally:
            with self._plock:
                self._pending.discard((user_id, key, h))

    def _write(self, user_id: int, key: str, h: str, facts: dict) -> Optional[dict]:
        import anthropic
        started = time.time()
        usage, out = None, {"ok": False}
        review = key.startswith("review:")
        try:
            r = self.client().beta.messages.create(
                model=MODEL,
                max_tokens=2000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema",
                                                           "schema": REVIEW_SCHEMA if review else SCHEMA}},
                system=[{"type": "text", "text": REVIEW_SYSTEM if review else SYSTEM,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": f"Facts about this {'week' if review else 'ride'} (JSON):\n"
                                                      + json.dumps(facts, sort_keys=True)}],
            )
            usage = r.usage
            if r.stop_reason == "refusal":
                out = {"ok": False, "why": "refusal"}
            elif review:
                data = json.loads(next((b.text for b in r.content if b.type == "text"), ""))
                out = _check_review(data, facts) | {"model": r.model}
            else:
                text = next((b.text for b in r.content if b.type == "text"), "")
                data = json.loads(text)
                bad = check_numbers(data["headline"] + " " + data["story"], facts)
                out = ({"ok": True, "headline": data["headline"].strip(), "story": data["story"].strip(), "by": "ai",
                        "model": r.model} if not bad else {"ok": False, "why": "numbers", "bad": bad})
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            log.warning("coach call failed for %s: %s", key, type(exc).__name__)
            out = {"ok": False, "why": type(exc).__name__}
        except (ValueError, KeyError) as exc:          # unreadable JSON: keep the engine's words
            out = {"ok": False, "why": f"reply: {type(exc).__name__}"}
        cost = _cost(usage)
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO coach_texts (user_id, key, input_hash, output, created_at) "
                            "VALUES (?, ?, ?, ?, ?)", (user_id, key, h, json.dumps(out), time.time()))
            self.db.execute("INSERT INTO coach_usage (user_id, key, model, input_tokens, output_tokens, cache_read, "
                            "cache_write, cost_usd, seconds, ok, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (user_id, key, MODEL, *(cost["tokens"]), cost["usd"], round(time.time() - started, 2),
                             1 if out.get("ok") else 0, time.time()))
        return out if out.get("ok") else None

    def week_review(self, user_id: int, week_start: str, facts: dict) -> Optional[dict]:
        """The Sunday review in the coach's words, for these facts (written in the background the first time, like
        a ride story). The engine's words stay when there's none."""
        return self.ride_story(user_id, week_start, facts, key=f"review:{week_start}")

    def spend(self, user_id: int) -> dict:
        with self.lock:
            row = self.db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd), 0) AS usd, COALESCE(SUM(ok), 0) AS ok "
                                  "FROM coach_usage WHERE user_id = ?", (user_id,)).fetchone()
        return {"calls": row["n"], "ok": row["ok"], "usd": round(row["usd"], 4)}


def _check_review(data: dict, facts: dict) -> dict:
    """The review's words pass only if every number is in the facts and every proposal is there, unchanged in
    number: the AI words the engine's changes, it never adds or drops one."""
    want = [p["id"] for p in facts.get("proposals", [])]
    got = {p["id"]: p["why"].strip() for p in data.get("proposals", [])}
    if sorted(got) != sorted(want):
        return {"ok": False, "why": "proposals"}
    bad = check_numbers(data["summary"] + " " + " ".join(got.values()), facts)
    if bad:
        return {"ok": False, "why": "numbers", "bad": bad}
    return {"ok": True, "summary": data["summary"].strip(), "proposals": got, "by": "ai"}


def _hash(facts: dict) -> str:
    return hashlib.sha256((str(PROMPT_VERSION) + MODEL + json.dumps(facts, sort_keys=True)).encode()).hexdigest()


def _cost(usage) -> dict:
    if usage is None:
        return {"tokens": (0, 0, 0, 0), "usd": 0.0}
    i = getattr(usage, "input_tokens", 0) or 0
    o = getattr(usage, "output_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    usd = (i * PRICE_PER_MTOK["input"] + o * PRICE_PER_MTOK["output"] + cr * PRICE_PER_MTOK["cache_read"]
           + cw * PRICE_PER_MTOK["cache_write"]) / 1e6
    return {"tokens": (i, o, cr, cw), "usd": round(usd, 6)}

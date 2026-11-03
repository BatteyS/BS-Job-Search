"""How much of the Claude plan is used, and what the page's runs used.

Claude Code reports the plan's usage windows on every request a run makes, as a
rate-limit event: the 5-hour session and the week, and on some plans the week
for one model. The page keeps the latest windows in data/ui-usage.json and shows
them in its header. Between runs, claude_run.check_usage() asks Claude Code's own
`/usage`, which answers without calling a model, so a check uses none of the
plan; from_usage_text() reads its answer.

Each run's own tokens and cost are in data/ui-runs.json; totals() adds them up.
The cost is what the same tokens would cost at API prices: on a subscription it
is a measure of size, not a charge.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import time

import core

USAGE = os.path.join(core.ROOT, "data", "ui-usage.json")

# Window -> what the page calls it. Others the CLI reports are shown by their key.
WINDOWS = {"five_hour": "Session", "seven_day": "Week", "seven_day_opus": "Week, Opus",
           "seven_day_sonnet": "Week, Sonnet"}

_lock = threading.Lock()


# --------------------------------------------------------------- reading

def from_event(info) -> dict:
    """The windows in one rate-limit event's info: {window: {used, resets_at,
    status}}. The full set is in the raw event's unifiedWindows; the fields
    the SDK models cover only the window that triggered the event."""
    raw = getattr(info, "raw", None) or {}
    out = {}
    for name, w in (raw.get("unifiedWindows") or {}).items():
        if isinstance(w, dict):
            out[name] = {"used": w.get("utilization"), "resets_at": w.get("resetsAt"),
                         "status": w.get("status")}
    kind = getattr(info, "rate_limit_type", None)
    if kind:
        w = out.setdefault(kind, {"used": None, "resets_at": None, "status": None})
        w["status"] = getattr(info, "status", None) or w["status"]
        if w["used"] is None:
            w["used"] = getattr(info, "utilization", None)
        if w["resets_at"] is None:
            w["resets_at"] = getattr(info, "resets_at", None)
    return out


# "Current session: 71% used · resets Nov 3 at 1:39pm (America/Chicago)"
# "Current week (all models): 36% used · resets Nov 7 at 10:59pm (America/Chicago)"
RE_LINE = re.compile(r"^Current (session|week)(?: \(([^)]*)\))?: (\d+)% used"
                     r"(?:\s*·\s*resets (.+))?$")
RE_WHEN = re.compile(r"^(?:([A-Z][a-z]{2}) (\d{1,2}) at )?(\d{1,2})(?::(\d{2}))?\s*([ap]m)"
                     r"(?: \(([^)]+)\))?$", re.I)


def from_usage_text(text: str, now: float | None = None) -> dict:
    """The windows in what /usage prints. A line it cannot read is left out."""
    out = {}
    for line in (text or "").splitlines():
        m = RE_LINE.match(line.strip())
        if not m:
            continue
        which, scope, pct, resets = m.groups()
        if which == "session":
            name = "five_hour"
        elif not scope or scope.lower() == "all models":
            name = "seven_day"
        else:
            name = "seven_day_" + re.sub(r"\W+", "_", scope.lower()).strip("_")
        out[name] = {"used": int(pct) / 100, "resets_at": when(resets, now), "status": None}
    return out


def when(text: str | None, now: float | None = None) -> int | None:
    """A /usage reset time ("Nov 3 at 1:39pm (America/Chicago)", or "1:39pm")
    as a Unix time, or None. The year is the one that puts it closest ahead."""
    m = RE_WHEN.match((text or "").strip())
    if not m:
        return None
    month, day, hour, minute, half, zone = m.groups()
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(zone) if zone else None
    except Exception:          # an unknown zone, or no tz database: local time
        tz = None
    base = dt.datetime.fromtimestamp(time.time() if now is None else now, tz)
    hour = int(hour) % 12 + (12 if half.lower() == "pm" else 0)
    try:
        if month:
            mon = dt.datetime.strptime(month, "%b").month
            stamp = base.replace(month=mon, day=int(day), hour=hour, minute=int(minute or 0),
                                 second=0, microsecond=0)
            if stamp < base - dt.timedelta(days=2):
                stamp = stamp.replace(year=stamp.year + 1)
        else:
            stamp = base.replace(hour=hour, minute=int(minute or 0), second=0, microsecond=0)
            if stamp < base:
                stamp += dt.timedelta(days=1)
    except ValueError:
        return None
    return int(stamp.timestamp())


# ----------------------------------------------------------------- store

def load() -> dict:
    try:
        with open(USAGE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record(windows: dict, source: str, note: str = "") -> dict:
    """Keep the latest windows. A window the new report leaves out keeps its
    last value: an event names only the windows the account has."""
    with _lock:
        data = load()
        merged = dict(data.get("windows") or {})
        merged.update({k: v for k, v in windows.items() if isinstance(v, dict)})
        data.update({"windows": merged, "seen": time.time(), "source": source})
        if note:
            data["note"] = note
        os.makedirs(os.path.dirname(USAGE), exist_ok=True)
        tmp = USAGE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, USAGE)
        return data


def windows(now: float | None = None) -> dict:
    """The latest windows, with any that has reset since it was read at 0."""
    now = time.time() if now is None else now
    out = {}
    for name, w in (load().get("windows") or {}).items():
        w = dict(w)
        if isinstance(w.get("resets_at"), (int, float)) and w["resets_at"] <= now:
            w.update(used=0.0, reset=True)
        out[name] = w
    return out


def totals(entries: list[dict], now: float | None = None) -> dict:
    """The page's runs today and over the last seven days: runs, tokens, and
    cost at API prices, from data/ui-runs.json."""
    now = time.time() if now is None else now
    midnight = dt.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0,
                                                      microsecond=0).timestamp()
    out = {}
    for key, since in (("today", midnight), ("week", now - 7 * 86400)):
        mine = [e for e in entries if (e.get("started") or 0) >= since]
        out[key] = {"runs": len(mine),
                    "tokens": sum(int(e.get("tokens") or 0) for e in mine),
                    "cost": round(sum(float(e.get("cost") or 0) for e in mine), 4)}
    return out


def summary(entries: list[dict], now: float | None = None) -> dict:
    """What GET /api/usage answers."""
    data = load()
    return {"windows": windows(now), "seen": data.get("seen"), "source": data.get("source"),
            "note": data.get("note", ""), "names": WINDOWS, "runs": totals(entries, now)}

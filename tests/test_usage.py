"""The plan usage the page shows: read from rate-limit events and from Claude
Code's /usage, kept between runs, and the page's own runs added up."""

from __future__ import annotations

import datetime as dt
import os
import sys
import types

import pytest

from helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "ui"))
import usage  # noqa: E402

# What Claude Code 2.1.317 reported on 2026-11-03, trimmed.
EVENT = types.SimpleNamespace(
    status="allowed", rate_limit_type="five_hour", utilization=None, resets_at=1793734800,
    raw={"status": "allowed", "rateLimitType": "five_hour", "resetsAt": 1793734800,
         "unifiedWindows": {
             "five_hour": {"utilization": 0.7, "resetsAt": 1793734800, "status": "allowed"},
             "seven_day": {"utilization": 0.36, "resetsAt": 1794114000, "status": "allowed"}}})
TEXT = """You are currently using your subscription to power your Claude Code usage

Current session: 71% used · resets Nov 3 at 1:39pm (America/Chicago)
Current week (all models): 36% used · resets Nov 7 at 10:59pm (America/Chicago)
Current week (Opus): 52% used · resets Nov 7 at 10:59pm (America/Chicago)

What's contributing to your usage?
"""
NOV_3 = dt.datetime(2026, 11, 3, 9, 0, tzinfo=dt.timezone.utc).timestamp()


def chicago(*args) -> int:
    from zoneinfo import ZoneInfo
    return int(dt.datetime(*args, tzinfo=ZoneInfo("America/Chicago")).timestamp())


def test_an_event_gives_every_window_it_reports():
    w = usage.from_event(EVENT)
    assert w["five_hour"] == {"used": 0.7, "resets_at": 1793734800, "status": "allowed"}
    assert w["seven_day"]["used"] == 0.36

    bare = types.SimpleNamespace(status="allowed_warning", rate_limit_type="seven_day",
                                 utilization=0.82, resets_at=None, raw={})
    assert usage.from_event(bare) == {"seven_day": {"used": 0.82, "resets_at": None,
                                                    "status": "allowed_warning"}}


def test_the_usage_command_is_read():
    w = usage.from_usage_text(TEXT, now=NOV_3)
    assert w["five_hour"]["used"] == 0.71
    assert w["five_hour"]["resets_at"] == chicago(2026, 11, 3, 13, 39)
    assert w["seven_day"]["used"] == 0.36 and w["seven_day_opus"]["used"] == 0.52
    assert usage.from_usage_text("You are using an API key", now=NOV_3) == {}


def test_reset_times_land_ahead_of_now():
    assert usage.when("Jan 2 at 9am (America/Chicago)",
                      now=chicago(2026, 12, 30, 12, 0)) == chicago(2027, 1, 2, 9, 0)
    assert usage.when("1:39pm (America/Chicago)",
                      now=chicago(2026, 11, 3, 14, 0)) == chicago(2026, 11, 4, 13, 39)
    assert usage.when("whenever") is None


def test_the_latest_windows_are_kept_and_reset_ones_read_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "USAGE", str(tmp_path / "ui-usage.json"))
    assert usage.windows() == {}
    usage.record({"five_hour": {"used": 0.7, "resets_at": 1000}}, "run")
    usage.record({"seven_day": {"used": 0.36, "resets_at": 5000}}, "check", note="subscription")
    data = usage.load()
    assert set(data["windows"]) == {"five_hour", "seven_day"} and data["source"] == "check"
    w = usage.windows(now=2000)
    assert w["five_hour"] == {"used": 0.0, "resets_at": 1000, "reset": True}
    assert w["seven_day"]["used"] == 0.36


def test_the_pages_runs_are_added_up():
    now = dt.datetime(2026, 11, 3, 15, 0).timestamp()
    entries = [{"started": now - 3600, "tokens": 1000, "cost": 0.5},
               {"started": now - 3 * 86400, "tokens": 500, "cost": 0.25},
               {"started": now - 10 * 86400, "tokens": 9, "cost": 9.0},
               {"started": now - 60}]           # a run with nothing counted yet
    t = usage.totals(entries, now=now)
    assert t["today"] == {"runs": 2, "tokens": 1000, "cost": 0.5}
    assert t["week"] == {"runs": 3, "tokens": 1500, "cost": 0.75}


@pytest.mark.parametrize("line", [
    "Current session: 0% used",
    "Current session: 5% used · resets 4pm (America/Chicago)",
])
def test_short_lines_still_read(line):
    assert "five_hour" in usage.from_usage_text(line, now=NOV_3)

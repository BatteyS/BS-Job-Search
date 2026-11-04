"""The router: which model and effort each skill run gets, and why."""

from __future__ import annotations

import os
import sys

import pytest

from helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "ui"))
import claude_run  # noqa: E402
import core  # noqa: E402
import digest_applies  # noqa: E402
import router  # noqa: E402

NOW = 1_800_000_000
LATER = NOW + 3600


@pytest.fixture
def digest(tmp_path, monkeypatch):
    """Write digests/<date>.md with `applies` roles ticked apply, the first
    `letters` of them with a cover letter, and `others` left unmarked."""
    folder = tmp_path / "digests"
    folder.mkdir()
    for mod in (core, digest_applies):
        monkeypatch.setattr(mod, "ROOT", str(tmp_path))
        monkeypatch.setattr(mod, "DIGESTS", str(folder))
        monkeypatch.setattr(mod, "APPS", str(tmp_path / "Applications"))

    def write(date: str, applies: int, letters: int = 0, others: int = 1) -> None:
        lines = [f"# Job digest — {date}", ""]
        for i in range(applies + others):
            lines += [f"### {i + 1}. Employer {i} — Analyst · **80** · Austin",
                      f"- [{'x' if i < applies else ' '}] apply",
                      "- [ ] skip — reason:",
                      f"- [{'x' if i < letters else ' '}] cover letter", ""]
        (folder / f"{date}.md").write_text("\n".join(lines), encoding="utf-8")
    return write


def test_every_skill_has_a_route_with_a_reason():
    assert set(router.ROUTES) == set(claude_run.SKILLS)
    for name in claude_run.SKILLS:
        r = router.route(name, now=NOW)
        assert r["model"] in router.MODELS and r["effort"] in router.EFFORTS
        assert r["why"] and r["auto"] is True
        assert r["label"] == f"{router.NAMES[r['model']]} · {r['effort']}"


def test_conversation_and_volume_go_to_sonnet_and_writing_to_opus():
    assert router.route("setup")["model"] == "sonnet"
    assert router.route("job-scan")["model"] == "sonnet"
    for name in ("tailor-resume", "cover-letter", "interview-prep"):
        r = router.route(name)
        assert (r["model"], r["effort"]) == ("opus", "high")


@pytest.mark.parametrize("applies,letters,want", [
    (0, 0, ("sonnet", "low")),       # nothing to tailor
    (2, 0, ("opus", "medium")),
    (6, 0, ("sonnet", "high")),      # a volume job
    (2, 1, ("opus", "high")),        # letters need the writing
    (6, 2, ("opus", "medium")),
])
def test_tailoring_a_digest_follows_what_is_marked(digest, applies, letters, want):
    digest("2026-11-01", applies, letters)
    r = router.route("tailor-digest", {"date": "2026-11-01"})
    assert (r["model"], r["effort"]) == want
    assert str(applies) in r["why"] or applies == 0


def test_a_digest_route_reads_the_newest_digest_without_a_date(digest):
    digest("2026-10-01", 0)
    digest("2026-11-01", 2, 1)
    assert router.route("tailor-digest")["effort"] == "high"
    assert router.route("tailor-digest", {"date": "2026-10-01"})["model"] == "sonnet"


def test_no_digest_keeps_the_default(digest):
    r = router.route("tailor-digest")
    assert (r["model"], r["effort"]) == ("opus", "medium")


def test_a_full_plan_window_steps_the_route_down():
    tight = {"five_hour": {"used": 0.85, "resets_at": LATER}, "seven_day": {"used": 0.4}}
    r = router.route("tailor-resume", limits=tight, now=NOW)
    assert (r["model"], r["effort"]) == ("sonnet", "high")
    assert "5-hour session is 85% used" in r["why"]

    opus_week = {"seven_day_opus": {"used": 0.9, "resets_at": LATER}}
    r = router.route("cover-letter", limits=opus_week, now=NOW)
    assert r["model"] == "sonnet" and "week's Opus is 90% used" in r["why"]

    tighter = {"seven_day": {"used": 0.93, "resets_at": LATER}}
    r = router.route("setup", limits=tighter, now=NOW)
    assert (r["model"], r["effort"]) == ("sonnet", "low") and "one step less effort" in r["why"]


def test_a_window_that_has_reset_does_not_count():
    reset = {"five_hour": {"used": 0.99, "resets_at": NOW - 60}}
    assert router.route("tailor-resume", limits=reset, now=NOW)["model"] == "opus"


def test_a_pick_stands_even_on_a_full_plan():
    tight = {"five_hour": {"used": 0.97, "resets_at": LATER}}
    r = router.route("job-scan", limits=tight, pick={"model": "opus", "effort": "max"}, now=NOW)
    assert (r["model"], r["effort"], r["auto"]) == ("opus", "max", False)
    assert r["why"] == "your pick in the Runs tab"

    half = router.route("cover-letter", pick={"model": "haiku", "effort": "auto"})
    assert (half["model"], half["effort"]) == ("haiku", "high")
    assert half["why"].endswith("the rest is your pick in the Runs tab")


@pytest.mark.parametrize("kwargs", [
    {"skill": "nope"},
    {"skill": "setup", "pick": {"model": "gpt"}},
    {"skill": "setup", "pick": {"effort": "extreme"}},
])
def test_what_is_not_a_route_is_refused(kwargs):
    with pytest.raises(ValueError):
        router.route(**kwargs)

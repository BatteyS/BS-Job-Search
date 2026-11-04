"""Which model and effort each skill run gets.

Every run the page starts goes through route(): the skill, what the page passed
it (the open digest, a posting), the person's own pick in the Runs tab, and the
latest plan usage from usage.py. The rules are plain code, not a question put to
a model, so routing uses none of the plan, and each route carries the rule that
chose it for the run to show.

A run's replies keep its route. Claude Code caches a conversation for one model
at one effort, and changing either mid-run makes the next turn read the whole
conversation again uncached, which costs more usage than the switch saves.
"""

from __future__ import annotations

import time

import core
import digest_applies

# Claude Code's aliases, each the newest model of its kind for the account.
MODELS = ("opus", "sonnet", "haiku")
NAMES = {"opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# skill -> (model, effort, why). A why reads after "Sonnet at medium effort: ".
ROUTES = {
    "setup": ("sonnet", "medium",
              "an interview is mostly conversation and careful transcription, which Sonnet "
              "does well on less of your plan"),
    "job-scan": ("sonnet", "medium",
                 "a scan reads every candidate posting, the heaviest run there is, and Sonnet "
                 "scores them against your rubric on less of your plan"),
    "tailor-resume": ("opus", "high",
                      "choosing what a resume leads with is the judgment the whole workflow "
                      "exists for"),
    "cover-letter": ("opus", "high",
                     "a letter has to read well and cite a source for every claim"),
    "interview-prep": ("opus", "high",
                       "a prep sheet has to pick the stories this posting asks about and "
                       "cite a source for every claim, as a letter does"),
    "tailor-digest": ("opus", "medium", "Opus for the judgment each resume needs"),
}

# A digest run with more applies than this is a volume job.
MANY_APPLIES = 4
# Plan usage at or above these shares of a window steps a route down.
TIGHT, TIGHTER = 0.8, 0.9
WINDOW_NAMES = {"five_hour": "your 5-hour session", "seven_day": "your week",
                "seven_day_opus": "your week's Opus"}


def route(skill: str, params: dict | None = None, limits: dict | None = None,
          pick: dict | None = None, now: float | None = None) -> dict:
    """The model and effort for one run, with why: {model, effort, why, auto,
    label}. `pick` is the Runs tab's {model, effort}, each "auto" or a value;
    `limits` is usage.windows()."""
    if skill not in ROUTES:
        raise ValueError(f"no skill named {skill!r}")
    pick = pick or {}
    want_model = str(pick.get("model") or "auto")
    want_effort = str(pick.get("effort") or "auto")
    if want_model not in MODELS + ("auto",):
        raise ValueError(f"model must be auto or one of {', '.join(MODELS)}")
    if want_effort not in EFFORTS + ("auto",):
        raise ValueError(f"effort must be auto or one of {', '.join(EFFORTS)}")

    model, effort, why = (digest_route((params or {}).get("date")) if skill == "tailor-digest"
                          else ROUTES[skill])
    reasons = [why]
    # Only what the router chose for itself steps down; a pick stands.
    share, window = tightest(limits, now)
    opus_share = used(limits, "seven_day_opus", now)
    if want_model == "auto" and model == "opus" and max(share, opus_share) >= TIGHT:
        model = "sonnet"
        name = window if share >= opus_share else WINDOW_NAMES["seven_day_opus"]
        reasons.append(f"but {name} is {round(max(share, opus_share) * 100)}% used, so "
                       "Sonnet instead, to stretch what is left")
    elif want_effort == "auto" and share >= TIGHTER and effort != "low":
        effort = EFFORTS[EFFORTS.index(effort) - 1]
        reasons.append(f"but {window} is {round(share * 100)}% used, so one step less effort")

    if want_model != "auto":
        model = want_model
    if want_effort != "auto":
        effort = want_effort
    if want_model != "auto" and want_effort != "auto":
        reasons = ["your pick in the Runs tab"]
    elif want_model != "auto" or want_effort != "auto":
        reasons.append("the rest is your pick in the Runs tab")
    return {"model": model, "effort": effort, "why": "; ".join(reasons),
            "auto": want_model == "auto" and want_effort == "auto",
            "label": f"{NAMES[model]} · {effort}"}


def digest_route(date: str | None) -> tuple[str, str, str]:
    """Tailoring a digest scales with what is marked in it: the open digest,
    or the newest one, as /tailor-digest picks."""
    if not date:
        dates = [d["date"] for d in core.list_digests()]
        if not dates:
            return ROUTES["tailor-digest"]
        date = dates[0]
    try:
        r = digest_applies.parse(core.digest_path(date))
    except (ValueError, FileNotFoundError):
        return ROUTES["tailor-digest"]
    applies, letters = len(r["apply"]), len(r["letters"])
    resumes = f"{applies} resume{'' if applies == 1 else 's'}"
    if not applies:
        return ("sonnet", "low", "nothing in the digest is marked apply yet, so the run has "
                                 "little to do")
    if letters:
        return ("opus", "high" if applies <= MANY_APPLIES else "medium",
                f"{resumes} and {letters} letter{'' if letters == 1 else 's'}, and letters "
                "need Opus's writing")
    if applies > MANY_APPLIES:
        return ("sonnet", "high", f"{resumes} in one run: Sonnet keeps the run's usage down, "
                                  "and high effort keeps each selection careful")
    return ("opus", "medium", f"{resumes}: Opus for the judgment, medium effort for the "
                              "number of them")


def used(limits: dict | None, window: str, now: float | None = None) -> float:
    """The share of one plan window used, or 0 when unknown or since reset."""
    w = (limits or {}).get(window) or {}
    share = w.get("used")
    if not isinstance(share, (int, float)):
        return 0.0
    resets = w.get("resets_at")
    if isinstance(resets, (int, float)) and resets <= (time.time() if now is None else now):
        return 0.0
    return float(share)


def tightest(limits: dict | None, now: float | None = None) -> tuple[float, str]:
    """The fuller of the session and week windows: (share used, its name)."""
    shares = [(used(limits, w, now), WINDOW_NAMES[w]) for w in ("five_hour", "seven_day")]
    return max(shares)

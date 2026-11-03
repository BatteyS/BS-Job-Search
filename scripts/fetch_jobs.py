"""Stage 1 -- fetch, normalize, dedupe, and hard-filter job postings.

No LLM. Deterministic and cheap by design: this stage exists so Stage 2 (Claude
scoring) only ever sees postings that already cleared every mechanical filter.
See ARCHITECTURE.md.

ATS adapters live in scripts/ats_adapters.py -- adding a platform or a company
never requires touching this file.

Scale design (built for hundreds to low thousands of boards, not 40):
  * Two-phase fetch. Listings come back without descriptions, get filtered on
    title/location/age, and only survivors get a detail fetch. Pulling full
    content for every posting across 500 boards would move hundreds of MB a
    night to discard ~99% of it.
  * Per-host concurrency caps (in ats_adapters.HOST_LIMITS). All boards of one
    vendor share a host, so this -- not --workers -- prevents rate limiting.
  * Board-response hashing: an unchanged board skips its detail work.
  * Per-board isolation: one failing board never aborts a run. Three
    consecutive failures raise a stale_boards warning.
  * Batched SQLite writes in WAL mode.

Usage:
    python scripts/fetch_jobs.py --clusters <id>,<id>
    python scripts/fetch_jobs.py --all-clusters -v
    python scripts/fetch_jobs.py --all-clusters --ats workday --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobspy_source  # noqa: E402  -- board settings only; JobSpy loads lazily
import scan_config  # noqa: E402
from ats_adapters import SUPPORTED, Job, fetch_detail, iso, list_board  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_print_lock = threading.Lock()


def log(msg: str, *, v: bool = True) -> None:
    if v:
        with _print_lock:
            print(msg, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ location

STATES = list(scan_config.STATE_NAMES)
STATE_RE = re.compile(r"\b(" + "|".join(STATES) + r")\b")
STATE_NAME_RE = re.compile(r"(?<![a-z])(" + "|".join(
    sorted(scan_config.STATE_CODES, key=len, reverse=True)) + r")(?![a-z])")
REMOTE_RE = re.compile(r"\b(remote|distributed|work from home|wfh|anywhere)\b", re.I)

# What every profile shares about place names: the metro library's city names,
# names that need a state to count, and words that put a place outside the US.
# A profile's filters.yaml adds to the last two.
PLACES = os.path.join(ROOT, "presets/metros.yaml")

# A posting open in several places lists them between these. Each place is
# judged on its own, so "London, UK; San Francisco, CA" is a San Francisco job.
PLACE_SEPARATOR = re.compile(r"\s*[|;\n]\s*")

# Words that put a place in the US: "Remote (US or Canada)", "New England".
US_RE = re.compile(r"(?<![a-z])(us|usa|u\.s\.(a\.)?|united states|new england)(?![a-z])",
                   re.I)

# State codes that postings also use for a country or province on the marker
# list: "Toronto, CA" is Canada, "Berlin, DE" Germany, "Pune, MH, IN" India,
# "Tel Aviv, IL" Israel, "Amsterdam, NH" Noord-Holland. Beside a marker they
# show nothing. Any other code does: "Vancouver, WA" and "Mexico, MO" are US
# towns.
SHARED_CODES = {"CA", "DE", "IN", "IL", "NH"}

# What can sit between a city and its state: "Concord, Middlesex County, MA".
COUNTY_RE = re.compile(r"\b(county|parish|borough)$", re.I)


def load_places(path: str = PLACES) -> dict:
    try:
        return scan_config.load_yaml(path)
    except FileNotFoundError:
        return {}


def any_of(words) -> re.Pattern | None:
    """One pattern matching any of `words` whole, trying the longest first."""
    words = sorted(set(words), key=len, reverse=True)
    if not words:
        return None
    return re.compile(r"(?<![a-z])(" + "|".join(map(re.escape, words)) + r")(?![a-z])",
                      re.I)


def stated_states(place: str) -> set[str]:
    """The states a place names: codes as written ("Everett, WA" -- the word
    "or" is not Oregon) and names spelled out ("Aurora-Colorado-United States")."""
    return (set(STATE_RE.findall(place))
            | {scan_config.STATE_CODES[n] for n in STATE_NAME_RE.findall(place.lower())})


def names_us(place: str) -> bool:
    """Does a place say it is in the US?"""
    return bool(US_RE.search(place) or stated_states(place) - SHARED_CODES)


def own_state(place: str, end: int) -> str | None:
    """The state written right after the city that ends at `end`, past any
    county: "Carson City, NV", "Concord, Middlesex County, MA",
    "Dublin-Ohio-United States of America". None when nothing says."""
    for part in re.split(r"\s*[,\-–—]\s*", place[end:])[1:]:
        if COUNTY_RE.search(part):
            continue
        words = part.split()
        if words and words[0] in STATES:
            return words[0]
        return scan_config.STATE_CODES.get(part.lower())
    return None


class LocationResolver:
    """Free-text location -> metro key, or None to drop.

    Deliberately conservative. A posting whose metro cannot be established is
    dropped rather than guessed at: a wrong metro produces a digest entry the
    user would have to catch by reading, which defeats the point of the filter.

    Each place a posting lists is judged on its own. Non-US places go first,
    because "Cambridge" and "Boston" both exist in England. A city in what is
    left counts only if nothing contradicts it: a name that needs a state must
    have one its metro covers, a state written after any city must be one its
    metro covers ("Lexington, KY" is not the one near Boston), and a city
    inside a longer known name does not count ("Mesa" in "Costa Mesa").

    `only_metros` narrows the allowlist for one run (--metros). `mode` is
    remote.mode: `include` keeps remote postings beside metro ones, `exclude`
    drops any posting whose location reads as remote, `only` keeps nothing else.
    `places` replaces presets/metros.yaml, for tests.
    """

    def __init__(self, cfg: dict, only_metros=None, mode: str = "include",
                 places: dict | None = None):
        self.metros = cfg.get("metros") or {}
        self.remote_cfg = cfg.get("remote") or {}
        self.mode = mode
        lib = load_places() if places is None else places
        self.ambiguous = {s.lower() for s in (cfg.get("require_state_disambiguation") or [])
                          + (lib.get("ambiguous_cities") or [])}
        # Whole words only: "india" is not in "Indianapolis", nor "berlin" in
        # "Oberlin Road".
        self.non_us = any_of(s.lower() for s in (cfg.get("non_us_markers") or [])
                             + (lib.get("non_us_markers") or []))
        keep = set(only_metros) if only_metros else set(self.metros)
        self.where: dict[str, list[str]] = {}       # city -> metros that list it
        for key, m in self.metros.items():
            if key in keep:
                for c in (m.get("cities") or []) + (m.get("regions") or []):
                    self.where.setdefault(c.lower(), []).append(key)
        # Every name the library knows, too, so "Costa Mesa" reads as itself in
        # a profile whose metros list only "mesa".
        known = set(self.where)
        for m in (lib.get("metros") or {}).values():
            known.update(c.lower() for c in (m.get("cities") or []) + (m.get("regions") or []))
        self.names = any_of(known) if self.where else None

    def foreign(self, place: str) -> bool:
        """Does this one place name a non-US marker, with nothing to say it is
        the US place of that name?"""
        if not self.non_us or not self.non_us.search(place):
            return False
        return not names_us(place)

    def resolve(self, raw: str) -> tuple[str | None, bool, int] | None:
        if not raw:
            return None
        places = [p for p in PLACE_SEPARATOR.split(raw) if p.strip()]
        us = [p for p in places if not self.foreign(p)]
        if not us:
            return None
        # Beside a non-US place, "Remote" counts only when the posting names
        # the US too: "Remote | London" is remote in London, where
        # "Remote | United States | Poland" is remote here.
        is_remote = (any(REMOTE_RE.search(p) for p in us)
                     and (len(us) == len(places) or any(names_us(p) for p in us)))
        if self.mode == "exclude" and is_remote:
            return None
        if self.mode == "only" and not is_remote:
            return None

        best: tuple[str, int] | None = None
        for place in us:
            stated = stated_states(place)
            for m in self.names.finditer(place) if self.names else ():
                city = m.group(1).lower()
                for metro in self.where.get(city, ()):
                    allowed = set(self.metros[metro].get("states") or [])
                    if city in self.ambiguous and not stated & allowed:
                        continue      # cannot disambiguate -> ignore this match
                    own = own_state(place, m.end())
                    if own and own not in allowed:
                        continue      # its own state is outside this metro
                    pen = int(self.metros[metro].get("penalty", 0))
                    if best is None or pen > best[1]:
                        best = (metro, pen)
        if best:
            return (best[0], is_remote, best[1])

        if is_remote:
            text = " | ".join(us).lower()
            if re.search(r"\b(emea|apac|europe|latam|global|international)\b", text):
                return None
            return (None, True, int(self.remote_cfg.get("penalty", -6)))
        return None


# ---------------------------------------------------------------------- comp

MONEY_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?\s*[kK]\b|\d{4,7})")
SALARY_CTX = re.compile(
    r"(salary|compensation|base pay|base salary|pay range|pay band|annual|"
    r"total cash|target cash|hiring range)", re.I)


def _money(tok: str) -> float | None:
    t = tok.replace(",", "").strip()
    try:
        return float(t[:-1].strip()) * 1000 if t.lower().endswith("k") else float(t)
    except ValueError:
        return None


def parse_comp(text: str, min_hourly: int) -> tuple[int | None, int | None]:
    """Best-effort disclosed range. Conservative: unsure -> (None, None).

    A false 'below floor' reading silently drops a good job, so only figures
    appearing in an explicit salary context are considered.
    """
    if not text:
        return (None, None)
    vals: list[float] = []
    for m in SALARY_CTX.finditer(text):
        window = text[max(0, m.start() - 120): m.end() + 220]
        for mm in MONEY_RE.finditer(window):
            v = _money(mm.group(1))
            if v is None:
                continue
            if v < 1000:
                if v >= min_hourly:
                    vals.append(v * 2080)
            elif 20_000 <= v <= 1_500_000:
                vals.append(v)
    return (int(min(vals)), int(max(vals))) if vals else (None, None)


# A description shorter than this cannot be judged: no requirements section, no
# stated years, nothing to gate on. Adzuna's snippets run about 539 characters.
THIN_DESCRIPTION = 1200


def too_old(posted_at: str | None, cutoff) -> bool:
    """Is this posting older than the cutoff?

    Sources disagree about timezones: Adzuna sends a trailing Z, USAJOBS sends
    none at all, and Workday sends a relative string until its detail fetch
    corrects it. A naive value compared against an aware cutoff raises
    TypeError, so UTC is assumed when the source omits the offset. An
    unparseable date is kept rather than dropped -- losing a live posting to a
    date format is worse than scoring one that is slightly stale.
    """
    if not posted_at:
        return False
    try:
        posted = datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return posted < cutoff


# --------------------------------------------------------------- experience

# The single biggest reason a surfaced role gets skipped. On the first digest
# this was tuned against, 10 of 16 skips were "the first qualification demands
# N years I don't have" -- minimums of 3, 4, 4, 5, 5, 5, 6, 8 and 10 against
# about two years of experience. Stage 1 never read the requirements section,
# so each of those roles cost the user a read.
YOE_PATTERNS = [
    # "5+ years of experience", "3-5 years' relevant experience"
    re.compile(r"(\d{1,2})\s*\+?\s*(?:to|-|\u2013)?\s*\d{0,2}\s*years?['\u2019]?\s+"
               r"(?:of\s+)?(?:\w+[\s,]+){0,3}?experience", re.I),
    # "8+ years of mechanical commissioning" -- the requirement is often stated
    # against a discipline, not the word "experience". This is the form that
    # made both OpenAI roles unreadable on the first pass.
    re.compile(r"(\d{1,2})\s*\+\s*years?\s+(?:of|in|with|as)\b", re.I),
    re.compile(r"minimum\s+of\s+(\d{1,2})\s*\+?\s*years?", re.I),
    re.compile(r"at\s+least\s+(\d{1,2})\s*\+?\s*years?", re.I),
    re.compile(r"(\d{1,2})\s*\+?\s*years?\s+(?:of\s+)?(?:relevant|professional|"
               r"industry|related|progressive)\b", re.I),
]


def parse_years_required(text: str) -> tuple[int | None, int | None]:
    """Lowest and highest stated experience minimums, or (None, None).

    Deliberately lenient: postings often list a hard minimum and a softer
    "preferred" one, and the LOWEST is the number worth gating on. Reading the
    highest would drop roles whose real bar the user clears. Unknown is never a
    drop -- Adzuna returns ~200-char snippets that rarely contain the
    requirements at all.
    """
    if not text:
        return (None, None)
    vals: list[int] = []
    for pat in YOE_PATTERNS:
        for m in pat.finditer(text):
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                continue
            # 0 is noise; >25 is company boilerplate ("40 years in business").
            if 1 <= n <= 25:
                vals.append(n)
    return (min(vals), max(vals)) if vals else (None, None)


# A recruiter posting for an employer it does not name. blocklist_staffing
# matches company names, and a specialist recruiter is not on it: on 2026-11-02
# Climate People reached the digest as if it were the employer, with "We're
# partnering with a well-funded direct air capture (DAC) and flow battery
# startup". Flagged, not dropped -- the role behind it can be real and worth it.
# Recruiters say so in their opening lines; an employer's own "we're working
# with a utility" usually comes later, so only the opening is read.
RECRUITER = re.compile(
    r"\b(?:on behalf of (?:our|a|an) client|"
    r"our client(?:'s|’s)? (?:is|has|seeks|needs|wants)\b|"
    r"we(?:'|’)?re (?:partnering|working) with (?:a|an|one)\b|"
    r"we are (?:partnering|working) with (?:a|an|one)\b|"
    r"confidential (?:client|company|employer))", re.I)
RECRUITER_OPENING_CHARS = 600


def posted_by_recruiter(text: str) -> bool:
    """Whether a posting reads as a recruiter's, for an employer it does not name."""
    return bool(text and RECRUITER.search(text[:RECRUITER_OPENING_CHARS]))


# ------------------------------------------------------------------ clusters


PRESETS = os.path.join(ROOT, "presets/title_excludes.yaml")


def preset_patterns(names, path: str = PRESETS) -> list[tuple[str, str]]:
    """(preset name, regex) for each title preset a profile names.

    Presets are shared, ready-made exclusions -- a career stage, or a job type
    like sales -- so a profile can say `presets: [mid_career, no_sales]` rather
    than carry the regexes itself. An unknown name stops the run: a typo would
    otherwise drop nothing and look like a working filter.
    """
    if not names:
        return []
    lib = yaml.safe_load(open(path, encoding="utf-8")) or {}
    known = sorted(k for k, v in lib.items() if isinstance(v, dict))
    unknown = [n for n in names if n not in known]
    if unknown:
        raise SystemExit(f"unknown title preset(s): {', '.join(unknown)}\n"
                         f"available: {', '.join(known)}")
    return [(n, p) for n in names for p in (lib[n].get("patterns") or [])]


class ClusterMatcher:
    def __init__(self, cfg: dict):
        g = cfg.get("global") or {}
        # Each exclude keeps the label of where it came from, so --preview can
        # say which preset or pattern dropped a title.
        labelled = ([(f"preset {n}", p) for n, p in preset_patterns(g.get("presets"))]
                    + [("global", p) for p in g.get("exclude") or []])
        self.global_ex = [(label, p, re.compile(p, re.I)) for label, p in labelled]
        self.clusters = [{
            "id": c["id"],
            "inc": [re.compile(p, re.I) for p in c.get("include") or []],
            "exc": [(p, re.compile(p, re.I)) for p in c.get("exclude") or []],
        } for c in cfg["clusters"]]

    def match(self, title: str, active: set[str]) -> list[str]:
        if any(r.search(title) for _, _, r in self.global_ex):
            return []
        return [c["id"] for c in self.clusters
                if c["id"] in active
                and not any(r.search(title) for _, r in c["exc"])
                and any(r.search(title) for r in c["inc"])]

    def explain(self, title: str, active: set[str]) -> dict[str, tuple[str, str] | None]:
        """Per active cluster whose include patterns match the title: None if
        the title gets through, or (where, pattern) for the exclude that drops
        it. Clusters whose includes do not match are left out."""
        dropped_by = next(((label, p) for label, p, r in self.global_ex
                           if r.search(title)), None)
        out: dict[str, tuple[str, str] | None] = {}
        for c in self.clusters:
            if c["id"] not in active or not any(r.search(title) for r in c["inc"]):
                continue
            if dropped_by:
                out[c["id"]] = dropped_by
                continue
            hit = next((p for p, r in c["exc"] if r.search(title)), None)
            out[c["id"]] = ("cluster", hit) if hit else None
        return out


class TitlePreview:
    """--preview: what each cluster's title patterns let through, and what
    they drop, among postings in the profile's metros. Nothing is written.

    Tuning a cluster used to mean writing a regex and reading a digest a
    minute later. This shows the effect directly, including the near misses
    -- titles an include pattern wanted that an exclude then dropped -- which
    is where a filter that is too tight shows up.
    """

    def __init__(self, matcher: ClusterMatcher, locres: "LocationResolver",
                 active: set[str], show: int):
        self.matcher, self.locres, self.active, self.show = matcher, locres, active, show
        self.kept: dict[str, dict] = {c: {} for c in active}
        self.dropped: dict[str, dict] = {c: {} for c in active}
        self.in_area = self.out_of_area = 0

    def consider(self, j: Job) -> None:
        if self.locres.resolve(j.location_raw) is None:
            self.out_of_area += 1
            return
        self.in_area += 1
        for cid, why in self.matcher.explain(j.title, self.active).items():
            key = (j.title.strip(), j.company)
            if why is None:
                self.kept[cid][key] = j
            else:
                self.dropped[cid].setdefault(why, {})[key] = j

    def report(self) -> None:
        import random
        log("")
        log(f"PREVIEW -- {self.in_area} postings in the profile's metros "
            f"({self.out_of_area} elsewhere, not shown). Nothing was written.")
        for cid in sorted(self.active):
            kept = sorted(self.kept[cid])
            log("")
            log(f"{cid}: {len(kept)} distinct titles get through")
            sample = list(kept)
            random.Random(0).shuffle(sample)
            for title, company in sorted(sample[: self.show]):
                log(f"  + {title}  [{company}]")
            drops = sorted(self.dropped[cid].items(), key=lambda kv: -len(kv[1]))
            if drops:
                total = sum(len(v) for _, v in drops)
                log(f"  just missed: {total} titles matched an include pattern, "
                    "then an exclude dropped them")
                for (where, pattern), titles in drops[:8]:
                    eg = "; ".join(t for t, _ in sorted(titles)[:2])
                    log(f"    {len(titles):5}  {where:22} {pattern}")
                    log(f"           e.g. {eg}")
                if len(drops) > 8:
                    log(f"    ... and {len(drops) - 8} more patterns")


# Sources with no company curation behind them. A board in companies.yaml was
# put there because the employer is relevant; an aggregator hands back whoever
# happens to match the words.
UNCURATED_SOURCES = frozenset({"adzuna"}) | jobspy_source.SCRAPED_ATS


class DomainGate:
    """Extra precision check for clusters that lean on the curated board list.

    A cluster can cast a wide title net on purpose -- "Manufacturing Engineer"
    is a climate role when the board it came from belongs to a climate
    company. An aggregator voids that assumption entirely: the 2026-08-19 Indeed
    probe matched Qualcomm "Server Postsilicon Project Engineer" and Intuitive
    Surgical "User Interaction Test Engineer" through exactly those patterns,
    34 of 104 survivors in all.

    Gating on the title alone would overcorrect -- KoBold Metals "Manufacturing
    Engineer" and Tesla "Mechanical Engineer, Infrastructure, Energy" are both
    wanted and neither title carries a domain word. So the gate reads the
    description too, which only works because Indeed returns the whole posting
    and phase C has already enriched the thin ones by the time this runs.

    A single match is enough, deliberately. Requiring several was measured and
    is worse: legitimate climate roles named their domain exactly once as often
    as noise did, so a higher bar cost recall and bought no precision. The
    vocabulary in `aggregator_gate` carries the discrimination instead -- see
    the comment beside it in clusters.yaml for the numbers.

    A cluster with no `aggregator_gate` is unaffected, as are all curated
    sources.
    """

    def __init__(self, cfg: dict):
        self.gates = {
            c["id"]: [re.compile(p, re.I) for p in (c.get("aggregator_gate") or [])]
            for c in cfg["clusters"]
        }

    def keep(self, cluster_id: str, ats: str, title: str, description: str) -> bool:
        if ats not in UNCURATED_SOURCES:
            return True
        pats = self.gates.get(cluster_id)
        if not pats:
            return True
        blob = f"{title}\n{description[:8000]}"
        return any(p.search(blob) for p in pats)


# Which copy of a duplicate requisition to keep. Higher wins. The text is what
# is being ranked: scoring quality follows the description, and the experience
# gate cannot run at all on a snippet. Company boards and USAJOBS return whole
# postings; Indeed does too (median 6,436 chars on the probe); Adzuna returns
# ~539 characters and is always the copy to discard.
#
# This replaced a binary "prefer anything over Adzuna" rule, which was fine
# with one aggregator and ambiguous with two. The other scraped boards rank
# with Indeed; ties break on description length.
SOURCE_RANK = {"adzuna": 0, "indeed": 2, "linkedin": 2, "glassdoor": 2,
               "zip_recruiter": 2, "usajobs": 3}
DEFAULT_SOURCE_RANK = 4          # a company's own board


# Every source fetch_jobs can read, by the name filters.yaml `sources` uses.
# The scraped boards are jobspy_source.SITES.
SOURCES = ("boards", "adzuna", "usajobs", *jobspy_source.SITES)


def chosen_sources(filt: dict, args) -> tuple[set[str], str]:
    """Which sources run: --sources if given, else filters.yaml `sources`.

    A profile without a `sources` block reads the company boards only, which
    is what a run without flags always did.
    """
    if args.sources:
        chosen = {s.strip() for s in args.sources.split(",") if s.strip()}
        origin = "--sources"
    elif filt.get("sources") is not None:
        cfg = filt.get("sources") or {}
        unknown = sorted(set(cfg) - set(SOURCES))
        if unknown:
            raise SystemExit(f"filters.yaml sources: unknown {', '.join(unknown)}\n"
                             f"known: {', '.join(SOURCES)}")
        chosen = {k for k, on in cfg.items() if on}
        origin = "filters.yaml"
    else:
        chosen, origin = {"boards"}, "default"
    unknown = sorted(chosen - set(SOURCES))
    if unknown:
        raise SystemExit(f"unknown source(s) {', '.join(unknown)}; "
                         f"known: {', '.join(SOURCES)}")
    return chosen, origin


def source_rank(ats: str) -> int:
    return SOURCE_RANK.get(ats, DEFAULT_SOURCE_RANK)


def prescore(j: Job, years: int | None = None) -> float:
    """Cheap mechanical promise score. Used for ONE thing: deciding what to
    drop when the candidate cap binds.

    `years` is the user's own experience, `experience.years` in filters.yaml.
    Without it the experience signal is neutral for every candidate.

    This is emphatically **not** a fit score and must never be used as one.
    Fit is the scorer's judgment against the rubric in profile.md, which
    nothing here can approximate, and mechanical ranking is known to sort
    unreachable prestige roles to the top. Every candidate that survives the
    cap is still scored in full by Stage 2.

    Until Indeed was added the cap never bound at all: the 2026-08-17 run
    produced 284 candidates against a cap of 500 and clipped nothing, so
    trimming order was moot. With the cap live, the previous rule -- newest
    first within each metro -- would drop good roles in favour of recent ones,
    which is arbitrary with respect to anything the user cares about.

    So the signals are only the ones already extracted, and all of them are
    about how well the candidate can be *scored*, not how good it is:
    """
    s = 0.0
    # Text is the scoring input. A snippet scores worse than a full posting
    # regardless of the underlying role.
    s += min(len(j.description), 6000) / 6000 * 3.0
    # A stated minimum the user clears, versus one they do not. Unknown sits
    # between the two -- absence of evidence, not evidence of a bad fit.
    if j.yoe_min is None or years is None:
        s += 1.0
    elif j.yoe_min <= years:
        s += 3.0
    elif j.yoe_min == years + 1:
        s += 2.0
    elif j.yoe_min == years + 2:
        s += 1.0
    # Disclosed comp above the floor is one less unknown.
    if j.comp_max is not None:
        s += 1.0
    # Prefer the copy whose text we trust, same ordering as dedupe.
    s += source_rank(j.ats) * 0.5
    # Matching several clusters means several routes to relevance.
    s += min(len(j.clusters), 3) * 0.5
    return s


# ------------------------------------------------------------------ storage

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  uid TEXT PRIMARY KEY, ats TEXT, company TEXT, token TEXT, job_id TEXT,
  title TEXT, location_raw TEXT, metro TEXT, is_remote INT, loc_penalty INT,
  url TEXT, posted_at TEXT, first_seen TEXT, last_seen TEXT,
  clusters TEXT, comp_min INT, comp_max INT, status TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_seen ON jobs(last_seen);
CREATE TABLE IF NOT EXISTS boards (
  ats TEXT, token TEXT, company TEXT, last_run TEXT, last_ok TEXT,
  consecutive_failures INT DEFAULT 0, last_count INT, list_hash TEXT,
  consecutive_empty INT DEFAULT 0,
  PRIMARY KEY (ats, token)
);
"""

# A board that reads fine but lists nothing, run after run, has usually moved:
# on 2026-11-02 Amplitude, Anyscale, ClickHouse, Confluent and four other
# employers with open roles read empty, and only unreadable boards were flagged.
EMPTY_RUNS_BEFORE_WARNING = 3


def open_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    # Databases made before consecutive_empty existed.
    if "consecutive_empty" not in {r[1] for r in con.execute("PRAGMA table_info(boards)")}:
        con.execute("ALTER TABLE boards ADD COLUMN consecutive_empty INT DEFAULT 0")
    return con


# ----------------------------------------------------------------- pipeline


@dataclass
class Stats:
    boards_ok: int = 0
    boards_failed: int = 0
    boards_empty: int = 0
    boards_unchanged: int = 0
    raw: int = 0
    seen_before: int = 0
    cut_title: int = 0
    cut_location: int = 0
    cut_age: int = 0
    cut_comp: int = 0
    detail_fetches: int = 0
    candidates: int = 0
    duplicates: int = 0
    adzuna_raw: int = 0
    usajobs_raw: int = 0
    jobspy_raw: int = 0
    cut_staffing: int = 0
    cut_blocked: int = 0
    cut_domain: int = 0
    cut_experience: int = 0
    enriched: int = 0
    cut_dead: int = 0
    clipped: int = 0


def load_companies(path: str) -> list[dict]:
    """Every board in the companies file. No file yet means no boards: a new
    profile may have no employers whose boards can be read, and the other
    sources still run."""
    if not os.path.exists(path):
        log(f"no {os.path.relpath(path, ROOT)} yet, so no company boards; "
            "add employers with scripts/detect_ats.py")
        return []
    d = yaml.safe_load(open(path, encoding="utf-8")) or {}
    out = list(d.get("companies") or []) + list(d.get("manual") or [])
    return [c for c in out if c.get("ats")]


def board_key(c: dict) -> str:
    return c.get("token") or c.get("tenant") or c.get("base") or c["name"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clusters", help="comma-separated cluster ids")
    ap.add_argument("--all-clusters", action="store_true")
    ap.add_argument("--companies", default=os.path.join(ROOT, "sources/companies.yaml"))
    ap.add_argument("--clusters-file", default=os.path.join(ROOT, "profile/clusters.yaml"))
    ap.add_argument("--filters", default=os.path.join(ROOT, "profile/filters.yaml"))
    ap.add_argument("--db", default=os.path.join(ROOT, "data/seen.sqlite"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "data"))
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--metros", default="",
                    help="comma-separated metro keys: search and keep only these, "
                         "this run (default: every metro in filters.yaml)")
    ap.add_argument("--remote", choices=scan_config.REMOTE_MODES,
                    help="override remote.mode from filters.yaml for this run")
    ap.add_argument("--ats", help="only boards on this ATS (debugging)")
    ap.add_argument("--limit-companies", type=int, default=0)
    ap.add_argument("--max-age-days", type=int)
    ap.add_argument("--no-enrich", action="store_true",
                    help="skip fetching full text for thin descriptions")
    ap.add_argument("--sources",
                    help="comma-separated sources for this run, overriding filters.yaml "
                         f"`sources`: {', '.join(SOURCES)}")
    ap.add_argument("--jobspy-results", type=int, default=400,
                    help="Indeed rows per (search term, metro) query")
    ap.add_argument("--ignore-seen", action="store_true",
                    help="do not skip previously-seen jobs (for tuning filters)")
    ap.add_argument("--dry-run", action="store_true", help="do not write to the DB")
    ap.add_argument("--preview", nargs="?", type=int, const=15, metavar="N",
                    help="show up to N titles each cluster lets through (default 15) and "
                         "the ones its excludes drop, then stop; writes nothing")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    filt = yaml.safe_load(open(args.filters, encoding="utf-8"))
    cl_cfg = yaml.safe_load(open(args.clusters_file, encoding="utf-8"))
    matcher = ClusterMatcher(cl_cfg)
    only_metros = {m.strip() for m in args.metros.split(",") if m.strip()} or None
    remote = scan_config.remote_mode(filt, args.remote)
    in_play = scan_config.metro_keys(filt, only_metros)   # unknown names stop here
    locres = LocationResolver(filt, only_metros=only_metros, mode=remote)
    # One search plan for every aggregator, so --metros and --remote reach them
    # all the same way.
    locations = scan_config.search_locations(filt, only=only_metros, mode=remote)
    gate = DomainGate(cl_cfg)
    all_ids = [c["id"] for c in cl_cfg["clusters"]]

    if args.all_clusters:
        active = set(all_ids)
    elif args.clusters:
        active = {c.strip() for c in args.clusters.split(",") if c.strip()}
        if active - set(all_ids):
            print(f"unknown cluster(s): {', '.join(sorted(active - set(all_ids)))}",
                  file=sys.stderr)
            print(f"available: {', '.join(all_ids)}", file=sys.stderr)
            return 2
    else:
        print("specify --clusters <ids> or --all-clusters", file=sys.stderr)
        print(f"available: {', '.join(all_ids)}", file=sys.stderr)
        return 2

    preview = (TitlePreview(matcher, locres, active, args.preview)
               if args.preview is not None else None)

    max_age = args.max_age_days or int(filt.get("max_age_days", 14))
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age)
    comp_cfg = filt.get("comp") or {}
    floor = int(comp_cfg.get("floor_usd", 0))
    min_hourly = int(comp_cfg.get("min_plausible_hourly", 15))
    cap = int(filt.get("max_candidates", 100))
    # How much of each posting the scorer reads. The pay and experience
    # filters read the whole posting either way.
    desc_chars = int(filt.get("max_description_chars", 6000))
    exp_cfg = filt.get("experience") or {}
    yoe_hard = int(exp_cfg.get("hard_max_years", 6))
    yoe_have = int(exp_cfg["years"]) if exp_cfg.get("years") is not None else None
    blocked = [b.lower() for b in filt.get("blocklist_companies") or []]
    # Applied to every posting, not just the board list: aggregators surface
    # staffing agencies reposting other companies' roles.
    staffing = [b.lower() for b in filt.get("blocklist_staffing") or []]

    sources, sources_from = chosen_sources(filt, args)
    scraped = [s for s in jobspy_source.SITES if s in sources]

    companies = load_companies(args.companies) if "boards" in sources else []
    companies = [c for c in companies if c["ats"] in SUPPORTED]
    if args.ats:
        companies = [c for c in companies if c["ats"] == args.ats]
    companies = [c for c in companies
                 if not any(b in c["name"].lower() for b in blocked)]
    if args.limit_companies:
        companies = companies[: args.limit_companies]

    con = open_db(args.db)
    known: set[str] = set()
    # A preview looks at everything currently posted, seen before or not.
    if not (args.ignore_seen or preview):
        known = {r[0] for r in con.execute("SELECT uid FROM jobs")}
    board_hashes = {(r[0], r[1]): r[2]
                    for r in con.execute("SELECT ats, token, list_hash FROM boards")}

    st = Stats()
    t0 = time.time()
    by_ats: dict[str, int] = {}
    for c in companies:
        by_ats[c["ats"]] = by_ats.get(c["ats"], 0) + 1
    log(f"clusters: {', '.join(sorted(active))}")
    log(f"boards: {len(companies)} ({', '.join(f'{k} {v}' for k, v in sorted(by_ats.items()))})")
    log(f"max age {max_age}d | comp floor ${floor:,} | cap {cap}")
    if remote == "only":
        log("metros: not searched | remote: only (nationwide remote search)")
    else:
        log(f"metros: {', '.join(in_play) or 'none'} | remote: {remote}")
    log(f"sources ({sources_from}): {', '.join(s for s in SOURCES if s in sources)}")
    if sources - {"boards"}:
        # A metro the aggregators cannot search is a coverage hole, not a
        # filter. Say so rather than let a thin digest look like a thin market.
        blind = scan_config.unsearchable_metros(filt, only_metros, remote)
        if blind:
            log(f"WARNING: no search_as for {', '.join(blind)} in filters.yaml; "
                "the aggregators cannot search there")

    def unasked(source: str, key: str) -> None:
        missing = scan_config.missing_terms(active, scan_config.cluster_terms(cl_cfg, key))
        if missing:
            log(f"{source}: no {key} for {', '.join(missing)} in clusters.yaml; "
                "nothing is asked for those clusters")

    survivors: list[Job] = []
    board_rows: list[tuple] = []
    now = iso(datetime.now(timezone.utc))

    # ---- the other sources start now, alongside the boards ------------------
    # Each is an independent host with its own pace, and none needs another's
    # results. On 2026-11-02 the boards took 72 s and only then did the scraped
    # boards start, which took minutes more. Their postings are still filtered
    # one source at a time, in a fixed order, once the boards are done.
    def timed(fetch, *a, **kw):
        started = time.time()
        return fetch(*a, **kw), time.time() - started

    def fetch_adzuna():
        import adzuna_source
        return adzuna_source.search(active, locations=locations, max_days=max_age,
                                    clusters_cfg=cl_cfg)

    background = ThreadPoolExecutor(max_workers=3)
    pending: dict[str, object] = {}
    board_status: dict = {}
    if "adzuna" in sources:
        unasked("adzuna", "search_terms")
        pending["adzuna"] = background.submit(timed, fetch_adzuna)
    if scraped:
        for key in scraped:
            label = jobspy_source.SITES[key]["label"]
            log(f"WARNING: scraping {label} because `sources` turns it on. Its terms "
                "prohibit scraping; this runs at your own risk, logged out.")
        unasked("scraped boards", "search_terms")
        pending["scraped boards"] = background.submit(
            timed, jobspy_source.search, active, locations=locations, max_days=max_age,
            results_wanted=args.jobspy_results, workers=args.workers, sites=scraped,
            verbose=args.verbose, clusters_cfg=cl_cfg, status=board_status)
    if "usajobs" in sources:
        unasked("usajobs", "usajobs_terms")
        try:
            import usajobs_source
            agencies, agencies_from = usajobs_source.agency_scope(filt)
            log(f"usajobs agencies ({agencies_from}): {', '.join(agencies) or 'all'}")
            pending["usajobs"] = background.submit(
                timed, usajobs_source.search, active, locations=locations,
                max_days=max_age, clusters_cfg=cl_cfg, agencies=agencies)
        except SystemExit as e:
            log(f"usajobs skipped: {e}")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(list_board, c): c for c in companies}
        done = 0
        for fut in as_completed(futs):
            c = futs[fut]
            jobs, ok, h = fut.result()
            done += 1
            if done % 25 == 0:
                log(f"  ...{done}/{len(companies)} boards", v=args.verbose)
            key = board_key(c)
            if not ok:
                st.boards_failed += 1
                board_rows.append((c["ats"], key, c["name"], now, None, 1, 0, None, 0))
                log(f"  ! unreadable: {c['name']} ({c['ats']})", v=args.verbose)
                continue
            st.boards_ok += 1
            if not jobs:
                st.boards_empty += 1
            if h and board_hashes.get((c["ats"], key)) == h:
                st.boards_unchanged += 1
            st.raw += len(jobs)
            board_rows.append((c["ats"], key, c["name"], now, now, 0, len(jobs), h,
                               0 if jobs else 1))

            for j in jobs:
                if preview:
                    preview.consider(j)
                    continue
                if not args.ignore_seen and j.uid in known:
                    st.seen_before += 1
                    continue
                hits = matcher.match(j.title, active)
                if not hits:
                    st.cut_title += 1
                    continue
                loc = locres.resolve(j.location_raw)
                if loc is None:
                    st.cut_location += 1
                    continue
                if j.posted_at:
                    try:
                        if datetime.fromisoformat(j.posted_at) < cutoff:
                            st.cut_age += 1
                            continue
                    except ValueError:
                        pass
                j.clusters = hits
                j.metro, j.is_remote, j.loc_penalty = loc
                survivors.append(j)

    log(f"phase A: {st.boards_ok} ok / {st.boards_failed} unreadable "
        f"({st.boards_empty} empty, {st.boards_unchanged} unchanged) | "
        f"{st.raw} raw -> {len(survivors)} survivors [{time.time()-t0:.1f}s]")

    # ---- supplementary sources -------------------------------------------
    # Both run through the identical filter chain below. Nothing here bypasses
    # the metro allowlist, comp floor, title regex, or seniority rules -- a
    # source that skipped them would quietly widen the search, which is the one
    # thing profile.md forbids outright.
    def absorb(jobs: list[Job]) -> int:
        kept = 0
        for j in jobs:
            if not args.ignore_seen and j.uid in known:
                st.seen_before += 1
                continue
            if any(b in j.company.lower() for b in staffing):
                st.cut_staffing += 1
                continue
            # blocklist_companies was only ever applied to the board list, so
            # an aggregator could surface a blocked employer freely -- while
            # that list held sixteen oil and gas majors, Adzuna was returning
            # them. Applied to every source now.
            if any(b in j.company.lower() for b in blocked):
                st.cut_blocked += 1
                continue
            if preview:
                preview.consider(j)
                continue
            hits = matcher.match(j.title, active)
            if not hits:
                st.cut_title += 1
                continue
            loc = locres.resolve(j.location_raw)
            if loc is None:
                st.cut_location += 1
                continue
            if too_old(j.posted_at, cutoff):
                st.cut_age += 1
                continue
            j.clusters = hits
            j.metro, j.is_remote, j.loc_penalty = loc
            survivors.append(j)
            kept += 1
        return kept

    # Adzuna reaches employers whose ATS we cannot read (iCIMS, Oracle HCM,
    # Taleo, Phenom, Avature) -- where most entry-to-mid energy project
    # engineering actually lives.
    #
    # The scraped boards reach the same unreadable-ATS half, and return the
    # whole posting rather than a snippet, so the experience gate -- the filter
    # feedback.md says decided ten of sixteen skips -- runs at full strength
    # with no phase C fetch. They are scraped, against their terms, so each
    # runs only when the profile turns it on, and says so.
    #
    # USAJOBS covers the federal agencies named in `usajobs_agencies` in
    # filters.yaml. It returns the whole posting too. It does NOT reach the
    # national labs: those are contractor-operated, so their jobs are on the
    # lab's own board rather than USAJOBS.
    for name, fut in pending.items():
        try:
            jobs, took = fut.result()
        except SystemExit as e:
            log(f"{name} skipped: {e}")
            continue
        if name == "scraped boards":
            for line in board_status.values():
                log(f"  {line}")
        raw = len(jobs)
        if name == "adzuna":
            st.adzuna_raw = raw
        elif name == "usajobs":
            st.usajobs_raw = raw
        else:
            st.jobspy_raw = raw
        log(f"{name}: {raw} raw -> {absorb(jobs)} survivors [{took:.1f}s]")
    background.shutdown()

    if preview:
        preview.report()
        return 0

    need = [j for j in survivors if not j.description]
    if need:
        started = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(fetch_detail, need))
        st.detail_fetches = len(need)
        log(f"phase B: {len(need)} detail fetches [{time.time() - started:.1f}s]")

    # ---- phase C: enrich thin descriptions --------------------------------
    # The aggregator returns ~539-character snippets, and 224 of its 226
    # candidates reached the last digest with no stated years-of-experience at
    # all -- the one factor feedback.md says decided ten of sixteen skips. So
    # the experience gate below was running blind on 80% of the list.
    #
    # Following the posting URL recovers the real text (75% yield on a sample of
    # twelve) and identifies listings that are already dead, which were a
    # quarter of the last skip list. Runs after the cheap filters so nothing is
    # fetched for a candidate that was going to be cut anyway.
    if not args.no_enrich:
        # Not the scraped boards: following their posting URLs would be more
        # scraping, outside the pacing jobspy_source holds them to.
        thin = [j for j in survivors
                if len(j.description) < THIN_DESCRIPTION and j.url
                and j.ats not in jobspy_source.SCRAPED_ATS]
        if thin:
            log(f"phase C: enriching {len(thin)} thin descriptions")
            started = time.time()
            try:
                import fetch_posting

                def _enrich(job):
                    text, _meta, status = fetch_posting.fetch_description(
                        job.url, timeout=20, min_chars=THIN_DESCRIPTION)
                    return job, text, status

                dead: set[str] = set()
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    for job, text, status in pool.map(_enrich, thin):
                        if status == "dead":
                            dead.add(job.uid)
                        elif text and len(text) > len(job.description):
                            job.description = text
                            st.enriched += 1
                if dead:
                    survivors = [j for j in survivors if j.uid not in dead]
                    st.cut_dead = len(dead)
                log(f"phase C: {st.enriched} enriched, {st.cut_dead} already dead "
                    f"[{time.time() - started:.1f}s]")
            except Exception as e:
                # Never let enrichment sink a scan -- the snippets still work,
                # they just score worse.
                log(f"phase C skipped: {type(e).__name__}: {e}")

    # Workday's detail fetch replaces a relative "Posted 5 Days Ago" with a real
    # ISO date, so the age cut is re-applied to anything it corrected.
    candidates: list[Job] = []
    for j in survivors:
        if too_old(j.posted_at, cutoff):
            st.cut_age += 1
            continue
        if j.comp_max is None:
            j.comp_min, j.comp_max = parse_comp(j.description, min_hourly)
        if j.comp_max is not None and j.comp_max < floor:
            st.cut_comp += 1
            continue

        # Runs here, after phase C, so every description is as complete as it
        # is going to get. Curated boards are exempt -- see DomainGate.
        kept_clusters = [c for c in j.clusters
                         if gate.keep(c, j.ats, j.title, j.description)]
        if not kept_clusters:
            st.cut_domain += 1
            continue
        j.clusters = kept_clusters

        j.yoe_min, j.yoe_max = parse_years_required(j.description)
        # Drop only clearly out-of-reach roles. Everything else passes through
        # with yoe_min attached so the scorer can weigh it -- and so it can
        # apply the prestige rule from feedback.md, which is a judgment call a
        # regex cannot make.
        if j.yoe_min is not None and j.yoe_min >= yoe_hard:
            st.cut_experience += 1
            continue
        j.recruiter = posted_by_recruiter(j.description)
        candidates.append(j)

    # Large employers post the same requisition several times under different
    # IDs -- PG&E listed "Civil Project Engineer" and "Substation Project
    # Engineer" twice each in one run. They are genuinely separate reqs, but
    # they read as duplicates in a digest and cost scoring tokens twice, so
    # collapse them and record the count.
    collapsed: dict[tuple, Job] = {}
    for j in candidates:
        key = (j.company.lower(), re.sub(r"\W+", " ", j.title.lower()).strip(), j.metro)
        if key in collapsed:
            st.duplicates += 1
            prev = collapsed[key]
            # Keep the copy with the best text -- see SOURCE_RANK. With two
            # aggregators in play this has to be an ordering, not the binary
            # "anything beats Adzuna" rule it replaced. Ties break on the
            # longer description, which is what scoring actually consumes.
            better = (source_rank(j.ats), len(j.description)) > \
                     (source_rank(prev.ats), len(prev.description))
            if better:
                j.duplicate_count = prev.duplicate_count + 1
                collapsed[key] = j
            else:
                prev.duplicate_count += 1
        else:
            j.duplicate_count = 1
            collapsed[key] = j
    candidates = list(collapsed.values())

    # Trimming to the cap is a sampling problem, not a sort. Sorting by any
    # single key lets one group monopolize: `-loc_penalty` reversed put the
    # WORST metros first and returned only Boston and LA; fixing the sign
    # flipped it to 100% Bay Area. Both throw away whole metros.
    #
    # So allocate round-robin across metros in preference order, newest first
    # within each. Bay Area still wins most slots because it has the most
    # candidates and goes first each pass, but New York, Chicago, Seattle, LA
    # and Boston are all represented instead of being cut wholesale.
    if len(candidates) > cap:
        buckets: dict[tuple[int, str], list[Job]] = {}
        for j in candidates:
            buckets.setdefault((j.loc_penalty, j.metro or "remote"), []).append(j)
        for b in buckets.values():
            # Most promising first within each metro, recency as the tiebreak.
            # See prescore() -- this decides only what is lost to the cap.
            b.sort(key=lambda j: (prescore(j, yoe_have), j.posted_at or ""),
                   reverse=True)
        order = sorted(buckets, key=lambda k: -k[0])      # penalty 0 first
        picked: list[Job] = []
        while len(picked) < cap and any(buckets[k] for k in order):
            for k in order:
                if buckets[k] and len(picked) < cap:
                    picked.append(buckets[k].pop(0))
        st.clipped = len(candidates) - len(picked)
        candidates = picked
    candidates.sort(key=lambda j: (j.loc_penalty, j.posted_at or ""), reverse=True)
    st.candidates = len(candidates)

    if not args.dry_run:
        cand_uids = {j.uid for j in candidates}
        rows = [(
            j.uid, j.ats, j.company, j.token, j.job_id, j.title, j.location_raw,
            j.metro, int(j.is_remote), j.loc_penalty, j.url, j.posted_at, now, now,
            ",".join(j.clusters), j.comp_min, j.comp_max,
            "candidate" if j.uid in cand_uids else "filtered",
        ) for j in survivors]
        con.executemany(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(uid) DO UPDATE SET last_seen=excluded.last_seen", rows)
        con.executemany(
            "INSERT INTO boards (ats, token, company, last_run, last_ok, "
            "consecutive_failures, last_count, list_hash, consecutive_empty) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(ats,token) DO UPDATE SET last_run=excluded.last_run, "
            "last_ok=COALESCE(excluded.last_ok, boards.last_ok), "
            "consecutive_failures=CASE WHEN excluded.last_ok IS NULL "
            "  THEN boards.consecutive_failures+1 ELSE 0 END, "
            "consecutive_empty=CASE WHEN excluded.last_ok IS NULL "
            "  THEN boards.consecutive_empty "
            "  WHEN excluded.consecutive_empty = 1 THEN boards.consecutive_empty+1 ELSE 0 END, "
            "last_count=excluded.last_count, list_hash=excluded.list_hash", board_rows)
        con.commit()

    stale = con.execute(
        "SELECT company, ats, token, consecutive_failures FROM boards "
        "WHERE consecutive_failures >= 3 ORDER BY consecutive_failures DESC").fetchall()
    empty = con.execute(
        "SELECT company, ats, token, consecutive_empty FROM boards "
        "WHERE consecutive_empty >= ? ORDER BY consecutive_empty DESC",
        (EMPTY_RUNS_BEFORE_WARNING,)).fetchall()

    os.makedirs(args.out_dir, exist_ok=True)
    outpath = os.path.join(args.out_dir,
                           f"candidates-{datetime.now().strftime('%Y-%m-%d')}.json")
    with open(outpath, "w", encoding="utf-8") as fh:
        json.dump({
            "generated_at": now,
            "clusters": sorted(active),
            "stats": asdict(st),
            "stale_boards": [{"company": r[0], "ats": r[1], "token": r[2],
                              "failures": r[3]} for r in stale],
            "empty_boards": [{"company": r[0], "ats": r[1], "token": r[2],
                              "empty_runs": r[3]} for r in empty],
            "candidates": [
                {k: v for k, v in asdict(j).items() if k not in ("description", "detail_path")}
                | {"description": j.description[:desc_chars]} for j in candidates],
        }, fh, indent=1, ensure_ascii=False)
    # /job-scan offers the last run's targeting as the default for the next.
    if not args.dry_run:
        with open(os.path.join(args.out_dir, "last-run.json"), "w", encoding="utf-8") as fh:
            json.dump({
                "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "clusters": sorted(active),
                "metros": [] if remote == "only" else list(in_play),
                "remote": remote,
                "sources": [s for s in SOURCES if s in sources],
            }, fh, indent=1)

    log("")
    log(f"raw {st.raw} | seen {st.seen_before} | cut: title {st.cut_title} "
        f"loc {st.cut_location} age {st.cut_age} comp {st.cut_comp} "
        f"staffing {st.cut_staffing} blocked {st.cut_blocked} domain {st.cut_domain} "
        f"yoe {st.cut_experience} dead {st.cut_dead} "
        f"dup {st.duplicates} | enriched {st.enriched}")
    log(f"CANDIDATES: {st.candidates}" + (f"  (clipped {st.clipped})" if st.clipped else ""))
    if stale:
        log(f"WARNING: {len(stale)} board(s) failing 3+ runs: "
            f"{', '.join(r[0] for r in stale[:6])}")
    if empty:
        log(f"WARNING: {len(empty)} board(s) empty {EMPTY_RUNS_BEFORE_WARNING}+ runs in a "
            f"row, probably moved -- re-check with detect_ats.py: "
            f"{', '.join(r[0] for r in empty[:8])}")
    log(f"-> {outpath}  [{time.time()-t0:.1f}s total]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

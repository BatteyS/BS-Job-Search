"""The big job boards -- Indeed, LinkedIn, Glassdoor, ZipRecruiter -- via JobSpy.

At your own risk
----------------
All four boards' terms prohibit scraping, and this module scrapes them. So each
one is off until the user turns it on in profile/filters.yaml `sources`, and
fetch_jobs prints a warning every time one runs. That was decided 2026-10-29,
replacing an outright LinkedIn exclusion. Two things limit the risk, and
neither is a setting:

  * Nothing here logs in. JobSpy reads each board's public, logged-out job
    search, so no account is involved -- the account risk was the original
    reason LinkedIn was excluded.
  * Each board is queried at a fixed, polite pace (SITES below). A board that
    starts refusing requests gets one cool-off and is then dropped for the rest
    of the run, never retried harder. One whose queries keep failing for any
    other reason is dropped too. There is no proxy support, on purpose.

The settings are the same for every user, so a scan behaves the same for
everyone out of the box.

Why these boards
----------------
`sources/companies.yaml` reaches employers whose ATS we can read. Measured on
the 2026-08-17 scan, that was 21 distinct employers out of 183 curated tokens.
Roughly half of established employers sit on Oracle HCM, Taleo, Avature,
Eightfold, UKG, Phenom or iCIMS, none of which is readable from Python.

Adzuna covers part of that gap with ~539-character snippets. Indeed returns the
whole posting. Measured on the probe of 2026-08-19, over three metros and four
search terms:

    1,177 raw rows in 19s (serial, 12 queries)   ->  89 candidates
    67 distinct employers
    median description 6,436 chars; 1 of 1,020 under 1,200 chars
    years-of-experience extracted on 83 of 124 (67%)

That last number is the point: stated years-of-experience decided ten of
sixteen skips on the first digest (profile/feedback.md), and the gate can only
run on text we actually hold. Indeed also reached the contractor-operated
national labs USAJOBS cannot -- Fermilab and Lawrence Livermore both surfaced.
Because queries are issued per metro, the metro allowlist only cuts ~14% of
title matches here versus 47% on the boards.

LinkedIn, Glassdoor and ZipRecruiter reach the same unreadable-ATS half with
different coverage. LinkedIn's search results carry no description, so it
fetches each posting's page, at one extra request per row.

Google
------
JobSpy's Google-for-Jobs scraper returned zero rows on all 15 probe queries on
2026-08-19, and JobSpy's own README now says Google Jobs is currently
unavailable. Not wired up; it belongs in SITES if that changes.

Install
-------
JobSpy needs Python 3.10 or newer. Its published pins (`regex<2025`,
`NUMPY==1.26.3`, `tls-client<2.0`, `markdownify<0.14`) also do not resolve on
Python 3.14 -- see README.md for the working install.

    python scripts/jobspy_source.py --clusters <id> --sites indeed --limit 5
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import logging
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scan_config  # noqa: E402
from ats_adapters import Job  # noqa: E402

# Per-board settings, the same for every user. Keys are the names used in
# filters.yaml `sources`; `jobspy` is the name JobSpy uses, which is also the
# `ats` each posting carries.
#
#   results      rows asked for per query
#   serial       one query at a time, `pause` seconds apart; False runs them
#                concurrently, for a board that does not rate-limit
#   max_queries  a cap per run. Queries are ordered so a capped board still
#                covers every cluster and metro: each cluster's first search
#                term everywhere, then its second, and so on.
SITES = {
    # Indeed has no rate limit (JobSpy README). It stops returning new rows well
    # before 400; the broadest probe query ("project engineer energy", Bay Area)
    # topped out at 311.
    "indeed": {"jobspy": "indeed", "label": "Indeed", "results": 400,
               "serial": False},
    # LinkedIn answers bursts with a 429 that clears within about a minute, and
    # every row costs one more request for its description. 25 rows keeps a
    # query to ~26 requests; 40 queries covers the first search term of six
    # clusters in seven metros.
    "linkedin": {"jobspy": "linkedin", "label": "LinkedIn", "results": 25,
                 "serial": True, "pause": 5.0, "max_queries": 40,
                 "fetch_description": True},
    # Glassdoor rate-limits above about 2 requests a second. Without
    # fetch_description, JobSpy 1.4 returns its postings with no text at all,
    # and with it every row costs a request, so rows are kept to LinkedIn's 25.
    "glassdoor": {"jobspy": "glassdoor", "label": "Glassdoor", "results": 25,
                  "serial": True, "pause": 2.0, "max_queries": 60,
                  "fetch_description": True},
    # US and Canada only, and it reads only the location. Rows as Glassdoor.
    "ziprecruiter": {"jobspy": "zip_recruiter", "label": "ZipRecruiter",
                     "results": 25, "serial": True, "pause": 2.0,
                     "max_queries": 60, "fetch_description": True},
}

# The `ats` values postings from these boards carry.
SCRAPED_ATS = frozenset(s["jobspy"] for s in SITES.values())

# A board that refuses a query gets one wait this long -- LinkedIn's blocks
# clear within about a minute -- and the query is retried once. A second
# refusal drops the board for the rest of the run: the next scan is the retry.
COOL_OFF_SECONDS = 65

# An error that is not a refusal -- a rejected query, a location the board
# cannot parse -- does not clear with a wait. On 2026-11-02 Glassdoor answered
# all six Bay Area queries with HTTP 400, "location not parsed", and the run
# asked six times. Two failed queries in a row now drop a board for the run.
ERRORS_BEFORE_STOP = 2

# Miles. Matches adzuna_source's `distance: 40`.
RADIUS_MILES = 40

HOURLY_HOURS_PER_YEAR = 2080


class _Errors(logging.Handler):
    """Counts the errors JobSpy logs for one board, and which of them say the
    board refused a request.

    JobSpy does not raise when a board blocks it or rejects a query; it logs an
    error and returns what it has, so a failure shows only in its log. Best
    effort: JobSpy names its loggers "JobSpy:<Board>" (1.1) or after the
    scraper's module, "jobspy.<board>" (1.4). If that changes again this sees
    nothing, and only raised errors count.
    """

    REFUSAL = re.compile(r"\b(429|403|blocked|rate.?limit\w*|too many requests)\b", re.I)

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.count = 0          # every error
        self.refusals = 0       # the errors that say the board refused
        self.last = ""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:                               # noqa: BLE001
            return
        self.count += 1
        self.last = msg
        if self.REFUSAL.search(msg):
            self.refusals += 1


def _s(v) -> str:
    """pandas hands back NaN for missing cells; treat those as empty."""
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    return str(v).strip()


def _annual(amount, interval: str) -> int | None:
    try:
        v = float(amount)
    except (TypeError, ValueError):
        return None
    if v <= 0 or math.isnan(v):
        return None
    if interval == "hourly":
        v *= HOURLY_HOURS_PER_YEAR
    elif interval == "monthly":
        v *= 12
    elif interval == "weekly":
        v *= 52
    elif interval == "daily":
        v *= 260
    return int(v)


def to_job(row, site: str, metro_hint: str) -> Job | None:
    jid = _s(row.get("id")) or _s(row.get("job_url"))
    title = _s(row.get("title"))
    company = _s(row.get("company"))
    if not (jid and title and company):
        return None

    city, state = _s(row.get("city")), _s(row.get("state"))
    loc = ", ".join(p for p in (city, state) if p) or _s(row.get("location"))
    is_remote = bool(row.get("is_remote"))
    if is_remote and "remote" not in loc.lower():
        loc = f"{loc}, Remote" if loc else "Remote"

    j = Job(
        uid=hashlib.sha1(f"{site}:{jid}".encode()).hexdigest()[:16],
        ats=site,
        company=company,
        token=site,
        job_id=jid,
        title=title,
        location_raw=loc or metro_hint,
        url=_s(row.get("job_url")),
        posted_at=_s(row.get("date_posted")) or None,
    )
    j.description = _s(row.get("description"))
    j.is_remote = is_remote

    interval = _s(row.get("interval")).lower()
    j.comp_min = _annual(row.get("min_amount"), interval)
    j.comp_max = _annual(row.get("max_amount"), interval)
    return j


def _accepts(fn, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _ranked(tasks, clusters, terms: dict[str, list[str]]):
    """Each cluster's first term in every metro, then its second, and so on."""
    rank: dict[str, int] = {}
    for c in clusters:
        for i, t in enumerate(terms.get(c, [])):
            rank[t] = min(rank.get(t, i), i)
    return sorted(tasks, key=lambda t: (rank.get(t[0], 0), t[1], t[0]))


def _board(key: str, scrape_jobs, tasks, hours_old: int, results: int,
           workers: int, verbose: bool) -> tuple[list[Job], str]:
    """Run one board's queries. Returns its postings and a status line."""
    cfg = SITES[key]
    site, label = cfg["jobspy"], cfg["label"]
    extra = {}
    if cfg.get("fetch_description"):
        # JobSpy 1.4 calls this fetch_description and applies it to every board;
        # older releases knew it only as linkedin_fetch_description.
        if _accepts(scrape_jobs, "fetch_description"):
            extra["fetch_description"] = True
        elif key == "linkedin":
            extra["linkedin_fetch_description"] = True
    planned = len(tasks)
    cap = cfg.get("max_queries")
    if cap and planned > cap:
        tasks = tasks[:cap]

    errors = _Errors()
    # JobSpy 1.1 logs as "JobSpy:LinkedIn", 1.4 under its scraper's module,
    # "jobspy.linkedin". Listening to both keeps either release's errors visible.
    loggers = [logging.getLogger(f"JobSpy:{label}"),
               logging.getLogger(f"jobspy.{site.replace('_', '')}")]
    for logger in loggers:
        logger.addHandler(errors)

    def attempt(task) -> tuple[list[Job], bool, bool]:
        """(postings, whether the board refused, whether it logged any error)."""
        term, mkey, place = task
        if mkey == scan_config.NATIONWIDE:
            # Remote work has no place to search around; ask for remote
            # postings nationwide instead.
            where, hint = {"is_remote": True}, ""
        else:
            where, hint = {"location": place, "distance": RADIUS_MILES}, place
        before, refused_before = errors.count, errors.refusals
        try:
            df = scrape_jobs(site_name=[site], search_term=term,
                             results_wanted=results, hours_old=hours_old,
                             country_indeed="USA", description_format="markdown",
                             verbose=0, **where, **extra)
        except Exception as e:                          # noqa: BLE001
            if verbose:
                print(f"  ! {label}/{mkey}/{term}: {type(e).__name__}: {e}",
                      file=sys.stderr)
            return [], True, True
        rows = [] if df is None or df.empty else [
            j for j in (to_job(r, site, hint) for _, r in df.iterrows()) if j]
        if verbose:
            print(f"  {label:12} {mkey:12} {term:34} {len(rows):4}", file=sys.stderr)
        return rows, errors.refusals > refused_before, errors.count > before

    out: list[Job] = []
    done, failed, stopped = 0, 0, ""
    started = time.time()
    try:
        if not cfg["serial"]:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for rows, _, errored in pool.map(attempt, tasks):
                    out += rows
                    done += 1
                    failed += errored and not rows
        else:
            cooled, in_a_row = False, 0
            for i, task in enumerate(tasks):
                if i:
                    time.sleep(cfg["pause"])
                rows, refused, errored = attempt(task)
                out += rows
                if refused and not cooled:
                    cooled = True
                    time.sleep(COOL_OFF_SECONDS)
                    rows, refused, errored = attempt(task)
                    out += rows
                if refused:
                    stopped = "refused"
                    break
                done += 1
                failed += errored and not rows
                in_a_row = in_a_row + 1 if errored and not rows else 0
                if in_a_row >= ERRORS_BEFORE_STOP:
                    stopped = "errors"
                    break
    finally:
        for logger in loggers:
            logger.removeHandler(errors)

    # Timed, because the slowest board sets the scan's pace and nothing else
    # would show which one that is.
    status = f"{label}: {done} of {planned} queries in {time.time() - started:.0f}s"
    if cap and planned > cap:
        status += f" (capped at {cap} per run)"
    if stopped == "refused":
        status += f"; stopped because {label} refused requests -- the next scan retries"
    elif stopped == "errors":
        status += (f"; stopped after {ERRORS_BEFORE_STOP} failed queries in a row "
                   f"({errors.last}) -- the next scan retries")
    elif failed:
        status += f"; {failed} failed ({errors.last})"
    return out, status


def search(clusters: set[str], locations: dict[str, list[str]] | None = None,
           max_days: int = 14, results_wanted: int | None = None,
           workers: int = 4, sites=("indeed",), verbose: bool = False,
           clusters_cfg: dict | None = None,
           status: dict | None = None) -> list[Job]:
    """Fetch across (search term x place) on each board in `sites`.

    Contract matches adzuna_source.search so fetch_jobs can absorb the result
    through the identical filter chain. Nothing here applies a filter of its
    own -- a source that pre-filtered would quietly widen or narrow the search
    outside the one place those rules are allowed to live.

    `results_wanted` overrides Indeed's rows per query (--jobspy-results). Each
    board's status line lands in `status`, keyed by board.
    """
    unknown = [s for s in sites if s not in SITES]
    if unknown:
        raise SystemExit(f"jobspy_source: unknown board(s) {', '.join(unknown)}; "
                         f"supported: {', '.join(SITES)}")
    try:
        from jobspy import scrape_jobs
    except ImportError as e:
        raise SystemExit(
            f"jobspy_source: python-jobspy is not installed ({e}). "
            "It needs Python 3.10+; see README.md for the install."
        ) from e

    if locations is None:
        locations = scan_config.search_locations(
            scan_config.load_yaml(scan_config.FILTERS_YAML))
    if clusters_cfg is None:
        clusters_cfg = scan_config.load_yaml(scan_config.CLUSTERS_YAML)
    terms = scan_config.cluster_terms(clusters_cfg)
    tasks = scan_config.plan_queries(clusters, terms, locations)
    hours_old = max(1, int(max_days) * 24)
    if not tasks:
        return []

    def run(key: str) -> tuple[str, list[Job], str]:
        cfg = SITES[key]
        board_tasks = _ranked(tasks, clusters, terms) if cfg.get("max_queries") else tasks
        results = results_wanted if (key == "indeed" and results_wanted) else cfg["results"]
        jobs, line = _board(key, scrape_jobs, board_tasks, hours_old, results,
                            workers, verbose)
        return key, jobs, line

    # Boards are independent hosts with their own limits, so each runs in its
    # own thread and the slow, paced ones overlap rather than queue.
    seen: dict[str, Job] = {}
    with ThreadPoolExecutor(max_workers=len(sites)) as pool:
        for key, jobs, line in pool.map(run, list(sites)):
            if status is not None:
                status[key] = line
            for j in jobs:
                # Same requisition across queries and metros -- keep the first,
                # which is the one whose metro query actually matched it.
                seen.setdefault(j.uid, j)
    return list(seen.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clusters", required=True,
                    help="comma-separated cluster ids")
    ap.add_argument("--sites", default="indeed",
                    help=f"comma-separated boards: {', '.join(SITES)}")
    ap.add_argument("--metros", default="",
                    help="comma-separated metro keys (default: all in filters.yaml)")
    ap.add_argument("--remote", choices=scan_config.REMOTE_MODES,
                    help="override remote.mode from filters.yaml")
    ap.add_argument("--max-days", type=int, default=14)
    ap.add_argument("--limit", type=int, default=10,
                    help="how many to print")
    args = ap.parse_args()

    cl = {c.strip() for c in args.clusters.split(",") if c.strip()}
    me = {m.strip() for m in args.metros.split(",") if m.strip()} or None
    sites = [s.strip() for s in args.sites.split(",") if s.strip()]
    locations = scan_config.search_locations(
        scan_config.load_yaml(scan_config.FILTERS_YAML), only=me, mode=args.remote)
    status: dict = {}
    jobs = search(cl, locations=locations, max_days=args.max_days, sites=sites,
                  verbose=True, status=status)
    for line in status.values():
        print(line, file=sys.stderr)
    print(f"\n{len(jobs)} unique postings", file=sys.stderr)
    for j in jobs[:args.limit]:
        comp = f" ${j.comp_max:,}" if j.comp_max else ""
        print(f"  [{j.ats}] {j.company} - {j.title} ({j.location_raw}){comp} "
              f"[{len(j.description)} chars]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""USAJOBS as a supplementary source, scoped to the agencies the profile names.

Unblocked 2026-08-18, when government and national labs stopped being a hard
pass in profile.md. Free API, and unlike every other source here it returns the
*whole* posting -- summary, duties, and qualifications -- so the experience gate
works on these without needing the phase C enrichment fetch.

WHAT THIS DOES NOT REACH, despite the name:

  The national labs. NREL, LBNL, Argonne, PNNL, and the rest are FFRDCs run by
  contractors -- Alliance for Sustainable Energy runs NREL, UC runs LBNL -- so
  their staff are contractor employees, not federal ones, and their jobs are on
  the lab's own board rather than USAJOBS. NREL is on iCIMS, which we cannot
  read. USAJOBS gets DOE proper, EPA, and the other agencies; the labs still
  arrive only if Adzuna happens to syndicate them.

  That is worth stating plainly because the reverse is easy to assume, and
  was assumed when this source was first proposed.

Agency scope is profile data: `usajobs_agencies` in profile/filters.yaml.
USAJOBS returns every federal posting matching a keyword, including plenty from
agencies the profile has no interest in, so results are kept only when the
hiring department matches one of those substrings. An empty list keeps every
agency and leaves the cluster title regexes to do the filtering.

The search words are per cluster too, as `usajobs_terms` in clusters.yaml, and
the places come from each metro's `search_as` -- see scan_config.py.

Credentials are free: register at https://developer.usajobs.gov/APIRequest/
Put them in sources/usajobs.local.yaml (gitignored) or USAJOBS_EMAIL /
USAJOBS_API_KEY.

    python scripts/usajobs_source.py --clusters <id> --limit 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_config  # noqa: E402
from ats_adapters import Job, strip_html  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDS = os.path.join(ROOT, "sources/usajobs.local.yaml")
CREDS_EXAMPLE = os.path.join(ROOT, "sources/usajobs.example.yaml")
BASE = "https://data.usajobs.gov/api/search"

# USAJOBS matches LocationName against full state names ("Boston,
# Massachusetts"). Metros give `search_as` the way the other sources take it
# ("Boston, MA"), so the abbreviation is expanded here.
STATE_NAMES = scan_config.STATE_NAMES

HOURS_PER_YEAR = 2080


def usajobs_place(place: str) -> str:
    """'Boston, MA' -> 'Boston, Massachusetts'. Anything else passes through."""
    m = re.match(r"^(.*?),\s*([A-Za-z]{2})$", place.strip())
    if m and m.group(2).upper() in STATE_NAMES:
        return f"{m.group(1).strip()}, {STATE_NAMES[m.group(2).upper()]}"
    return place


def load_creds() -> tuple[str, str]:
    email = os.environ.get("USAJOBS_EMAIL", "")
    key = os.environ.get("USAJOBS_API_KEY", "")
    if os.path.exists(CREDS):
        c = yaml.safe_load(open(CREDS, encoding="utf-8")) or {}
        email = email or str(c.get("email", "") or "")
        key = key or str(c.get("api_key", "") or "")
    if not (email and key):
        raise SystemExit(
            "USAJOBS credentials not found.\n"
            "  Register (free) at https://developer.usajobs.gov/APIRequest/\n"
            f"  then copy {os.path.relpath(CREDS_EXAMPLE, ROOT)} to "
            f"{os.path.relpath(CREDS, ROOT)} and fill in email / api_key.\n"
            "  Or set USAJOBS_EMAIL and USAJOBS_API_KEY."
        )
    return email, key


def agency_scope(filters: dict) -> tuple[list[str], str]:
    """The agency substrings to keep, and where they came from.

    `usajobs_agencies` in filters.yaml wins, and an empty list there means every
    agency. Before 2026-10-29 the list lived beside the API key in
    sources/usajobs.local.yaml, so that file is still read when filters.yaml
    names none -- the list is a preference, not a secret, and belongs with the
    rest of the profile.
    """
    if "usajobs_agencies" in filters:
        return ([str(a).lower() for a in (filters.get("usajobs_agencies") or [])],
                "profile/filters.yaml")
    if os.path.exists(CREDS):
        c = yaml.safe_load(open(CREDS, encoding="utf-8")) or {}
        legacy = [str(a).lower() for a in (c.get("agencies") or [])]
        if legacy:
            return legacy, os.path.relpath(CREDS, ROOT)
    return [], "none set"


def _get(url: str, email: str, key: str, retries: int = 3) -> dict | None:
    headers = {"Host": "data.usajobs.gov", "User-Agent": email,
               "Authorization-Key": key}
    delay = 1.0
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=25) as r:
                if r.status != 200:
                    return None
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 401/403 mean the key or the registered email is wrong; retrying
            # cannot fix that and USAJOBS rate-limits repeat auth failures.
            if e.code in (401, 403):
                body = e.read().decode("utf-8", "ignore")[:200]
                raise SystemExit(f"USAJOBS auth failed ({e.code}): {body}")
            if attempt == retries - 1:
                return None
            time.sleep(delay * (3 if e.code == 429 else 1))
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(delay)
        delay *= 2
    return None


def annual_pay(remuneration: list) -> tuple[int | None, int | None]:
    """Federal pay is banded and always disclosed. Hourly rates are annualized
    so the $80k floor in filters.yaml compares like with like."""
    lo = hi = None
    for r in remuneration or []:
        try:
            a = float(r.get("MinimumRange") or 0)
            b = float(r.get("MaximumRange") or 0)
        except (TypeError, ValueError):
            continue
        if (r.get("RateIntervalCode") or "").upper() == "PH":
            a, b = a * HOURS_PER_YEAR, b * HOURS_PER_YEAR
        if a > 0:
            lo = a if lo is None else min(lo, a)
        if b > 0:
            hi = b if hi is None else max(hi, b)
    return (int(lo) if lo else None, int(hi) if hi else None)


def to_job(item: dict, agencies: list[str]) -> Job | None:
    d = item.get("MatchedObjectDescriptor") or {}
    jid = str(item.get("MatchedObjectId") or d.get("PositionID") or "")
    title = (d.get("PositionTitle") or "").strip()
    if not (jid and title):
        return None

    dept = (d.get("DepartmentName") or "").strip()
    org = (d.get("OrganizationName") or "").strip()
    haystack = f"{dept} {org}".lower()
    if agencies and not any(a in haystack for a in agencies):
        return None

    locs = d.get("PositionLocation") or []
    loc = (locs[0].get("LocationName") if locs else "") or ""

    j = Job(
        uid=hashlib.sha1(f"usajobs:{jid}".encode()).hexdigest()[:16],
        ats="usajobs", company=org or dept, token="usajobs", job_id=jid,
        title=strip_html(title), location_raw=loc,
        url=d.get("PositionURI") or "",
        posted_at=(d.get("PublicationStartDate") or None),
    )

    details = (d.get("UserArea") or {}).get("Details") or {}
    duties = details.get("MajorDuties") or []
    if isinstance(duties, str):
        duties = [duties]
    parts = [d.get("QualificationSummary") or "",
             details.get("JobSummary") or "",
             "\n".join(str(x) for x in duties),
             details.get("Requirements") or ""]
    j.description = strip_html("\n\n".join(p for p in parts if p)).strip()

    j.comp_min, j.comp_max = annual_pay(d.get("PositionRemuneration"))
    return j


def search(clusters: set[str], locations: dict[str, list[str]] | None = None,
           max_days: int = 14, per_page: int = 50, workers: int = 4,
           clusters_cfg: dict | None = None,
           agencies: list[str] | None = None) -> list[Job]:
    """Query USAJOBS for every (usajobs term x place) the profile asks for.

    `usajobs_terms` are deliberately broad single words: federal postings are
    titled by occupational series ("Interdisciplinary General
    Engineer/Physical Scientist"), so compound phrases that work on Adzuna
    match almost nothing here. See the comment on them in clusters.yaml.
    """
    email, key = load_creds()
    if locations is None or agencies is None:
        filters = scan_config.load_yaml(scan_config.FILTERS_YAML)
        if locations is None:
            locations = scan_config.search_locations(filters)
        if agencies is None:
            agencies, _ = agency_scope(filters)
    if clusters_cfg is None:
        clusters_cfg = scan_config.load_yaml(scan_config.CLUSTERS_YAML)
    tasks = scan_config.plan_queries(
        clusters, scan_config.cluster_terms(clusters_cfg, "usajobs_terms"),
        locations)

    def run(t) -> list[Job]:
        term, mkey, place = t
        params = {"Keyword": term, "ResultsPerPage": per_page,
                  "DatePosted": min(max_days, 60)}
        if mkey == scan_config.NATIONWIDE:
            params["RemoteIndicator"] = "True"
        else:
            params.update({"LocationName": usajobs_place(place), "Radius": 40})
        d = _get(BASE + "?" + urllib.parse.urlencode(params), email, key)
        if not d:
            return []
        items = ((d.get("SearchResult") or {}).get("SearchResultItems") or [])
        return [j for j in (to_job(it, agencies) for it in items) if j]

    seen: dict[str, Job] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for batch in pool.map(run, tasks):
            for j in batch:
                seen.setdefault(j.uid, j)   # same req across queries/metros
    return list(seen.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clusters", required=True, help="comma-separated cluster ids")
    ap.add_argument("--metros", default="",
                    help="comma-separated metro keys (default: all in filters.yaml)")
    ap.add_argument("--remote", choices=scan_config.REMOTE_MODES,
                    help="override remote.mode from filters.yaml")
    ap.add_argument("--max-days", type=int, default=14)
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()
    filters = scan_config.load_yaml(scan_config.FILTERS_YAML)
    only = {m.strip() for m in args.metros.split(",") if m.strip()} or None
    locations = scan_config.search_locations(filters, only=only, mode=args.remote)
    agencies, where = agency_scope(filters)
    print(f"agencies ({where}): {', '.join(agencies) or 'all'}", file=sys.stderr)
    jobs = search({c.strip() for c in args.clusters.split(",") if c.strip()},
                  locations=locations, max_days=args.max_days, agencies=agencies)
    print(f"{len(jobs)} unique postings", file=sys.stderr)
    for j in jobs[:args.limit]:
        pay = f"${j.comp_min or 0:,}-${j.comp_max or 0:,}"
        print(f"  {j.company[:26]:<27}| {j.title[:40]:<41}| "
              f"{j.location_raw[:22]:<23}| {pay}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

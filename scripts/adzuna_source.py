"""Adzuna as a supplementary source.

Every other source in this project is a company's own board, reached because we
know its ATS. That structurally misses employers on iCIMS, Oracle HCM, Taleo,
Phenom and Avature -- roughly half of established employers, and precisely where
entry-to-mid energy project engineering lives. Adzuna indexes postings
regardless of the employer's ATS, so it reaches exactly that gap.

Two things to understand before trusting its output:

  * DESCRIPTIONS ARE SNIPPETS. Adzuna returns roughly 200 characters, not the
    full posting ("we currently only provide a snippet of the job description").
    Scoring on a snippet is materially weaker than scoring on a real JD, so
    these candidates carry source="adzuna" and the digest must say so.
  * It is an aggregator, so the same requisition often appears here AND on the
    company's own board. fetch_jobs collapses duplicates on
    (company, title, metro) and prefers the ATS copy, which has the full text.

Credentials are free but require registering at developer.adzuna.com. Put them
in sources/adzuna.local.yaml (gitignored) or ADZUNA_APP_ID / ADZUNA_APP_KEY.

    python scripts/adzuna_source.py --clusters <id> --limit 5
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
from ats_adapters import Job, iso, strip_html  # noqa: E402

from datetime import datetime, timezone  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDS = os.path.join(ROOT, "sources/adzuna.local.yaml")
CREDS_EXAMPLE = os.path.join(ROOT, "sources/adzuna.example.yaml")
BASE = "https://api.adzuna.com/v1/api/jobs/us/search/1"
UA = "Mozilla/5.0 (compatible; job-scanner/1.0)"

# What to ask for and where both come from the profile: each cluster's
# `search_terms` in clusters.yaml, and each metro's `search_as` in filters.yaml
# (see scan_config.py). Adzuna's `what` is a keyword match, so the terms stay
# short and high-signal; the cluster title regexes do the real filtering once
# results come back.

# Adzuna's location field names a city even for a remote role; the remote part
# is in the title or the snippet -- "Engineer III - FinOps Data Analytics
# (Remote)" came back located in Sunnyvale on the first nationwide probe,
# 2026-10-29, and twelve more carried "Location: Remote (US)" or "100% Remote"
# in the snippet under a city. Results of a nationwide remote search are marked
# remote when the posting itself says so, so the location filter can tell them
# from the on-site roles that same search also returns.
#
# A snippet counts only when it states the arrangement. The bare word is not
# enough: energy postings say "remote monitoring", and some say "not remote".
REMOTE_TITLE = re.compile(r"\bremote\b", re.I)
_NOT = r"(?<!non-)(?<!not a )(?<!not )(?<!no )"
REMOTE_STATED = re.compile(
    rf"\blocation:?\s*remote\b|{_NOT}\b(100%|fully|entirely)\s+remote\b|"
    rf"\bremote\s*\((us|u\.s\.|usa|united states)\)|{_NOT}\bwork\s+from\s+home\b|"
    rf"{_NOT}\bremote[\s-](first|role|position|job|opportunity|eligible)\b", re.I)


def says_remote(j: Job) -> bool:
    return bool(REMOTE_TITLE.search(j.title) or REMOTE_STATED.search(j.description))


def load_creds() -> tuple[str, str]:
    app_id = os.environ.get("ADZUNA_APP_ID", "")
    app_key = os.environ.get("ADZUNA_APP_KEY", "")
    if not (app_id and app_key) and os.path.exists(CREDS):
        c = yaml.safe_load(open(CREDS, encoding="utf-8")) or {}
        app_id = app_id or str(c.get("app_id", "") or "")
        app_key = app_key or str(c.get("app_key", "") or "")
    if not (app_id and app_key):
        raise SystemExit(
            "Adzuna credentials not found.\n"
            f"  Register (free) at https://developer.adzuna.com/signup\n"
            f"  then copy {os.path.relpath(CREDS_EXAMPLE, ROOT)} to "
            f"{os.path.relpath(CREDS, ROOT)} and fill in app_id / app_key.\n"
            "  Or set ADZUNA_APP_ID and ADZUNA_APP_KEY."
        )
    return app_id, app_key


def _get(url: str, retries: int = 3) -> dict | None:
    delay = 1.0
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                if r.status != 200:
                    return None
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 401/403 mean bad credentials -- retrying will not fix that.
            if e.code in (401, 403):
                body = e.read().decode("utf-8", "ignore")[:200]
                raise SystemExit(f"Adzuna auth failed: {body}")
            if attempt == retries - 1:
                return None
            time.sleep(delay * (3 if e.code == 429 else 1))
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(delay)
        delay *= 2
    return None


def to_job(r: dict, metro_hint: str) -> Job | None:
    jid = str(r.get("id") or "")
    if not jid:
        return None
    company = ((r.get("company") or {}).get("display_name") or "").strip()
    where = r.get("location") or {}
    loc = (where.get("display_name") or "").strip()
    # display_name stops at the county ("Burlington, Middlesex County"), and a
    # city that needs its state to resolve -- Burlington MA or VT -- would be
    # dropped for lack of one. `area` runs country, state, county, city.
    area = where.get("area") or []
    state = scan_config.STATE_CODES.get(str(area[1]).lower()) if len(area) > 1 else None
    if loc and state:
        loc = f"{loc}, {state}"
    title = (r.get("title") or "").strip()
    if not (company and title):
        return None
    j = Job(
        uid=hashlib.sha1(f"adzuna:{jid}".encode()).hexdigest()[:16],
        ats="adzuna", company=company, token="adzuna", job_id=jid,
        title=strip_html(title), location_raw=loc or metro_hint,
        url=r.get("redirect_url") or "",
        posted_at=r.get("created"),
    )
    # Snippet only -- flagged so the digest can say the scoring input was thin.
    j.description = "[Adzuna snippet, not the full posting]\n" + strip_html(
        r.get("description") or "")
    for k, attr in (("salary_min", "comp_min"), ("salary_max", "comp_max")):
        v = r.get(k)
        if isinstance(v, (int, float)) and v > 0:
            setattr(j, attr, int(v))
    return j


def search(clusters: set[str], locations: dict[str, list[str]] | None = None,
           max_days: int = 14, per_page: int = 50, workers: int = 4,
           clusters_cfg: dict | None = None) -> list[Job]:
    """Query Adzuna for every (search term x place) the profile asks for.

    `locations` comes from scan_config.search_locations(); fetch_jobs passes the
    one it built, so --metros and --remote reach every source the same way.
    """
    app_id, app_key = load_creds()
    if locations is None:
        locations = scan_config.search_locations(
            scan_config.load_yaml(scan_config.FILTERS_YAML))
    if clusters_cfg is None:
        clusters_cfg = scan_config.load_yaml(scan_config.CLUSTERS_YAML)
    tasks = scan_config.plan_queries(
        clusters, scan_config.cluster_terms(clusters_cfg), locations)

    def run(t) -> list[Job]:
        term, mkey, place = t
        params = {
            "app_id": app_id, "app_key": app_key,
            "results_per_page": per_page,
            "max_days_old": max_days, "content-type": "application/json",
        }
        if mkey == scan_config.NATIONWIDE:
            # No place to search around: ask the whole US index for the term
            # plus "remote". The location filter then keeps only postings
            # that really are remote.
            params["what"] = f"{term} remote"
            hint = ""
        else:
            params.update({"what": term, "where": place, "distance": 40})
            hint = place
        d = _get(BASE + "?" + urllib.parse.urlencode(params))
        if not d:
            return []
        out = []
        for r in d.get("results") or []:
            j = to_job(r, hint)
            if not j:
                continue
            if (mkey == scan_config.NATIONWIDE
                    and "remote" not in j.location_raw.lower()
                    and says_remote(j)):
                j.location_raw = f"{j.location_raw}, Remote" if j.location_raw else "Remote"
            out.append(j)
        return out

    seen: dict[str, Job] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for batch in pool.map(run, tasks):
            for j in batch:
                seen.setdefault(j.uid, j)     # same req across queries/metros
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
    only = {m.strip() for m in args.metros.split(",") if m.strip()} or None
    locations = scan_config.search_locations(
        scan_config.load_yaml(scan_config.FILTERS_YAML), only=only, mode=args.remote)
    jobs = search({c.strip() for c in args.clusters.split(",") if c.strip()},
                  locations=locations, max_days=args.max_days)
    print(f"{len(jobs)} unique postings", file=sys.stderr)
    for j in jobs[:args.limit]:
        print(f"  {j.company[:24]:<25}| {j.title[:44]:<45}| {j.location_raw[:28]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

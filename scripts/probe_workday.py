"""Find a Workday tenant/site by probing, when careers-page detection fails.

detect_ats.py reads the careers page and looks for a myworkdayjobs.com link.
That fails on single-page careers sites -- ServiceNow, Salesforce, Autodesk,
Veeva and most large enterprises render the job search entirely in JavaScript,
so a plain fetch sees no ATS at all even though a Workday board exists.

This probes the CXS API directly instead: tenant x host x site-name, keeping
any combination that returns real postings. Guessing is cheap here and, unlike
slug-guessing for Greenhouse, near-impossible to get *wrong* -- a Workday
tenant is company-specific, so a hit is the right company by construction.

    python scripts/probe_workday.py servicenow salesforce autodesk
    python scripts/probe_workday.py --name "ServiceNow" servicenow
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

HOSTS = ["wd1", "wd5", "wd3", "wd12", "wd101", "wd2", "wd10"]

def site_names(tenant: str) -> list[str]:
    t = tenant
    T = tenant.capitalize()
    U = tenant.upper()
    return [
        "External", "external", "Careers", "careers", "search", "Search",
        f"{T}_Careers", f"{t}_careers", f"{U}", f"{T}",
        "External_Career_Site", "ExternalCareerSite", "External_Careers",
        f"{T}_External_Career_Site", f"{t}", "Global", "Professional",
        f"{T}Careers", "CareerSite", "jobs", "Jobs",
    ]


def probe(tenant: str, host: str, site: str, timeout: int = 12) -> int | None:
    url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    body = json.dumps({"limit": 1, "offset": 0, "searchText": ""}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            d = json.loads(r.read())
        n = d.get("total")
        return int(n) if isinstance(n, int) and n > 0 else None
    except Exception:
        return None


def find(tenant: str) -> tuple[str, str, str, int] | None:
    for host in HOSTS:
        # One cheap probe per host before trying every site name.
        combos = [(host, s) for s in site_names(tenant)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda c: (c[1], probe(tenant, c[0], c[1])), combos))
        for site, n in results:
            if n:
                return (tenant, host, site, n)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tenants", nargs="+")
    ap.add_argument("--name", help="display name (single tenant only)")
    args = ap.parse_args()

    hits, misses = [], []
    for t in args.tenants:
        r = find(t)
        (hits if r else misses).append(r or t)
        print(f"  {t:<24} {'-> ' + r[1] + '/' + r[2] + f'  ({r[3]} jobs)' if r else 'no board found'}",
              file=sys.stderr)

    if misses:
        print("\nNot found: " + ", ".join(misses), file=sys.stderr)
    if not hits:
        return 1

    print("\n# Paste into the `manual:` list in sources/companies.yaml")
    for tenant, host, site, n in hits:
        name = args.name if (args.name and len(args.tenants) == 1) else tenant
        print(f'  - name: "{name}"')
        print(f"    ats: workday")
        print(f"    tenant: {tenant}")
        print(f"    host: {host}")
        print(f"    site: {site}")
        print(f"    confidence: verified   # {n} live postings at detection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

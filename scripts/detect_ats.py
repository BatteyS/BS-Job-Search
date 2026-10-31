"""Identify a company's ATS and emit a ready-to-paste companies.yaml entry.

This is the tool for growing the net. When you find a company you want scanned,
run it against their domain; if the platform is supported you get a config block
to paste into the `manual:` list in sources/companies.yaml.

    python scripts/detect_ats.py bv.com
    python scripts/detect_ats.py ameresco.com clearesult.com ethree.com
    python scripts/detect_ats.py --name "Black & Veatch" bv.com

Detection is best-effort: careers pages that render entirely in JavaScript can
hide the ATS from a plain HTTP fetch. A "not detected" result means look at the
page yourself and check where the Apply button goes -- it does not prove the
company has no usable board.

Every emitted entry is VERIFIED before printing: the tool actually calls the
board and reports the live posting count. If it says 0, do not paste it.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ats_adapters import UA, list_board  # noqa: E402

# Ordered: a page can reference several, so the most specific pattern wins.
SIGNATURES = [
    ("workday", r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
    ("greenhouse", r"(?:boards|job-boards)\.greenhouse\.io/([a-zA-Z0-9_-]+)"),
    ("lever", r"jobs\.lever\.co/([a-zA-Z0-9_-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)"),
    ("successfactors", r"(successfactors|sapsf)\."),
]
# Platforms we can identify but cannot read. Naming them is still useful --
# it tells you to stop looking rather than assume detection failed.
UNSUPPORTED = {
    # iCIMS is detectable but not scannable: WAF returns 405 to Python HTTP
    # clients, and many tenants render results client-side. See ats_adapters.py.
    "icims": r"[a-z0-9-]+\.icims\.com",
    "taleo": r"taleo\.net",
    "oracle-hcm": r"oraclecloud\.com|oracle\.com/hcm",
    "avature": r"avature\.net",
    "eightfold": r"eightfold\.ai",
    "phenom": r"phenompeople\.com",
    "ukg": r"ultipro\.com",
    "smartrecruiters": r"smartrecruiters\.com",
    "jobvite": r"jobvite\.com",
    "brassring": r"brassring\.com",
    "workable": r"workable\.com",
    "paycom": r"paycomonline\.net",
    "cornerstone": r"csod\.com",
    "dayforce": r"dayforcehcm\.com",
}

PATHS = ["/careers", "/careers/", "/jobs", "/en/careers", "/about/careers",
         "/company/careers", "/careers/job-search", "/careers/jobs", "/"]


def get(url: str, limit: int = 900_000) -> tuple[str, str]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return (r.geturl(), r.read(limit).decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        try:
            return (e.geturl(), e.read(limit // 2).decode("utf-8", "ignore"))
        except Exception:
            return ("", "")
    except Exception:
        return ("", "")


def candidate_urls(domain: str) -> list[str]:
    d = domain.strip().rstrip("/").replace("https://", "").replace("http://", "")
    return ([f"https://careers.{d}", f"https://jobs.{d}"]
            + [f"https://{d}{p}" for p in PATHS]
            + [f"https://www.{d}{p}" for p in PATHS[:3]])


def detect(domain: str, name: str | None = None) -> dict:
    name = name or domain.split(".")[0].replace("-", " ").title()
    blob, seen_urls = "", []
    for u in candidate_urls(domain):
        final, body = get(u)
        if not body:
            continue
        seen_urls.append(final or u)
        blob += " " + final + " " + body
        if any(re.search(p, blob, re.I) for _, p in SIGNATURES):
            break

    if not blob.strip():
        return {"name": name, "domain": domain, "status": "unreachable"}

    for ats, pat in SIGNATURES:
        m = re.search(pat, blob, re.I)
        if not m:
            continue
        cfg: dict = {"name": name, "ats": ats}
        if ats == "workday":
            cfg |= {"tenant": m.group(1), "host": m.group(2), "site": m.group(3)}
        elif ats == "successfactors":
            base = next((u for u in seen_urls if "career" in u.lower()), "")
            if not base:
                return {"name": name, "domain": domain, "status": "successfactors-no-base"}
            cfg["base"] = base.rstrip("/").split("/search")[0]
        else:
            cfg["token"] = m.group(1)
        return {"name": name, "domain": domain, "status": "supported", "config": cfg}

    for label, pat in UNSUPPORTED.items():
        if re.search(pat, blob, re.I):
            return {"name": name, "domain": domain, "status": "unsupported", "ats": label}
    return {"name": name, "domain": domain, "status": "not-detected"}


def verify(cfg: dict) -> int:
    """Actually call the board. Never emit an entry that returns nothing."""
    try:
        jobs, ok, _ = list_board(cfg)
        return len(jobs) if ok else -1
    except Exception:
        return -1


def emit(cfg: dict, count: int) -> str:
    order = ["name", "ats", "token", "tenant", "host", "site", "base"]
    lines = [f"  - name: {cfg['name']!r}".replace("'", '"')]
    for k in order[1:]:
        if k in cfg:
            lines.append(f"    {k}: {cfg[k]}")
    lines.append(f"    confidence: verified   # {count} live postings at detection")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("domains", nargs="+",
                    help='domains, optionally "domain=Company Name" to set the '
                         'name that appears in digests (e.g. bv.com="Black & Veatch")')
    ap.add_argument("--name", help="company name (only valid with one domain)")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if args.name and len(args.domains) > 1:
        print("--name works with a single domain only", file=sys.stderr)
        return 2

    pairs: list[tuple[str, str | None]] = []
    for spec in args.domains:
        dom, _, nm = spec.partition("=")
        pairs.append((dom, nm or args.name))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda p: detect(p[0], p[1]), pairs))

    ready, notes = [], []
    for r in results:
        if r["status"] == "supported":
            n = verify(r["config"])
            if n > 0:
                ready.append((r, n))
            else:
                notes.append(f"  {r['domain']:<26} {r['config']['ats']} detected, "
                             f"but the board returned no postings -- do not add")
        elif r["status"] == "unsupported":
            notes.append(f"  {r['domain']:<26} {r['ats']} -- no free API; not scannable")
        elif r["status"] == "unreachable":
            notes.append(f"  {r['domain']:<26} could not fetch any careers page")
        else:
            notes.append(f"  {r['domain']:<26} ATS not detected "
                         f"(likely JS-rendered -- check the Apply link yourself)")

    if ready:
        print("# Paste into the `manual:` list in sources/companies.yaml\n")
        for r, n in ready:
            print(emit(r["config"], n))
        print()
    if notes:
        print("Not added:", file=sys.stderr)
        for n in notes:
            print(n, file=sys.stderr)
    print(f"\n{len(ready)} of {len(results)} ready to add.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

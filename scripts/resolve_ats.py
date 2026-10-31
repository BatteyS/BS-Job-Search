"""Resolve company names to ATS board tokens by probing public job-board APIs.

Board tokens are not derivable from company names -- probing six target
companies by guesswork resolved only two. This script generates plausible slug
variants per company and probes Greenhouse, Lever, and Ashby directly, keeping
only tokens that return a real board.

Usage:
    python scripts/resolve_ats.py sources/seed_companies.txt -o sources/companies.yaml

Re-run monthly; companies migrate between ATS vendors and tokens go stale.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

TIMEOUT = 8
WORKERS = 8
UA = "Mozilla/5.0 (compatible; job-scanner/1.0)"

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{t}/jobs",
    "lever": "https://api.lever.co/v0/postings/{t}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{t}",
}

# Words that companies routinely drop from their board token.
DROPPABLE = (
    "inc corp corporation company co llc ltd holdings group technologies technology "
    "tech systems system labs lab industries energy power solutions materials "
    "sciences science ai io the and"
).split()


# (ats, token) pairs confirmed to belong to a different company. Loaded from
# sources/known_bad.txt so a re-run never reintroduces a rejected match.
DENY: set[tuple[str, str]] = set()


@dataclass
class Result:
    name: str
    ats: str | None = None
    token: str | None = None
    job_count: int = 0
    sample: str = ""
    confidence: str = "high"
    tried: list[str] = field(default_factory=list)


def load_denylist(path: str) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.split("#", 1)[0].strip()
                if not ln:
                    continue
                parts = ln.split()
                if len(parts) >= 2:
                    out.add((parts[0], parts[1]))
    except FileNotFoundError:
        pass
    return out


def fetch_sample(ats: str, token: str) -> str:
    """One 'title @ location' string, so a human can eyeball the match once."""
    req = urllib.request.Request(
        ENDPOINTS[ats].format(t=token), headers={"User-Agent": UA}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read())
    except Exception:
        return ""
    jobs = data["jobs"] if isinstance(data, dict) else data
    if not jobs:
        return ""
    j = jobs[0]
    title = j.get("title") or j.get("text") or "?"
    loc = j.get("location")
    if isinstance(loc, dict):
        loc = loc.get("name")
    if not loc:
        loc = (j.get("categories") or {}).get("location", "")
    return f"{title} @ {loc}"[:90]


def slugs_from_domain(domain: str) -> list[str]:
    """Token candidates derived from the web domain.

    Board tokens follow the BRAND, not the legal name, and the domain is the
    best available proxy for the brand. Measured examples this recovers, none
    of which any name-based generator can produce:

        eh2.com          -> eh2          (Electric Hydrogen)
        cfs.energy       -> cfsenergy    (Commonwealth Fusion Systems)
        ethree.com       -> ethree       (Energy and Environmental Economics)

    Cheap to try and, because every candidate is still verified against a live
    board, a wrong guess costs one HTTP request rather than a bad entry.
    """
    d = re.sub(r"^https?://", "", (domain or "").strip().lower()).strip("/")
    d = re.sub(r"^www\.", "", d).split("/")[0]
    if not d or "." not in d:
        return []
    parts = d.split(".")
    tld = parts[-1]
    stem = ".".join(parts[:-1])
    out: list[str] = []

    def add(s: str) -> None:
        if s and s not in out and 1 < len(s) <= 40:
            out.append(s)

    add(stem.replace(".", "").replace("-", ""))   # sublime-systems -> sublimesystems
    add(stem.replace(".", "-"))
    add(parts[0])                                  # eh2.com -> eh2
    # cfs.energy -> cfsenergy: a non-generic TLD is often part of the brand.
    if tld not in {"com", "net", "org", "io", "ai", "co", "us", "inc"}:
        add(stem.replace(".", "").replace("-", "") + tld)
    return out


def slugs_for(name: str) -> list[str]:
    """Generate candidate board tokens, most likely first."""
    clean = re.sub(r"[^\w\s-]", "", name.lower()).strip()
    words = [w for w in re.split(r"[\s-]+", clean) if w]
    out: list[str] = []

    def add(s: str) -> None:
        if s and s not in out and len(s) > 2:
            out.append(s)

    add("".join(words))
    add("-".join(words))
    kept = [w for w in words if w not in DROPPABLE]
    if kept != words:
        add("".join(kept))
        add("-".join(kept))
    # Deliberately NO bare first-word fallback. It produced confident false
    # positives on the first run: "Electric Hydrogen" -> ashby/electric (an
    # unrelated software company) and "Radiant Nuclear" -> ashby/radiant (a
    # UK company in Gloucestershire). A wrong token is worse than a missing
    # one -- it silently pollutes every nightly scan.
    return out[:6]


def count_jobs(ats: str, payload: bytes) -> int | None:
    """Return job count, or None if the payload isn't a valid board."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if ats == "greenhouse":
        if isinstance(data, dict) and isinstance(data.get("jobs"), list):
            return len(data["jobs"])
    elif ats == "lever":
        # Lever returns a bare list; an error is a dict with ok=false.
        if isinstance(data, list):
            return len(data)
    elif ats == "ashby":
        if isinstance(data, dict) and isinstance(data.get("jobs"), list):
            return len(data["jobs"])
    return None


def probe(ats: str, token: str, retries: int = 3) -> int | None:
    """Probe one board. Retries transient failures.

    Without this, a bulk run silently mis-reports: Electric Hydrogen resolved to
    greenhouse/eh2 when probed alone but came back "unresolved" during a
    399-company sweep, because 16 workers hammering one host produce timeouts
    and throttling that are indistinguishable from "no such board". A false
    negative here is expensive -- it drops a real employer from the scan.
    """
    url = ENDPOINTS[ats].format(t=token)
    delay = 0.8
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                if resp.status != 200:
                    return None
                return count_jobs(ats, resp.read())
        except urllib.error.HTTPError as e:
            # 404/410 are real answers: this token does not exist. Anything
            # else (429, 5xx) is worth another try.
            if e.code in (404, 410):
                return None
            if attempt == retries - 1:
                return None
            time.sleep(delay * (3 if e.code == 429 else 1))
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == retries - 1:
                return None
            time.sleep(delay)
        delay *= 2
    return None


def resolve(entry: str) -> Result:
    # Seed lines may carry an optional domain: "Company Name | example.com"
    if "|" in entry:
        name, domain = (x.strip() for x in entry.split("|", 1))
    else:
        name, domain = entry.strip(), ""
    res = Result(name=name)
    # Domain-derived candidates first: they encode the brand, which is what
    # board tokens actually follow.
    for token in slugs_from_domain(domain) + slugs_for(name):
        res.tried.append(token)
        for ats in ENDPOINTS:
            if (ats, token) in DENY:
                continue
            n = probe(ats, token)
            # A board with zero jobs is usually a wrong-but-existing token or a
            # company not currently hiring; accept it only if nothing better turns up.
            if n is not None and n > 0:
                res.ats, res.token, res.job_count = ats, token, n
                # A token that drops words from the company name ("Haven Energy"
                # -> haven) collides far more often. In the 2026-08-06 run, 3 of
                # 9 such matches were the wrong company -- a 33% error rate,
                # versus near zero for full-name tokens. Flag them for review.
                full = re.sub(r"[^a-z0-9]", "", name.lower())
                if re.sub(r"[^a-z0-9]", "", token) != full:
                    res.confidence = "low"
                return res
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("seedfile", help="one company name per line; # comments ok")
    ap.add_argument("-o", "--out", default="sources/companies.yaml")
    ap.add_argument("--denylist", default="sources/known_bad.txt")
    args = ap.parse_args()

    global DENY
    DENY = load_denylist(args.denylist)
    if DENY:
        print(f"denylist: {len(DENY)} rejected (ats, token) pairs", file=sys.stderr)

    with open(args.seedfile, encoding="utf-8") as fh:
        names = [
            ln.strip()
            for ln in fh
            if ln.strip() and not ln.lstrip().startswith("#")
        ]

    print(f"Probing {len(names)} companies across 3 ATS vendors...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(resolve, names))

    found = [r for r in results if r.token]
    missing = [r for r in results if not r.token]
    found.sort(key=lambda r: r.name.lower())

    # Second pass: one sample posting per board. Makes a wrong token visible on
    # inspection instead of invisible until it poisons a digest.
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        samples = pool.map(lambda r: fetch_sample(r.ats, r.token), found)
    for r, s in zip(found, samples):
        r.sample = s

    lines = [
        "# Company -> ATS board token map. GENERATED by scripts/resolve_ats.py.",
        "# Every token below returned a live board with >=1 open posting at generation time.",
        "# Re-run monthly. Hand-edits survive only until the next regeneration --",
        "# add durable entries to the `manual:` block at the bottom instead.",
        "",
        "version: 1",
        "companies:",
    ]
    for r in found:
        lines.append(f"  - name: {json.dumps(r.name)}")
        lines.append(f"    ats: {r.ats}")
        lines.append(f"    token: {r.token}")
        lines.append(f"    jobs_at_scan: {r.job_count}")
        lines.append(f"    confidence: {r.confidence}")
        if r.sample:
            lines.append(f"    sample: {json.dumps(r.sample)}")
    lines += [
        "",
        "# Not resolved by automated probing. These use Workday, iCIMS, SmartRecruiters,",
        "# SuccessFactors, or a custom board -- none of which expose a free JSON API.",
        "# To add one: open its careers page, look for a boards.greenhouse.io/<token>,",
        "# jobs.lever.co/<token>, or jobs.ashbyhq.com/<token> URL, and add it under `manual:`.",
        "unresolved:",
    ]
    for r in sorted(missing, key=lambda r: r.name.lower()):
        lines.append(f"  - {json.dumps(r.name)}   # tried: {', '.join(r.tried)}")
    # Carry the existing manual block through verbatim. Regeneration silently
    # destroyed it twice -- taking with it every Workday/SuccessFactors employer
    # (Black & Veatch, PG&E, CLEAResult, Ameresco...), which are exactly the
    # ones this resolver cannot find and which took manual work to verify.
    manual_block = ""
    try:
        with open(args.out, encoding="utf-8") as fh:
            prev = fh.read()
        # Anchor to a line that STARTS with "manual:". Searching for the bare
        # substring matched the words "manual:` block" inside the header comment
        # and spliced the whole file onto itself.
        m = re.search(r"^manual:", prev, re.M)
        if m:
            tail = prev[m.start():].rstrip()
            if tail and tail != "manual: []":
                manual_block = tail
    except FileNotFoundError:
        pass

    lines += ["", manual_block or "manual: []", ""]

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(
        f"resolved {len(found)}/{len(names)}  ->  {args.out}",
        file=sys.stderr,
    )
    for r in found:
        print(f"  {r.name:<32} {r.ats:<11} {r.token:<28} {r.job_count:>4} jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

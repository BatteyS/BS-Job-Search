"""ATS adapters: one board -> a list of normalized Job records.

Six platforms, split into two reliability tiers. Know which you're relying on:

  JSON APIs (stable, documented shapes)
    greenhouse, lever, ashby   -- free, unauthenticated, no per-company setup
    workday                    -- free JSON, but tenant/host/site must be
                                  discovered per company (scripts/detect_ats.py)

  HTML scraping (brittle by nature -- a site redesign breaks the parser)
    successfactors             -- career-site HTML, parses reliably today

NOT SUPPORTED -- iCIMS. Attempted and deliberately abandoned 2026-08-06. Two
independent problems: only some tenants render results server-side (Sargent &
Lundy returns 109 KB with 20 rows; Exelon and TRC return a ~150-byte chrome
stub), and the platform sits behind a WAF that returns HTTP 405 to Python HTTP
clients while serving curl the same URL normally -- reproduced with both urllib
and requests. Shipping a scraper whose viability depends on evading a WAF would
fail silently and unpredictably, so iCIMS employers (Exelon, TRC, Sargent &
Lundy) are simply out of scope. detect_ats.py still names iCIMS when it sees it,
so the answer reads as "not scannable" rather than "detection failed".

Adding a platform means adding one `_list_*` function and one dispatch entry.
Nothing in fetch_jobs.py needs to change.
"""

from __future__ import annotations

import gzip
import hashlib
import html as htmllib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Per-host concurrency. All boards of one vendor share a host, so this -- not
# the global worker count -- is what actually prevents rate limiting.
HOST_LIMITS = {
    "greenhouse": 8, "lever": 6, "ashby": 8,
    "workday": 4, "successfactors": 3,
}
_sems: dict[str, threading.Semaphore] = {
    k: threading.Semaphore(v) for k, v in HOST_LIMITS.items()
}


@dataclass
class Job:
    uid: str
    ats: str
    company: str
    token: str
    job_id: str
    title: str
    location_raw: str
    url: str
    posted_at: str | None = None
    metro: str | None = None
    is_remote: bool = False
    loc_penalty: int = 0
    clusters: list[str] = field(default_factory=list)
    comp_min: int | None = None
    comp_max: int | None = None
    description: str = ""
    detail_path: str = ""      # adapter-specific handle for the detail fetch
    duplicate_count: int = 1   # identical reqs collapsed into this one
    yoe_min: int | None = None  # lowest stated years-of-experience minimum
    yoe_max: int | None = None


# ----------------------------------------------------------------- utilities


def mk_uid(ats: str, token: str, job_id: str) -> str:
    return hashlib.sha1(f"{ats}:{token}:{job_id}".encode()).hexdigest()[:16]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_when(val: object) -> str | None:
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            secs = val / 1000 if val > 1e11 else val
            return iso(datetime.fromtimestamp(secs, tz=timezone.utc))
        s = str(val).strip().replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return iso(d)
    except Exception:
        return None


def parse_relative_posted(s: str) -> str | None:
    """Workday ships 'Posted Today' / 'Posted 5 Days Ago' instead of a date.

    Only used for the Stage 1 age cut; the detail fetch returns a real ISO
    startDate for anything that survives.
    """
    if not s:
        return None
    t = s.lower()
    now = datetime.now(timezone.utc)
    if "today" in t:
        return iso(now)
    if "yesterday" in t:
        return iso(now - timedelta(days=1))
    m = re.search(r"(\d+)\+?\s*day", t)
    if m:
        return iso(now - timedelta(days=int(m.group(1))))
    m = re.search(r"(\d+)\+?\s*month", t)
    if m:
        return iso(now - timedelta(days=30 * int(m.group(1))))
    return None


def strip_html(s: str) -> str:
    """HTML -> plain text.

    Unescaping MUST happen before tag stripping. Greenhouse returns its
    `content` field HTML-escaped (`&lt;div&gt;`), so stripping first matched
    nothing and the later unescape handed back raw markup -- descriptions were
    reaching the scorer full of `<div class=...>` and inline CSS ("font",
    "style", "arial", "helvetica" ranked as top keywords for a Samsara role).
    Unescape twice: some boards double-encode.
    """
    s = htmllib.unescape(htmllib.unescape(s or ""))
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</tr>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def _open(req: urllib.request.Request, ats: str, timeout: int) -> bytes | None:
    sem = _sems.get(ats)
    if sem is None:
        sem = _sems.setdefault(ats, threading.Semaphore(4))
    with sem:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw


def http(url: str, ats: str, *, data: dict | None = None, timeout: int = 25,
         retries: int = 3) -> bytes | None:
    """GET, or POST when `data` is given. None on permanent failure."""
    delay = 1.0
    body = json.dumps(data).encode() if data is not None else None
    for attempt in range(retries):
        try:
            headers = {"User-Agent": UA, "Accept-Encoding": "gzip"}
            if data is not None:
                headers["Content-Type"] = "application/json"
                headers["Accept"] = "application/json"
            req = urllib.request.Request(url, data=body, headers=headers)
            return _open(req, ats, timeout)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410, 403):
                return None          # retrying will not help
            if e.code == 429:
                time.sleep(delay * 3)
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(delay)
            delay *= 2
    return None


def http_json(url: str, ats: str, **kw) -> object | None:
    raw = http(url, ats, **kw)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def http_text(url: str, ats: str, **kw) -> str | None:
    raw = http(url, ats, **kw)
    return None if raw is None else raw.decode("utf-8", "ignore")


# ------------------------------------------------------------ JSON API tiers


def _list_greenhouse(c: dict) -> list[Job]:
    tok = c["token"]
    d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs", "greenhouse")
    out = []
    for j in (d or {}).get("jobs", []):
        jid = str(j.get("id"))
        out.append(Job(
            uid=mk_uid("greenhouse", tok, jid), ats="greenhouse", company=c["name"],
            token=tok, job_id=jid, title=j.get("title") or "",
            location_raw=(j.get("location") or {}).get("name") or "",
            url=j.get("absolute_url") or "",
            posted_at=parse_when(j.get("first_published") or j.get("updated_at")),
            detail_path=jid,
        ))
    return out


def _list_lever(c: dict) -> list[Job]:
    tok = c["token"]
    d = http_json(f"https://api.lever.co/v0/postings/{tok}?mode=json", "lever")
    out = []
    for j in d or []:
        jid = str(j.get("id"))
        cats = j.get("categories") or {}
        job = Job(
            uid=mk_uid("lever", tok, jid), ats="lever", company=c["name"], token=tok,
            job_id=jid, title=j.get("text") or "", location_raw=cats.get("location") or "",
            url=j.get("hostedUrl") or j.get("applyUrl") or "",
            posted_at=parse_when(j.get("createdAt")),
        )
        job.description = strip_html(j.get("descriptionPlain") or j.get("description") or "")
        sal = j.get("salaryRange") or {}
        if isinstance(sal, dict) and sal.get("max"):
            try:
                job.comp_min = int(float(sal.get("min") or 0)) or None
                job.comp_max = int(float(sal["max"]))
            except (TypeError, ValueError):
                pass
        out.append(job)
    return out


def _list_ashby(c: dict) -> list[Job]:
    tok = c["token"]
    d = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{tok}", "ashby")
    out = []
    for j in (d or {}).get("jobs", []):
        jid = str(j.get("id"))
        locs = [j.get("location") or ""]
        for sec in j.get("secondaryLocations") or []:
            if isinstance(sec, dict) and sec.get("location"):
                locs.append(sec["location"])
        job = Job(
            uid=mk_uid("ashby", tok, jid), ats="ashby", company=c["name"], token=tok,
            job_id=jid, title=j.get("title") or "",
            location_raw=" | ".join(x for x in locs if x),
            url=j.get("jobUrl") or "", posted_at=parse_when(j.get("publishedAt")),
        )
        job.description = strip_html(j.get("descriptionPlain") or j.get("descriptionHtml") or "")
        comp = j.get("compensation") or {}
        if isinstance(comp, dict):
            for tier in comp.get("compensationTiers") or []:
                for comp_c in (tier or {}).get("components") or []:
                    try:
                        mx = comp_c.get("maxValue") or comp_c.get("value")
                        if mx and float(mx) > (job.comp_max or 0):
                            job.comp_max = int(float(mx))
                            job.comp_min = int(float(comp_c.get("minValue") or 0)) or None
                    except (TypeError, ValueError):
                        pass
        out.append(job)
    return out


def _list_workday(c: dict) -> list[Job]:
    """POST /wday/cxs/{tenant}/{site}/jobs, paginated 20 at a time.

    Requires tenant, host (wd1/wd5/...), and site -- none of which are
    guessable. Use scripts/detect_ats.py to discover them from a careers URL.
    """
    tenant, host, site = c.get("tenant"), c.get("host", "wd1"), c.get("site")
    if not (tenant and site):
        return []
    base = f"https://{tenant}.{host}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    out: list[Job] = []
    offset, total, page = 0, None, 0
    while page < 25:                      # hard stop: 500 postings per board
        d = http_json(api, "workday",
                      data={"appliedFacets": {}, "limit": 20,
                            "offset": offset, "searchText": ""})
        if not isinstance(d, dict):
            break
        posts = d.get("jobPostings") or []
        if not posts:
            break
        # Workday reports the real total only on the first page; later pages
        # come back with total: 0. Taking that at face value stopped paging
        # after 40 postings on every tenant. Keep the first non-zero value.
        if total is None and d.get("total"):
            total = d["total"]
        for j in posts:
            path = j.get("externalPath") or ""
            jid = (j.get("bulletFields") or [path])[0]
            out.append(Job(
                uid=mk_uid("workday", tenant, str(jid)), ats="workday",
                company=c["name"], token=tenant, job_id=str(jid),
                title=j.get("title") or "", location_raw=j.get("locationsText") or "",
                url=f"{base}/{site}{path}",
                posted_at=parse_relative_posted(j.get("postedOn") or ""),
                detail_path=f"{base}/wday/cxs/{tenant}/{site}{path}",
            ))
        offset += 20
        page += 1
        if total is not None and offset >= total:
            break
    return out


# ------------------------------------------------------- HTML scraping tier

_SF_ROW = re.compile(
    r'<a[^>]*href="(?P<href>/job/[^"]+?)"[^>]*class="jobTitle-link"[^>]*>(?P<title>[^<]+)',
    re.I)
_SF_LOC = re.compile(r'<span[^>]*class="jobLocation"[^>]*>(?P<loc>[^<]*)', re.I)


def _list_successfactors(c: dict) -> list[Job]:
    """SAP SuccessFactors career-site HTML. Paginated via ?startrow=."""
    base = (c.get("base") or "").rstrip("/")
    if not base:
        return []
    out: list[Job] = []
    seen: set[str] = set()
    for start in range(0, 500, 25):
        page = http_text(f"{base}/search/?q=&startrow={start}", "successfactors")
        if not page:
            break
        rows = list(_SF_ROW.finditer(page))
        if not rows:
            break
        # Pair each title with the NEXT location span in document order. Index
        # alignment does not work here: these sites emit two jobLocation spans
        # per row (mobile and desktop layouts), which silently gave every PG&E
        # posting the same city -- including one actually in Fresno.
        locs = [(m.start(), m.group("loc").strip()) for m in _SF_LOC.finditer(page)]
        new = 0
        for m in rows:
            href = m.group("href")
            jid_m = re.search(r"/(\d{5,})/?$", href)
            jid = jid_m.group(1) if jid_m else href
            if jid in seen:
                continue
            seen.add(jid)
            new += 1
            loc = next((t for pos, t in locs if pos > m.end() and t), "")
            if not loc:
                loc = htmllib.unescape(href.split("/")[2]).replace("-", " ")
            out.append(Job(
                uid=mk_uid("successfactors", base, jid), ats="successfactors",
                company=c["name"], token=base, job_id=jid,
                title=htmllib.unescape(m.group("title")).strip(),
                location_raw=htmllib.unescape(loc),
                url=urllib.parse.urljoin(base + "/", href.lstrip("/")),
                detail_path=urllib.parse.urljoin(base + "/", href.lstrip("/")),
            ))
        if new == 0:
            break
    return out


# --------------------------------------------------------------- dispatch

LISTERS = {
    "greenhouse": _list_greenhouse,
    "lever": _list_lever,
    "ashby": _list_ashby,
    "workday": _list_workday,
    "successfactors": _list_successfactors,
}
SUPPORTED = sorted(LISTERS)

# Adapters whose listing already carries the description -- no detail fetch.
_LISTING_HAS_DESCRIPTION = {"lever", "ashby"}


def list_board(c: dict) -> tuple[list[Job], bool, str]:
    """-> (jobs, ok, content_hash). ok=False means the board could not be read."""
    ats = c.get("ats")
    fn = LISTERS.get(ats)
    if fn is None:
        return ([], False, "")
    try:
        jobs = fn(c)
    except Exception:
        return ([], False, "")
    if not jobs:
        # Distinguish "read the board, it is empty" from "could not read it".
        # Neither is fatal; both are reported as a zero-count board.
        return ([], True, "")
    sig = "|".join(sorted(f"{j.job_id}:{j.title}" for j in jobs))
    return (jobs, True, hashlib.sha1(sig.encode()).hexdigest())


def fetch_detail(job: Job) -> None:
    """Populate description (and comp, where exposed) for one job."""
    if job.description or not job.detail_path:
        return
    try:
        if job.ats == "greenhouse":
            d = http_json(
                f"https://boards-api.greenhouse.io/v1/boards/{job.token}"
                f"/jobs/{job.detail_path}", "greenhouse")
            if isinstance(d, dict):
                job.description = strip_html(d.get("content") or "")
                for r in d.get("pay_input_ranges") or []:
                    try:
                        mx = int(float(r.get("max_cents", 0))) // 100
                        if mx > (job.comp_max or 0):
                            job.comp_max = mx
                            job.comp_min = int(float(r.get("min_cents", 0))) // 100 or None
                    except (TypeError, ValueError):
                        pass

        elif job.ats == "workday":
            d = http_json(job.detail_path, "workday")
            info = (d or {}).get("jobPostingInfo") or {}
            job.description = strip_html(info.get("jobDescription") or "")
            # Real ISO date, unlike the relative string in the listing.
            if info.get("startDate"):
                job.posted_at = parse_when(info["startDate"]) or job.posted_at
            if info.get("location"):
                job.location_raw = info["location"]

        elif job.ats == "successfactors":
            page = http_text(job.detail_path, job.ats)
            if page:
                # The posting body sits in a `jobdescription` container. Slicing
                # from <main>/<body> instead returned nothing but the cookie
                # banner and nav menu, leaving every PG&E and Black & Veatch
                # posting unscorable.
                m = re.search(r'class="[^"]*jobdescription[^"]*"[^>]*>', page, re.I)
                if m:
                    body = page[m.end():]
                    end = re.search(r'<(footer|/main|div[^>]*class="[^"]*(footer|apply)[^"]*")',
                                    body, re.I)
                    job.description = strip_html(body[:end.start()] if end else body)[:20000]
                else:
                    job.description = strip_html(page)[:20000]
    except Exception:
        pass       # a missing description degrades scoring; it must not abort

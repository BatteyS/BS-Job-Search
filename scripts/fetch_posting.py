"""Fetch the full text of a job posting and save it next to the application.

The digest is not enough to tailor against. Six of the seven roles marked apply
on 2026-08-12 carried 539-character Adzuna snippets -- about eighty words. This
follows the posting URL (Adzuna links redirect to the employer), pulls the real
description, and writes it to a file.

    python scripts/fetch_posting.py --url <url> --out "Applications/X/Y - posting.txt"

Exit codes matter, because the caller has to know the difference between a
posting it can tailor against and one it cannot:

    0  got a usable description
    2  fetched, but too short to tailor from -- probably JS-rendered. Escalate
       to a browser fetch or ask for a paste.
    3  the posting looks closed or gone. Four of sixteen skips last digest were
       listings already dead, so this is worth catching before doing any work.
    4  network or HTTP failure

Extraction tries JSON-LD first. Most boards embed a schema.org JobPosting whose
`description` is the whole posting as clean HTML; scraping the rendered page is
the fallback, not the plan.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from html import unescape

try:
    import requests
except ImportError:
    # Python in a browser (Pyodide) has no requests. There the page fetches a
    # posting itself and calls describe() or classify() below, which need no
    # network.
    requests = None

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# Phrases that mean the listing is gone. Kept narrow on purpose -- a posting
# that merely mentions "closed loop" must not trip this.
DEAD_PATTERNS = [
    r"no longer accepting applications",
    r"this (job|position|posting) (is|has been) (closed|filled|expired)",
    r"(job|position|posting) (no longer|not) available",
    r"we are no longer accepting",
    r"this job posting has expired",
    r"the page you.{0,20}looking for.{0,20}(cannot be found|does not exist)",
]


def normalize_url(url: str) -> str:
    """Adzuna publishes two forms of the same ad and only one of them serves.

    Digest entries carry whichever the API returned. `land/ad/<id>` is a
    click-tracking redirect that answers HTTP 400 to a plain GET; `details/<id>`
    is the same ad and returns a page with a JSON-LD JobPosting in it.
    """
    return re.sub(r"(adzuna\.com)/land/ad/(\d+)", r"\1/details/\2", url)


def html_to_text(fragment: str) -> str:
    """Crude but dependency-free HTML to text. bs4 is not installed here."""
    s = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", fragment)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|section|article|ul|ol)>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return "\n".join(line.strip() for line in s.splitlines()).strip()


def walk_json(node):
    """Yield every dict in a JSON-LD blob, which may be a @graph or a list."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk_json(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_json(v)


def from_json_ld(html: str) -> tuple[str, dict]:
    """Pull the schema.org JobPosting description, plus whatever metadata it carries."""
    best, meta = "", {}
    for m in re.finditer(
            r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        for node in walk_json(data):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "JobPosting" not in types:
                continue
            desc = html_to_text(str(node.get("description", "")))
            if len(desc) > len(best):
                best = desc
                org = node.get("hiringOrganization") or {}
                meta = {
                    "title": node.get("title", ""),
                    "company": org.get("name", "") if isinstance(org, dict) else "",
                    "date_posted": node.get("datePosted", ""),
                    "valid_through": node.get("validThrough", ""),
                    "employment_type": node.get("employmentType", ""),
                }
    return best, meta


def from_page(html: str) -> str:
    """Fallback: the whole rendered page as text, minus the obvious chrome."""
    body = re.search(r"(?is)<body[^>]*>(.*)</body>", html)
    return html_to_text(body.group(1) if body else html)


def from_linkedin(html: str) -> str:
    """The posting on a LinkedIn guest job page, or "" if the page has none.

    LinkedIn wraps the posting in a show-more-less-html div and surrounds it
    with sign-in prompts and similar-jobs lists, with no JSON-LD. Read as a
    whole page, that chrome counted as description: on 2026-11-02 a listing
    whose description was only the company's blurb came back as 12,661 usable
    characters.
    """
    m = re.search(r'(?is)<div[^>]*class="[^"]*show-more-less-html__markup[^"]*"[^>]*>',
                  html)
    if not m:
        return ""
    depth = 1
    for tag in re.finditer(r"(?is)<(/?)div\b", html[m.end():]):
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            return html_to_text(html[m.end():m.end() + tag.start()])
    return html_to_text(html[m.end():])


def fetch_description(url: str, timeout: int = 30,
                      min_chars: int = 1200) -> tuple[str, dict, str]:
    """Pull one posting's text. Returns (text, meta, status).

    status is one of:
        ok     usable description
        short  fetched but too thin to judge from -- JS-rendered, usually
        dead   closed, expired, or gone
        error  network or HTTP failure

    Shared by the CLI below and by fetch_jobs.py, so the scan and the tailor
    step agree on what a posting says and on when one is dead. Two copies would
    drift, and the scan would keep listings the tailor step already knew were
    404.
    """
    try:
        r = requests.get(normalize_url(url),
                         headers={"User-Agent": UA, "Accept-Language": "en-US,en"},
                         timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return "", {}, "error"

    if r.status_code in (404, 410):
        return "", {"final_url": r.url}, "dead"
    if not r.ok:
        return "", {"final_url": r.url}, "error"
    return describe(r.text, r.url, min_chars)


def describe(html: str, url: str, min_chars: int = 1200) -> tuple[str, dict, str]:
    """(text, meta, status) for a posting page already fetched from `url`: the
    extraction and the verdict of fetch_description(), without the network."""
    text, meta = from_json_ld(html)
    meta["source"] = "json-ld"
    if len(text) < min_chars and "linkedin.com/jobs" in url:
        # Never the whole page here: its chrome would pass for a description.
        posting = from_linkedin(html)
        if len(posting) > len(text):
            text, meta["source"] = posting, "linkedin"
    elif len(text) < min_chars:
        page = from_page(html)
        if len(page) > len(text):
            text, meta["source"] = page, "page-text"
    meta["final_url"] = url
    return text, meta, classify(text, meta, min_chars)


def classify(text: str, meta: dict, min_chars: int = 1200) -> str:
    """ok, short, or dead, for a posting's text and its metadata, however they
    were read: from a page here, or from a job board's API by another host."""
    if any(re.search(p, text.lower()[:4000]) for p in DEAD_PATTERNS):
        return "dead"

    # validThrough is the employer's own expiry date, which beats guessing from
    # prose. Compared date-only so a same-day expiry is not called dead.
    expires = str(meta.get("valid_through", ""))[:10]
    if (re.fullmatch(r"\d{4}-\d{2}-\d{2}", expires)
            and expires < datetime.now().strftime("%Y-%m-%d")):
        return "dead"

    return "ok" if len(text) >= min_chars else "short"


META_KEYS = ("title", "company", "date_posted", "valid_through", "employment_type")


def save_posting(path: str, where: str, meta: dict, text: str) -> None:
    """Write a posting beside its application: a short header, then the text.
    Shared with digest_applies.py --fetch, so every saved posting reads alike."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    header = [f"# source: {where}"] + [f"# {k}: {meta[k]}" for k in META_KEYS if meta.get(k)]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(header) + "\n\n" + text + "\n")


def main() -> int:
    # Piped, stdout is block-buffered and stderr is not, so a verdict printed
    # to stderr would land above the report it ends.
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", help="file to write the posting text to")
    ap.add_argument("--min-chars", type=int, default=1200,
                    help="below this the description is treated as unusable")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    text, meta, status = fetch_description(args.url, args.timeout, args.min_chars)
    where = meta.get("final_url", args.url)

    if status == "dead":
        print(f"DEAD  closed, expired, or gone  {where}", file=sys.stderr)
        return 3
    if status == "error":
        print(f"FETCH FAILED  {where}", file=sys.stderr)
        return 4

    print(f"final url : {where}")
    print(f"source    : {meta.get('source', '')}")
    print(f"chars     : {len(text)}")
    for k in META_KEYS:
        if meta.get(k):
            print(f"{k:10}: {meta[k]}")

    if args.out:
        save_posting(args.out, where, meta, text)
        print(f"saved     : {args.out}")

    if status == "short":
        print(f"TOO SHORT  {len(text)} chars < {args.min_chars}. Probably JS-rendered; "
              "fetch it in a browser or paste the posting.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

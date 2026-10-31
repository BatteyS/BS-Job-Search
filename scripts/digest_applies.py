"""Read a digest and report the entries marked `apply`.

Purely mechanical: it parses what the user already decided and computes where each
resume would be filed. No scoring, no cluster inference, no judgment -- those
belong to the tailor-digest skill, the same way fetch_jobs.py stays out of the
scoring that follows it.

    python scripts/digest_applies.py                 # newest digest, as a table
    python scripts/digest_applies.py --json          # same, for the skill
    python scripts/digest_applies.py --date 2026-08-12
    python scripts/digest_applies.py --pending       # only the not-yet-built

Entries are matched on the checkbox the user ticks:

    - [x] apply
    - [ ] skip -- reason:

Both boxes ticked, or neither, is reported rather than guessed at.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_resume import safe_name  # noqa: E402  -- one definition, no drift

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIGESTS = os.path.join(ROOT, "digests")
APPS = os.path.join(ROOT, "Applications")

EM_DASH = chr(8212)   # separates company from title in a heading
MIDDOT = chr(183)     # separates the fields of a heading

RE_HEADING = re.compile(r"^###\s+(\d+)\.\s+(.*?)\s*$")
RE_CHECKBOX = re.compile(r"^-\s*\[([ xX])\]\s*(apply|skip)\b", re.I)
RE_SCORE = re.compile(r"^\*\*(\d+)\*\*$")
RE_RESUME = re.compile(r"^\*\*Resume:\*\*\s*([A-Za-z_-]+)")
RE_URL = re.compile(r"\[View posting\]\(([^)]+)\)")
RE_FIELD = re.compile(r"^\*\*([A-Za-z ]+):\*\*\s*(.*)$")


def newest_digest() -> str:
    """Newest by filename -- the names are ISO dates, so that is chronological."""
    files = sorted(glob.glob(os.path.join(DIGESTS, "*.md")))
    if not files:
        raise SystemExit(f"No digests in {os.path.relpath(DIGESTS, ROOT)}")
    return files[-1]


def norm_company(name: str) -> str:
    """Fold a company name so near-duplicate folders can be spotted.

    Applications/ already holds "Black and Veatch" while the digest writes
    "Black & Veatch". Left alone that becomes two folders for one employer --
    exactly the split the tailor-resume skill warns about.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("&", " and "))


def split_heading(text: str) -> tuple[str, str, int | None, str, str]:
    """Company, title, score, metro, comp from one `###` heading."""
    fields = [f.strip() for f in text.split(MIDDOT)]
    company, _, title = fields[0].partition(EM_DASH)

    score, metro, comp = None, "", ""
    for f in fields[1:]:
        m = RE_SCORE.match(f)
        if m:
            score = int(m.group(1))
        elif f.startswith("$"):
            comp = f
        elif not metro:
            # "Remote (-6)" / "New York (-4)": the parenthetical is the location
            # penalty the scorer applied, not part of the place name.
            metro = re.sub(r"\s*\(.*?\)\s*$", "", f).strip()
    return company.strip(), title.strip(), score, metro, comp


def entry_blocks(lines: list[str]) -> list[tuple[int, str, list[str]]]:
    """Each `###` heading owns its lines up to the next `###` or `##`."""
    blocks: list[tuple[int, str, list[str]]] = []
    cur: list[str] | None = None
    for line in lines:
        m = RE_HEADING.match(line)
        if m:
            blocks.append((int(m.group(1)), m.group(2), []))
            cur = blocks[-1][2]
        elif line.startswith("## "):
            cur = None
        elif cur is not None:
            cur.append(line)
    return blocks


def read_prose(body: list[str]) -> dict[str, str]:
    """Pull the Why and Gaps paragraphs, which wrap across several lines."""
    out: dict[str, str] = {}
    key = None
    for line in body:
        f = RE_FIELD.match(line)
        if f:
            # Any other bold field ends the current paragraph -- notably
            # **Resume:**, which sits between Why and Gaps.
            key = f.group(1).lower() if f.group(1) in ("Why", "Gaps") else None
            if key:
                out[key] = f.group(2)
        elif not line.strip():
            key = None
        elif key and not line.startswith(("[", "- ")):
            out[key] += " " + line.strip()
    return out


def parse(path: str) -> dict:
    lines = open(path, encoding="utf-8").read().splitlines()

    existing = {}
    if os.path.isdir(APPS):
        existing = {norm_company(d): d for d in os.listdir(APPS)
                    if os.path.isdir(os.path.join(APPS, d))}

    entries = []
    for n, heading, body in entry_blocks(lines):
        company, title, score, metro, comp = split_heading(heading)

        marks = {}
        for line in body:
            m = RE_CHECKBOX.match(line)
            if m:
                marks[m.group(2).lower()] = m.group(1).lower() == "x"

        variant = ""
        url = ""
        for line in body:
            m = RE_RESUME.match(line)
            if m:
                variant = m.group(1).lower()
            u = RE_URL.search(line)
            if u:
                url = u.group(1)
        prose = read_prose(body)

        folder_name = safe_name(company)
        near = existing.get(norm_company(company))
        note = ""
        if near and near != folder_name:
            note = (f"Applications/{near} already exists and reads as the same "
                    f"employer -- confirm before creating '{folder_name}'")
            folder_name = near

        stem = safe_name(title)
        folder = os.path.join(APPS, folder_name)
        pdf = os.path.join(folder, stem + ".pdf")
        tex = os.path.join(folder, stem + ".tex")
        rel = lambda p: os.path.relpath(p, ROOT).replace(os.sep, "/")  # noqa: E731

        entries.append({
            "n": n,
            "company": company,
            "title": title,
            "score": score,
            "metro": metro,
            "comp": comp,
            "suggested_variant": variant,
            "snippet": any("`snippet`" in l for l in body),
            "url": url,
            "why": prose.get("why", ""),
            "gaps": prose.get("gaps", ""),
            "marked_apply": marks.get("apply", False),
            "marked_skip": marks.get("skip", False),
            "folder": rel(folder),
            "pdf": rel(pdf),
            "tex": rel(tex),
            "already_built": os.path.exists(pdf) and os.path.exists(tex),
            "folder_note": note,
        })

    return {
        "digest": os.path.relpath(path, ROOT).replace(os.sep, "/"),
        "date": os.path.splitext(os.path.basename(path))[0],
        "total_entries": len(entries),
        "apply": [e for e in entries if e["marked_apply"] and not e["marked_skip"]],
        "conflicts": [e for e in entries if e["marked_apply"] and e["marked_skip"]],
        "unmarked": [e for e in entries
                     if not e["marked_apply"] and not e["marked_skip"]],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest", help="path to a digest (default: the newest)")
    ap.add_argument("--date", help="digest date, YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--pending", action="store_true",
                    help="only entries whose PDF and .tex are not both filed yet")
    args = ap.parse_args()

    if args.digest:
        path = args.digest
    elif args.date:
        path = os.path.join(DIGESTS, args.date + ".md")
    else:
        path = newest_digest()
    if not os.path.exists(path):
        raise SystemExit(f"No such digest: {path}")

    result = parse(path)
    if args.pending:
        result["apply"] = [e for e in result["apply"] if not e["already_built"]]

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"digest    : {result['digest']}")
    print(f"entries   : {result['total_entries']}")
    print(f"apply     : {len(result['apply'])}"
          + ("  (pending only)" if args.pending else ""))
    if result["unmarked"]:
        nums = ", #".join(str(e["n"]) for e in result["unmarked"])
        print(f"unmarked  : {len(result['unmarked'])}  (#{nums})")
    print()

    for e in result["apply"]:
        state = "built" if e["already_built"] else "TO BUILD"
        print(f"  #{e['n']:<3} {e['company']} - {e['title']}")
        print(f"       {e['score']} - {e['metro']}"
              + (f" - {e['comp']}" if e["comp"] else "")
              + f" - suggests {e['suggested_variant'] or '?'}"
              + ("  [snippet]" if e["snippet"] else ""))
        print(f"       -> {e['pdf']}  [{state}]")
        if e["folder_note"]:
            print(f"       !! {e['folder_note']}")
        print()

    for e in result["conflicts"]:
        print(f"  CONFLICT #{e['n']} {e['company']} - apply and skip both ticked")
    if not result["apply"]:
        print("  nothing to build" if args.pending else "  nothing marked apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

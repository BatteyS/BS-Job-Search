"""Read a digest and report the entries marked `apply`, and which want a letter.

Purely mechanical: it parses what the user already decided and computes where each
resume and letter would be filed. No scoring, no cluster inference, no judgment --
those belong to the tailor-digest skill, the same way fetch_jobs.py stays out of the
scoring that follows it.

    python scripts/digest_applies.py                 # newest digest, as a table
    python scripts/digest_applies.py --json          # same, for the skill
    python scripts/digest_applies.py --date 2026-08-12
    python scripts/digest_applies.py --pending       # only the not-yet-built
    python scripts/digest_applies.py --verdicts      # the marks, as a feedback.md section
    python scripts/digest_applies.py --fetch         # save every apply's posting

--verdicts prints the marks in profile/feedback.md's format, for the user to check
before it is appended -- the calibration loop stalled for months on that step. --fetch
saves each apply's posting beside where its resume will go; when the digest's link
fails or comes back thin, it looks the role up on the employer's own board in
sources/companies.yaml, which is where Redwood's posting was when LinkedIn refused it.

Entries are matched on the checkboxes the user ticks:

    - [x] apply
    - [ ] skip -- reason:
    - [x] cover letter

`cover letter` rides on `apply`: it asks for a letter beside that role's resume.
Digests written before the box existed have no such line, and read as no letter.
Apply and skip both ticked, a letter on a skipped role, a letter with neither, and
no box at all are each reported rather than guessed at.
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
RE_CHECKBOX = re.compile(r"^-\s*\[([ xX])\]\s*(apply|skip|cover\s+letter)\b", re.I)
# "- [x] skip — reason: wants 8+ years" -> "wants 8+ years"
RE_SKIP_REASON = re.compile(r"^-\s*\[[xX]\]\s*skip\b\s*[—–-]*\s*(?:reason\s*:)?\s*(.*?)\s*$",
                            re.I)
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
        # A leading underscore marks a folder that is not an employer.
        existing = {norm_company(d): d for d in os.listdir(APPS)
                    if not d.startswith("_")
                    and os.path.isdir(os.path.join(APPS, d))}

    entries = []
    for n, heading, body in entry_blocks(lines):
        company, title, score, metro, comp = split_heading(heading)

        marks = {}
        reason = ""
        for line in body:
            m = RE_CHECKBOX.match(line)
            if m:
                box = m.group(2).lower()
                marks["letter" if box.startswith("cover") else box] = m.group(1).lower() == "x"
            r = RE_SKIP_REASON.match(line)
            if r:
                reason = r.group(1)

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
        # Where build_letter.py files it.
        letter_pdf = os.path.join(folder, stem + " - cover letter.pdf")
        posting = os.path.join(folder, stem + " - posting.txt")
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
            "marked_letter": marks.get("letter", False),
            "skip_reason": reason,
            "folder": rel(folder),
            "posting": rel(posting),
            "pdf": rel(pdf),
            "tex": rel(tex),
            "letter_pdf": rel(letter_pdf),
            "already_built": os.path.exists(pdf) and os.path.exists(tex),
            "letter_built": os.path.exists(letter_pdf),
            "folder_note": note,
        })

    apply = [e for e in entries if e["marked_apply"] and not e["marked_skip"]]
    return {
        "digest": os.path.relpath(path, ROOT).replace(os.sep, "/"),
        "date": os.path.splitext(os.path.basename(path))[0],
        "total_entries": len(entries),
        "apply": apply,
        "letters": [e for e in apply if e["marked_letter"]],
        "skip": [e for e in entries if e["marked_skip"]
                 and not (e["marked_apply"] or e["marked_letter"])],
        # A letter is for a role being applied to, so one on a skipped role
        # contradicts the skip as much as a ticked apply does.
        "conflicts": [e for e in entries
                      if e["marked_skip"] and (e["marked_apply"] or e["marked_letter"])],
        "letter_only": [e for e in entries if e["marked_letter"]
                        and not e["marked_apply"] and not e["marked_skip"]],
        "unmarked": [e for e in entries if not
                     (e["marked_apply"] or e["marked_skip"] or e["marked_letter"])],
    }


def verdicts(result: dict) -> str:
    """The digest's marks as a section of profile/feedback.md, followed by what
    to settle before appending it: skips with no reason, and unmarked entries
    whose resume is already filed, which were probably applied to."""
    def role(e: dict) -> str:
        return f"{e['company']} {EM_DASH} {e['title']}"

    apply, skip = result["apply"], result["skip"]
    out = [f"### {result['date']} {EM_DASH} {result['total_entries']} scored, "
           f"{len(apply)} apply, {len(skip)} skip", ""]
    if apply:
        out += [f"**Applied ({len(apply)}).**", "", "| # | Role | Score | Metro |",
                "|---|---|---|---|"]
        out += [f"| {e['n']} | {role(e)} | {e['score'] or ''} | {e['metro']} |" for e in apply]
        out.append("")
    if skip:
        out += [f"**Skipped ({len(skip)}).**", "", "| # | Role | Score | Reason |",
                "|---|---|---|---|"]
        out += [f"| {e['n']} | {role(e)} | {e['score'] or ''} | {e['skip_reason']} |"
                for e in skip]
        out.append("")

    check = [f"  #{e['n']} {role(e)}: skipped with no reason, which teaches the "
             "scorer nothing" for e in skip if not e["skip_reason"]]
    check += [f"  #{e['n']} {role(e)}: unmarked, but its resume is filed -- "
              "probably applied" for e in result["unmarked"] if e["already_built"]]
    if check:
        out += ["Settle before appending:"] + check
    return "\n".join(out).rstrip() + "\n"


def find_on_board(company: str, title: str, boards: list[dict],
                  list_board, fetch_detail) -> tuple[object | None, str]:
    """The posting titled `title` on `company`'s own board, if
    sources/companies.yaml lists one. Returns (job, why not)."""
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

    board = next((b for b in boards if norm_company(b.get("name", "")) == norm_company(company)),
                 None)
    if board is None:
        return None, "the employer's board is not in sources/companies.yaml"
    jobs, ok, _ = list_board(board)
    if not ok:
        return None, f"its {board.get('ats')} board could not be read"
    want = norm(title)
    exact = [j for j in jobs if norm(j.title) == want]
    near = exact or [j for j in jobs if want in norm(j.title) or norm(j.title) in want]
    if not near:
        return None, f"no posting titled like that on its {board.get('ats')} board"
    if len(exact) != 1 and len({norm(j.title) for j in near}) > 1:
        return None, ("several postings on its board could be it: "
                      + "; ".join(j.title for j in near[:4]))
    job = near[0]
    if not job.description:
        fetch_detail(job)
    return (job, "") if job.description else (None, "the board's posting has no text")


def fetch_postings(entries: list[dict]) -> int:
    """Save each entry's posting beside where its resume will go. Returns 2 if
    any still needs a browser or a paste, else 0."""
    import yaml

    import fetch_posting
    from ats_adapters import fetch_detail, list_board

    companies_yaml = os.path.join(ROOT, "sources/companies.yaml")
    boards: list[dict] = []
    if os.path.exists(companies_yaml):
        d = yaml.safe_load(open(companies_yaml, encoding="utf-8")) or {}
        boards = list(d.get("companies") or []) + list(d.get("manual") or [])

    stuck = 0
    for e in entries:
        path = os.path.join(ROOT, e["posting"])
        print(f"  #{e['n']:<3} {e['company']} - {e['title']}")
        if os.path.exists(path):
            print(f"       already saved -> {e['posting']}")
            continue
        status = "no link in the digest"
        if e["url"]:
            text, meta, status = fetch_posting.fetch_description(e["url"])
            if status == "dead":
                print("       DEAD -- closed, expired, or gone. Skip this role.")
                continue
            if status == "ok":
                fetch_posting.save_posting(path, meta.get("final_url", e["url"]), meta, text)
                print(f"       saved -> {e['posting']}")
                continue
        job, why = find_on_board(e["company"], e["title"], boards, list_board, fetch_detail)
        if job is not None:
            meta = {"title": job.title, "company": e["company"], "date_posted": job.posted_at}
            fetch_posting.save_posting(path, job.url, meta, job.description)
            print(f"       the link gave '{status}'; saved from the employer's "
                  f"{job.ats} board -> {e['posting']}")
            continue
        stuck += 1
        print(f"       NEEDS A BROWSER OR A PASTE -- the link gave '{status}', and {why}")
    return 2 if stuck else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest", help="path to a digest (default: the newest)")
    ap.add_argument("--date", help="digest date, YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--pending", action="store_true",
                    help="only entries whose PDF and .tex are not both filed yet, "
                         "or whose letter is not")
    ap.add_argument("--verdicts", action="store_true",
                    help="print the marks as a section for profile/feedback.md")
    ap.add_argument("--fetch", action="store_true",
                    help="save each apply's posting, from the employer's board if the "
                         "link fails")
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
        # A filed resume whose letter is still to write stays: the letter is pending.
        result["apply"] = [e for e in result["apply"] if not e["already_built"]
                           or (e["marked_letter"] and not e["letter_built"])]
        result["letters"] = [e for e in result["letters"] if not e["letter_built"]]

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.verdicts:
        print(verdicts(result), end="")
        return 0
    if args.fetch:
        print(f"digest    : {result['digest']}")
        return fetch_postings(result["apply"])

    print(f"digest    : {result['digest']}")
    print(f"entries   : {result['total_entries']}")
    print(f"apply     : {len(result['apply'])}"
          + ("  (pending only)" if args.pending else ""))
    print(f"letters   : {len(result['letters'])}")
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
        if e["marked_letter"]:
            print(f"       -> {e['letter_pdf']}  "
                  f"[{'written' if e['letter_built'] else 'TO WRITE'}]")
        if e["folder_note"]:
            print(f"       !! {e['folder_note']}")
        print()

    for e in result["conflicts"]:
        ticked = " and ".join(name for name, on in (("apply", e["marked_apply"]),
                                                    ("cover letter", e["marked_letter"])) if on)
        print(f"  CONFLICT #{e['n']} {e['company']} - {ticked} ticked with skip")
    for e in result["letter_only"]:
        print(f"  LETTER ONLY #{e['n']} {e['company']} - cover letter ticked, apply not")
    if not result["apply"]:
        print("  nothing to build" if args.pending else "  nothing marked apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

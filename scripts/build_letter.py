"""Render a cover letter whose every factual claim cites where it came from.

The letter's words are written by the cover-letter skill, not by this script.
What stays mechanical is what must not drift, the same way it does for resumes:

  * Each paragraph names its sources -- a content/master.md bullet, a passage of
    content/story.md, a quote from the posting, or something the user said --
    and every source has to resolve to text that exists. A master.md or
    story.md fragment must match exactly one passage.
  * Every number in a paragraph, in digits or words, has to appear in one of
    that paragraph's sources. An invented metric is the most likely fabrication
    in a letter, and the cheapest one to catch.
  * The letter has to fit one page. It is never trimmed to fit: cutting a
    paragraph changes what the letter says, so an overlong letter fails and the
    writer shortens it.

The report lists each paragraph beside its sources, so the user can check every
claim before anything is sent.

    python scripts/build_letter.py --letter letter.json \\
        --company "Acme Energy" --title "Project Engineer"
    python scripts/build_letter.py --letter letter.json --check    # sources only

--company/--title files Applications/<Company>/<Title> - cover letter.{pdf,tex,txt}
and reads the posting saved beside it (<Title> - posting.txt) to check posting
quotes; --posting names another file. The .txt is the same letter as plain text,
for application forms that want it pasted into a box.

The letter file:

    {
      "greeting": "Dear Hiring Team,",                 optional
      "paragraphs": [
        {"text": "...",
         "sources": [{"master": "Managed execution and grant compliance"},
                     {"story": "I came to energy through"},
                     {"posting": "deploy storage at utility scale"},
                     {"user": "what the user said, in their words"}]}
      ],
      "closing": "Sincerely,",                         optional
      "date": "October 29, 2026",                      optional, default today
      "recipient": ["Acme Energy"]                     optional, default the company
    }
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# One definition of each, shared with the resume builder, so the two cannot drift.
from build_resume import (APPS, BUILD, CONTACT, LATEX, MASTER, PDFDIR, ROOT,  # noqa: E402
                          compile_pdf, contact_line, load_contact, master_format,
                          norm_match, parse_master, safe_name, text_to_latex)

STORY = os.path.join(ROOT, "content/story.md")
TEMPLATE = os.path.join(LATEX, "letter.tex")

SOURCE_KINDS = ("master", "story", "posting", "user")

# Tried in order until the letter fits one page. Past the last tier the letter
# is too long, and the fix is fewer words, not smaller margins.
LETTER_TIERS = [
    {"MARGIN": "1in", "PARSKIP": "10pt", "SIGNATURE_GAP": "18pt"},
    {"MARGIN": "0.85in", "PARSKIP": "8pt", "SIGNATURE_GAP": "14pt"},
    {"MARGIN": "0.7in", "PARSKIP": "6pt", "SIGNATURE_GAP": "10pt"},
]

# A letter a recruiter reads is short. Outside this range is a warning, not an
# error: some forms cap length, some postings ask for more.
WORDS_LOW, WORDS_HIGH = 150, 400

# Phrases that make a letter read as boilerplate. Warnings only -- the writer
# decides -- but each one costs the letter the specificity it exists to show.
STOCK_PHRASES = [
    "i am writing to express", "i am excited to apply", "passionate", "synergy",
    "dynamic", "team player", "fast-paced", "go-getter", "think outside the box",
    "results-driven", "detail-oriented", "perfect fit", "great fit", "dream job",
    "hit the ground running", "wear many hats", "proven track record",
]

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# Spelled-out quantities count too -- "three years in Epic" is as much a claim as
# "3 years". "One" is left out because it is rarely a quantity ("one of the",
# "one-on-one"), and so are multipliers like "hundred", which would turn "two
# hundred" into 2 and 100 and never match a source that says 200.
NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    ["two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
     "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
     "nineteen", "twenty"], start=2)}
NUMBER_WORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60",
                     "seventy": "70", "eighty": "80", "ninety": "90", "dozen": "12"})
NUMBER_WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.I)
_FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                       "–": "-", "—": "-"})


def norm(s: str) -> str:
    """norm_match, plus curly quotes and dashes folded to plain ones -- postings
    and story.md are pasted from anywhere."""
    return norm_match(s.translate(_FOLD))


def numbers(s: str) -> set[str]:
    """Every quantity in s, as digits: "1,184" -> 1184, "three" -> 3."""
    found = {n.replace(",", "") for n in NUMBER.findall(s)}
    return found | {NUMBER_WORDS[w.lower()] for w in NUMBER_WORD.findall(s)}


def story_passages(path: str) -> list[str]:
    """story.md's passages: each paragraph, and each list item on its own.
    Headings organize the file and are not claims, so they are skipped."""
    raw = open(path, encoding="utf-8").read()
    raw = re.sub(r"\A---\n.*?\n---\n", "", raw, flags=re.S)
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append(" ".join(buf))
            buf.clear()

    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            flush()
            continue
        if re.match(r"[-*]\s+", s):
            flush()
            s = re.sub(r"^[-*]\s+", "", s)
        buf.append(s)
    flush()
    return out


class Sources:
    """Everything a paragraph may cite, and the lookup for each kind."""

    def __init__(self, master: str, story: str, posting: str | None):
        _, entries = parse_master(master)
        self.bullets = [b.text for e in entries for b in e.bullets]
        self.headings = [" | ".join(p for p in e.title_parts if p)
                         for e in entries if not e.meta.get("list")]
        self.story_path = story
        self.story = story_passages(story) if os.path.exists(story) else None
        self.posting_path = posting
        self.posting = (norm(open(posting, encoding="utf-8").read())
                        if posting and os.path.exists(posting) else None)

    def resolve(self, kind: str, fragment: str) -> tuple[str | None, str]:
        """(the passage the fragment names, or None) and why not."""
        f = norm(fragment)
        if not f:
            return None, "is empty"
        if kind == "user":
            return fragment, ""
        if kind == "posting":
            if self.posting is None:
                return None, ("cannot be checked: no posting file. Save it with "
                              "fetch_posting.py, or pass --posting")
            return (fragment, "") if f in self.posting else (None, "is not in the posting")
        if kind == "story":
            if self.story is None:
                return None, f"cannot be checked: {os.path.relpath(self.story_path, ROOT)} does not exist"
            pool = self.story
        else:
            pool = [b for b in self.bullets if f in norm(b)] or self.headings
        hits = [p for p in pool if f in norm(p)]
        if len(hits) == 1:
            return hits[0], ""
        if not hits:
            return None, f"matches nothing in {kind}"
        return None, f"matches {len(hits)} passages in {kind}; use a longer fragment"


def check(letter: dict, sources: Sources) -> tuple[list[dict], list[str], list[str]]:
    """Resolve every source and run the checks. Returns (paragraph reports,
    errors, warnings). Errors stop the build; warnings are for the writer."""
    errors: list[str] = []
    warnings: list[str] = []
    paras = letter.get("paragraphs") or []
    if not paras:
        errors.append("the letter has no paragraphs")
    reports = []
    for i, p in enumerate(paras, 1):
        text = (p.get("text") or "").strip()
        if not text:
            errors.append(f"paragraph {i} has no text")
        resolved = []
        for src in p.get("sources") or []:
            if not (isinstance(src, dict) and len(src) == 1 and next(iter(src)) in SOURCE_KINDS):
                errors.append(f"paragraph {i}: a source must be one of "
                              f"{', '.join(SOURCE_KINDS)}, as {{\"master\": \"...\"}}; got {src!r}")
                continue
            kind, fragment = next(iter(src.items()))
            found, why = sources.resolve(kind, str(fragment))
            if found is None:
                errors.append(f"paragraph {i}: {kind} source {str(fragment)[:60]!r} {why}")
            resolved.append((kind, str(fragment), found))
        backing = " ".join(f for _, _, f in resolved if f)
        unsourced = sorted(numbers(text) - numbers(backing), key=lambda n: (len(n), n))
        if unsourced:
            errors.append(f"paragraph {i}: {', '.join(unsourced)} appear(s) in none of its "
                          "sources -- cite the passage that says it, or take it out")
        low = text.lower()
        stock = [s for s in STOCK_PHRASES if s in low]
        if stock:
            warnings.append(f"paragraph {i}: stock phrasing ({', '.join(stock)})")
        reports.append({"text": text, "sources": resolved})
    words = sum(len(r["text"].split()) for r in reports)
    if paras and not WORDS_LOW <= words <= WORDS_HIGH:
        warnings.append(f"{words} words; most read best at {WORDS_LOW}-{WORDS_HIGH}")
    return reports, errors, warnings


def today() -> str:
    d = date.today()
    return f"{d:%B} {d.day}, {d.year}"


def render(letter: dict, front: dict, company: str, tier: dict) -> str:
    t = text_to_latex
    recipient = letter.get("recipient")
    if recipient is None:
        recipient = [company] if company else []
    subs = {
        "NAME": t(front.get("name", "")),
        "CONTACT": contact_line(front),
        "DATE": t(letter.get("date") or today()),
        "RECIPIENT": (" " + chr(92) * 2 + "\n").join(t(r) for r in recipient),
        "GREETING": t(letter.get("greeting") or "Dear Hiring Team,"),
        "BODY": "\n\n".join(t(p["text"].strip()) for p in letter["paragraphs"]),
        "CLOSING": t(letter.get("closing") or "Sincerely,"),
        **tier,
    }
    tpl = open(TEMPLATE, encoding="utf-8").read()
    for k, v in subs.items():
        tpl = tpl.replace(f"%%{k}%%", v)
    return tpl


def plain_text(letter: dict, front: dict) -> str:
    """The letter as an application form's text box wants it: no header."""
    parts = [letter.get("greeting") or "Dear Hiring Team,"]
    parts += [p["text"].strip() for p in letter["paragraphs"]]
    parts.append(f"{letter.get('closing') or 'Sincerely,'}\n{front.get('name', '')}")
    return "\n\n".join(parts) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--letter", required=True, metavar="JSON", help="the letter file")
    ap.add_argument("--company", help="file under Applications/<company>/")
    ap.add_argument("--title", help="the job title the files are named after")
    ap.add_argument("--posting", help="the posting text, for checking posting quotes "
                                      "(default: <Title> - posting.txt beside the files)")
    ap.add_argument("--check", action="store_true",
                    help="resolve sources and run the checks only; build nothing")
    ap.add_argument("--out", default="editing_letter", help="build basename")
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--story", default=STORY)
    ap.add_argument("--contact", default=CONTACT)
    args = ap.parse_args()
    if bool(args.company) != bool(args.title):
        print("--company and --title go together", file=sys.stderr)
        return 2

    with open(args.letter, encoding="utf-8") as fh:
        letter = json.load(fh)
    posting = args.posting
    if not posting and args.company:
        guess = os.path.join(APPS, safe_name(args.company),
                             f"{safe_name(args.title)} - posting.txt")
        posting = guess if os.path.exists(guess) else None

    sources = Sources(args.master, args.story, posting)
    reports, errors, warnings = check(letter, sources)
    master_front, _ = parse_master(args.master)
    mode, _ = master_format(args.master, master_front)

    rel = lambda p: os.path.relpath(p, ROOT)  # noqa: E731
    print(f"letter    : {args.letter}")
    print(f"master    : {rel(args.master)} (as {mode})")
    print(f"story     : {rel(args.story)}" + ("" if sources.story is not None else "  (missing)"))
    print(f"posting   : {rel(posting) + ' (quotes checked)' if sources.posting is not None else 'none -- posting quotes cannot be checked'}")
    print(f"words     : {sum(len(r['text'].split()) for r in reports)}")

    print("\nparagraphs and the sources behind them:")
    for i, r in enumerate(reports, 1):
        print(f"  [{i}] {r['text'][:110]}{'...' if len(r['text']) > 110 else ''}")
        if not r["sources"]:
            print("      (no sources -- this paragraph must make no factual claim)")
        for kind, fragment, found in r["sources"]:
            shown = found if found else f"NOT FOUND: {fragment}"
            print(f"      {kind:8}: {shown[:110]}{'...' if len(shown) > 110 else ''}")

    for w in warnings:
        print(f"\nnote: {w}")
    if errors:
        print("\nNOT BUILT -- fix these first:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    if args.check:
        print("\nchecks passed (--check: nothing built)")
        return 0

    front = load_contact(args.contact)
    texpath = os.path.join(LATEX, args.out + ".tex")
    pages, err, tier = 0, "", LETTER_TIERS[0]
    for tier in LETTER_TIERS:
        with open(texpath, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(letter, front, args.company or "", tier))
        ok, pages, err = compile_pdf(texpath)
        if not ok:
            print(f"build failed:\n{err}", file=sys.stderr)
            return 1
        if pages <= 1:
            break
    if pages > 1:
        print(f"\nNOT FILED -- the letter runs to {pages} pages even at "
              f"{tier['MARGIN']} margins. Cut words; a letter is never trimmed "
              "mechanically, because that changes what it says.", file=sys.stderr)
        return 1

    pdf_src = os.path.join(BUILD, args.out + ".pdf")
    os.makedirs(PDFDIR, exist_ok=True)
    shutil.copy(pdf_src, os.path.join(PDFDIR, args.out + ".pdf"))
    print(f"\npages     : 1 (margins {tier['MARGIN']})")
    print(f"tex       : {texpath}")

    if args.company:
        dest_dir = os.path.join(APPS, safe_name(args.company))
        os.makedirs(dest_dir, exist_ok=True)
        stem = os.path.join(dest_dir, f"{safe_name(args.title)} - cover letter")
        shutil.copy(pdf_src, stem + ".pdf")
        shutil.copy(texpath, stem + ".tex")
        with open(stem + ".txt", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(plain_text(letter, front))
        print(f"filed     : {stem}.pdf")
        print(f"            {stem}.tex")
        print(f"            {stem}.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

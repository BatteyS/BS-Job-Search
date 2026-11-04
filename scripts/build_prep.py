"""Check and file an interview prep sheet whose every claim cites its source.

The interview-prep skill writes the sheet's words; this script keeps what must
not drift, with the checks a cover letter gets, from the same code
(build_letter.check_passage):

  * Every source resolves to text that exists: a content/master.md bullet or
    role heading, a passage of content/story.md (never one under "Keep out of
    letters"), a phrase quoted exactly from the posting, or what the user said.
    A master.md or story.md fragment must match exactly one passage.
  * Every number in a passage, in digits or words, appears in that passage's
    own sources. A rehearsed answer with a better number than the real one is
    the likeliest thing to go wrong, and the cheapest to catch.

And what a prep sheet adds:

  * Every likely question, and every question to ask the employer, says what it
    was drawn from, and every gap quotes the posting where it asks for that
    thing, so none of them is a guess.
  * An answer cites a master.md bullet, a story.md passage, or the user's own
    words. A posting quote says what the employer wants, never what the user
    did, so it cannot back an answer alone.
  * An answer about past work is told as situation, action and result; a
    question about motivation ("why this role?") gets one answer instead. A
    question the user's files cannot answer stays on the sheet unanswered, as
    one to prepare, rather than being answered for them.

    python scripts/build_prep.py --prep prep.json \\
        --company "Acme Energy" --title "Project Engineer" --check
    python scripts/build_prep.py --prep prep.json \\
        --company "Acme Energy" --title "Project Engineer"

--company/--title file Applications/<Company>/<Title> - interview prep.md and
read the posting saved beside it (<Title> - posting.txt); --posting names
another file. The sheet is Markdown, which the page's Applications tab shows.

The prep file:

    {
      "date": "November 3, 2026",                      optional, default today
      "questions": [
        {"question": "Tell me about a time you ...",
         "from": [{"posting": "the phrase that makes it likely"}],
         "situation": "...", "action": "...", "result": "...",
         "sources": [{"master": "..."}, {"story": "..."}]},
        {"question": "Why this role?", "from": [{"posting": "..."}],
         "answer": "...", "sources": [{"story": "..."}, {"user": "..."}]},
        {"question": "...", "from": [{"posting": "..."}]}     no answer yet
      ],
      "gaps": [
        {"gap": "what the posting asks for that the user lacks",
         "from": [{"posting": "where it asks"}],
         "address": "an honest way to answer it", "sources": [{"master": "..."}]}
      ],
      "ask": [
        {"question": "...", "from": [{"posting": "..."}, {"story": "..."}]}
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The letter's sources and checks, so a prep sheet and a letter cannot drift apart.
from build_letter import STORY, Sources, check_passage, today  # noqa: E402
from build_resume import (APPS, MASTER, ROOT, master_format, parse_master,  # noqa: E402
                          safe_name)

SUFFIX = " - interview prep.md"
SECTIONS = ("questions", "gaps", "ask")
ANSWER_PARTS = ("situation", "action", "result")
FIELDS = {
    "questions": {"question", "from", "answer", *ANSWER_PARTS, "sources"},
    "gaps": {"gap", "from", "address", "sources"},
    "ask": {"question", "from"},
}
# What may back an answer: the user's own files, or their words in chat.
ABOUT_THE_USER = ("master", "story", "user")
# A rehearsed answer is spoken. Past this it is a speech, which is a note, not
# an error: the writer decides.
ANSWER_WORDS = 200

LABEL = {"posting": "the posting", "master": "master.md", "story": "story.md",
         "user": "what you said"}
TAG = {"posting": "the posting", "master": "master.md", "story": "story.md",
       "user": "you said"}
QUOTED = ("posting", "user")

INTRO = ("Every answer here is drawn from your master.md and story.md, the posting filed "
         "beside this sheet, or what you said while it was written, and lists the passages "
         "behind it. Where an answer and its sources disagree, the sources are right.")
UNANSWERED = ("*No answer yet.* Your files do not answer this one, so the sheet leaves it "
              "to you. Prepare it before the interview, in your own words.")
BUILT = ("<!-- Built by scripts/build_prep.py, which checked every source on this sheet. "
         "Edit it as you like; building it again replaces it. -->")


def words(v) -> str:
    """A field's text on one line, or "" for anything that is not text."""
    return " ".join(v.split()) if isinstance(v, str) else ""


def _item(obj, section: str, where: str, errors: list[str]) -> bool:
    if not isinstance(obj, dict):
        errors.append(f"{where} must be an object, as the prep file format shows")
        return False
    unknown = sorted(set(obj) - FIELDS[section])
    if unknown:
        errors.append(f"{where} has keys the sheet does not use: {', '.join(unknown)}")
    return True


def _drawn_from(where: str, text: str, cited, sources: Sources, errors: list[str],
                warnings: list[str], posting: bool = False) -> list:
    """The `from` list: what makes a question likely, or where the posting asks
    for what a gap lacks. Required, and checked like any other sources."""
    if not cited:
        errors.append(f"{where} does not say what it was drawn from: list the posting "
                      "phrase or the passage behind it, under from")
    resolved = check_passage(where, text, cited, sources, errors, warnings, stock=False)
    if cited and posting and not any(kind == "posting" for kind, _, _ in resolved):
        errors.append(f"{where}: quote the posting where it asks for this, as a posting "
                      "source under from")
    return resolved


def check(prep, sources: Sources) -> tuple[dict, list[str], list[str]]:
    """Resolve every source and run the checks. Returns (the sheet's items with
    their sources resolved, errors, warnings). Errors stop the build; warnings
    are notes for the writer."""
    errors: list[str] = []
    warnings: list[str] = []
    report: dict = {s: [] for s in SECTIONS}
    if not isinstance(prep, dict):
        return report, ["the prep file must be a JSON object, as the format shows"], []
    unknown = sorted(set(prep) - set(SECTIONS) - {"date"})
    if unknown:
        errors.append(f"the prep file has keys the sheet does not use: {', '.join(unknown)}")
    items = {}
    for section in SECTIONS:
        value = prep.get(section) or []
        if not isinstance(value, list):
            errors.append(f"{section} must be a list")
            value = []
        items[section] = value
    if not items["questions"]:
        errors.append("the sheet has no questions")

    for i, q in enumerate(items["questions"], 1):
        where = f"question {i}"
        if not _item(q, "questions", where, errors):
            continue
        text = words(q.get("question"))
        if not text:
            errors.append(f"{where} has no question")
        drawn = _drawn_from(where, text, q.get("from"), sources, errors, warnings)
        parts = {k: words(q.get(k)) for k in ("answer", *ANSWER_PARTS)}
        told = [k for k in ANSWER_PARTS if parts[k]]
        if parts["answer"] and told:
            errors.append(f"{where}: give one answer, or a situation, action and result, "
                          "not both")
        elif told and len(told) < len(ANSWER_PARTS):
            missing = [k for k in ANSWER_PARTS if not parts[k]]
            errors.append(f"{where}: an answer told as situation, action and result needs "
                          f"all three; it has no {' or '.join(missing)}")
        resolved: list = []
        if parts["answer"] or told:
            body = " ".join(parts[k] for k in ("answer", *ANSWER_PARTS) if parts[k])
            resolved = check_passage(f"{where}'s answer", body, q.get("sources"), sources,
                                     errors, warnings)
            if not any(kind in ABOUT_THE_USER for kind, _, _ in resolved):
                errors.append(f"{where}'s answer cites nothing the user did: back it with a "
                              "master.md bullet, a story.md passage, or what the user said")
            n = len(body.split())
            if n > ANSWER_WORDS:
                warnings.append(f"{where}'s answer runs {n} words; a spoken answer is "
                                "shorter")
        elif q.get("sources"):
            errors.append(f"{where} lists sources but has no answer")
        else:
            warnings.append(f"{where} has no answer yet, so the sheet shows it as one to "
                            "prepare")
        report["questions"].append({"question": text, "from": drawn, **parts,
                                    "sources": resolved})

    for i, g in enumerate(items["gaps"], 1):
        where = f"gap {i}"
        if not _item(g, "gaps", where, errors):
            continue
        name = words(g.get("gap"))
        if not name:
            errors.append(f"{where} does not name what is missing")
        drawn = _drawn_from(where, name, g.get("from"), sources, errors, warnings,
                            posting=True)
        address = words(g.get("address"))
        if not address:
            errors.append(f"{where} has no way to address it")
        resolved = check_passage(f"{where}'s answer", address, g.get("sources"), sources,
                                 errors, warnings)
        report["gaps"].append({"gap": name, "from": drawn, "address": address,
                               "sources": resolved})

    for i, a in enumerate(items["ask"], 1):
        where = f"question to ask {i}"
        if not _item(a, "ask", where, errors):
            continue
        text = words(a.get("question"))
        if not text:
            errors.append(f"{where} has no question")
        drawn = _drawn_from(where, text, a.get("from"), sources, errors, warnings)
        report["ask"].append({"question": text, "from": drawn})

    if not items["gaps"]:
        warnings.append("no gaps listed: the report should say the posting asks for "
                        "nothing the files lack")
    if not items["ask"]:
        warnings.append("no questions to ask them")
    return report, errors, warnings


# ----------------------------------------------------------------- the sheet

def plain(s: str, mode: str) -> str:
    """A master.md passage as it reads. A LaTeX-source master.md stores
    "M\\&V" and "CO$_2$"; plain text is left alone, "$1.2M" included."""
    if mode != "latex":
        return s
    s = s.replace("\\$", "\x00")
    s = re.sub(r"\$([^$]*)\$", lambda m: re.sub(r"\\sim\s*", "~", m.group(1))
               .translate(str.maketrans("", "", "_^{}\\")), s)
    s = re.sub(r"\\(?:textbf|textit|emph|underline|textsc)\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\([&%#_{}])", r"\1", s)
    return s.replace("\x00", "$").replace("~", " ")


def _quote(s: str) -> str:
    return f"\u201c{s}\u201d"


def drawn_line(drawn: list) -> str:
    """'*From the posting:* "a"; "b" · *From story.md:* "c"', the phrases cited."""
    groups: dict[str, list[str]] = {}
    for kind, fragment, _ in drawn:
        groups.setdefault(kind, []).append(" ".join(fragment.split()))
    return " · ".join(f"*From {LABEL[k]}:* " + "; ".join(_quote(f) for f in v)
                      for k, v in groups.items())


def source_block(resolved: list, mode: str) -> list[str]:
    """Each passage behind an answer, in full, once, as a list in a quote: a
    list, because consecutive quoted lines run together in most viewers."""
    lines, seen = [], set()
    for kind, fragment, found in resolved:
        text = " ".join((found or fragment).split())
        if (kind, text) in seen:
            continue
        seen.add((kind, text))
        shown = _quote(text) if kind in QUOTED else plain(text, mode)
        lines.append(f"> - **{TAG[kind]}:** {shown}")
    return lines + [""] if lines else []


def render(prep: dict, report: dict, company: str, title: str, mode: str = "text") -> str:
    """The sheet as Markdown, from check()'s report."""
    out = [BUILT, "", f"# Interview prep: {title}", "",
           f"{company} · prepared {prep.get('date') or today()}", "", INTRO, "",
           "## Questions to expect", ""]
    for i, q in enumerate(report["questions"], 1):
        out += [f"### {i}. {q['question']}", "", drawn_line(q["from"]), ""]
        if q["answer"]:
            out += [q["answer"], ""]
        elif q["situation"]:
            out += [f"**Situation.** {q['situation']}", "", f"**Action.** {q['action']}", "",
                    f"**Result.** {q['result']}", ""]
        else:
            out += [UNANSWERED, ""]
        out += source_block(q["sources"], mode)
    if report["gaps"]:
        out += ["## Gaps to be ready for", ""]
        for i, g in enumerate(report["gaps"], 1):
            out += [f"### {i}. {g['gap']}", "", drawn_line(g["from"]), "",
                    f"**How to answer it.** {g['address']}", ""]
            out += source_block(g["sources"], mode)
    if report["ask"]:
        out += ["## Questions to ask them", ""]
        for i, a in enumerate(report["ask"], 1):
            out += [f"### {i}. {a['question']}", "", drawn_line(a["from"]), ""]
    return "\n".join(out).rstrip("\n") + "\n"


def sheet_path(company: str, title: str) -> str:
    return os.path.join(APPS, safe_name(company), safe_name(title) + SUFFIX)


# ---------------------------------------------------------------------- main

def _show(label: str, fragment: str, found: str | None) -> str:
    shown = " ".join((found if found else f"NOT FOUND: {fragment}").split())
    return f"      {label:12}: {shown[:100]}{'...' if len(shown) > 100 else ''}"


def main() -> int:
    # Piped, stdout is block-buffered and stderr is not, so NOT FILED would
    # land above the report it ends.
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prep", required=True, metavar="JSON", help="the prep file")
    ap.add_argument("--company", help="file under Applications/<company>/")
    ap.add_argument("--title", help="the job title the sheet is named after")
    ap.add_argument("--posting", help="the posting text, for checking posting quotes "
                                      "(default: <Title> - posting.txt beside the sheet)")
    ap.add_argument("--check", action="store_true",
                    help="resolve sources and run the checks only; file nothing")
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--story", default=STORY)
    args = ap.parse_args()
    if bool(args.company) != bool(args.title):
        print("--company and --title go together", file=sys.stderr)
        return 2
    if not args.check and not args.company:
        print("--company and --title say where to file the sheet; without them, "
              "only --check runs", file=sys.stderr)
        return 2

    try:
        with open(args.prep, encoding="utf-8") as fh:
            prep = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"cannot read the prep file {args.prep}: {exc}", file=sys.stderr)
        return 2
    posting = args.posting
    if not posting and args.company:
        guess = os.path.join(APPS, safe_name(args.company),
                             f"{safe_name(args.title)} - posting.txt")
        posting = guess if os.path.exists(guess) else None

    sources = Sources(args.master, args.story, posting)
    report, errors, warnings = check(prep, sources)
    mode, _ = master_format(args.master, parse_master(args.master)[0])

    rel = lambda p: os.path.relpath(p, ROOT)  # noqa: E731
    print(f"prep      : {args.prep}")
    print(f"master    : {rel(args.master)} (as {mode})")
    print(f"story     : {rel(args.story)}" + ("" if sources.story is not None else "  (missing)"))
    print(f"posting   : {rel(posting) + ' (quotes checked)' if sources.posting is not None else 'none -- posting quotes cannot be checked'}")
    answered = sum(1 for q in report["questions"] if q["answer"] or q["situation"])
    print(f"sheet     : {len(report['questions'])} questions ({answered} answered), "
          f"{len(report['gaps'])} gaps, {len(report['ask'])} questions to ask")

    for section, label, key in (("questions", "questions to expect", "question"),
                                ("gaps", "gaps", "gap"), ("ask", "questions to ask", "question")):
        if not report[section]:
            continue
        print(f"\n{label}, and the sources behind them:")
        for i, item in enumerate(report[section], 1):
            print(f"  [{i}] {item[key][:110]}{'...' if len(item[key]) > 110 else ''}")
            for kind, fragment, found in item["from"]:
                print(_show(f"from {kind}", fragment, found))
            for kind, fragment, found in item.get("sources", []):
                print(_show(kind, fragment, found))
            if section == "questions" and not (item["answer"] or item["situation"]):
                print("      (no answer yet -- the sheet shows it as one to prepare)")

    for w in warnings:
        print(f"\nnote: {w}")
    if errors:
        print("\nNOT FILED -- fix these first:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    if args.check:
        print("\nchecks passed (--check: nothing filed)")
        return 0

    path = sheet_path(args.company, args.title)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(prep, report, args.company, args.title, mode))
    print(f"\nfiled     : {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Keyword-coverage check against a job description.

Every other design decision in this project optimizes a resume for a 30-second
human scan. At large employers a parser filters first, and that is a different
test: it wants the posting's own vocabulary present in the document.

This does NOT rewrite anything. It reports which of a posting's keywords are
missing, and -- the part that matters for our architecture -- whether each
missing term already exists somewhere in content/master.md. That splits the
result into two very different problems:

    SELECTABLE   the evidence exists, the tailoring step just didn't pick it.
                 Fix by adding that bullet to the manifest.
    GAP          the user genuinely lacks it. Not something to write around; it
                 belongs in the digest's "gaps" line.

Usage:
    python scripts/ats_check.py --jd "<posting.txt>" --resume "Applications/<Company>/<Job Title>.tex"
    cat posting.txt | python scripts/ats_check.py --jd - --resume <file>

Check the .tex filed with the application: Resume/LaTeX/editing_<variant>.tex holds only
the last build, which in a batch is some other role's resume.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(ROOT, "content/master.md")

# Words that carry no signal for a parser. Deliberately aggressive: a false
# "missing keyword" wastes attention, a missed generic word costs nothing.
STOP = set("""
a an the and or but if then than that this these those there here of in on at to for with
from by as is are was were be been being do does did doing have has had having will would
can could should may might must shall we you they it he she our your their its his her
not no yes all any both each few more most other some such only own same so too very just
about above after again against below between during into through under until while over
who whom which what when where why how i me my mine us them him
job role position candidate applicant company team work working works worked experience
years year opportunity apply application applications hiring hire join looking seeking
ability able strong excellent good great best help helping support ensure ensuring
including include includes provide providing across within using use used new
plus preferred required requirements responsibilities qualifications benefits
equal employer opportunity diversity inclusive veteran disability status
please note may also etc via per one two three four five
responsible responsibility accountable following assigned various complex related
guidance direction directed oversee overseeing perform performs performed performing
deliverables deliverable tasks task duties duty activities activity effort efforts
knowledge understanding familiarity proficiency proficient skilled expertise expert
technology technologies solution solutions service services product products
develop develops developed developing development build builds built
manage manages managed managing lead leads led leading
prepare prepares prepared preparing review reviews reviewed reviewing
assist assists assisted assisting coordinate coordinates coordinated coordinating
communicate communication communicates written verbal interpersonal
detail details detailed oriented motivated self driven passionate collaborative
environment environments culture mission vision values impact meaningful
successful success effective effectively efficiently timely accurate accurately
level levels senior junior mid entry associate staff principal
degree bachelor bachelors master masters phd education educational university
salary compensation range base bonus equity benefits insurance medical dental
401k pto vacation holiday leave remote hybrid onsite office location
minimum maximum typical typically ideal ideally must should preferred
members member people employee employees staff colleagues peers professionals
together world global worldwide national international leading largest premier
moderately highly fully partially generally primarily mainly largely
owned ownership founded established growing growth future forward together
clients customer customers partner partners stakeholder stakeholders
recognized awarded ranked named voted proud pride commitment committed
u.s usa business drive active
""".split())

# The legal and HR sentences every posting ends with, and the application form a
# saved board page carries after "Apply for this job". Their words -- "military",
# "employment", "attach", "select" -- are nobody's keyword, and on Redwood's
# 2026-11-02 posting they made up a third of the GAP list.
BOILERPLATE = re.compile(
    r"equal (employment )?opportunit|without regard to|veteran|military|"
    r"reasonable accommodation|personal information|privacy (notice|policy|rights)|"
    r"pay (transparency|range)|salary range|compensation (range|will be|may vary)|"
    r"e-verify|background check|at[- ]will|drug[- ]free|disabilit|sexual orientation|"
    r"gender identity|national origin|criminal histor|we collect|"
    r"apply for this job|\battach\b|enter manually|select\.\.\.|accepted file types|"
    r"\b(first|last|preferred) name\b", re.I)


def strip_boilerplate(jd: str) -> str:
    """The posting without its legal and HR sentences or application form."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", jd)
    return " ".join(s for s in sentences if not BOILERPLATE.search(s))

# Terms that look like keywords but are just the employer's own name. Populated
# per run from --company and the posting title, because "Black Veatch" scoring
# as a missing keyword is noise, not a finding.
COMPANY_TOKENS: set[str] = set()

# Multi-word terms worth catching as a unit; a bigram scan alone splits these.
PHRASES = [
    "project management", "program management", "capital projects", "energy storage",
    "battery energy storage", "solar pv", "demand response", "load forecasting",
    "energy efficiency", "measurement and verification", "commissioning",
    "root cause analysis", "continuous improvement", "cross functional",
    "stakeholder management", "process improvement", "data analysis",
    "asset framework", "point to point", "site acceptance test", "factory acceptance test",
    "control systems", "process safety", "capital expenditure", "cost estimating",
    "scheduling", "procurement", "vendor management", "contract negotiation",
    "technical documentation", "client facing", "customer facing", "renewable energy",
    "distributed energy", "grid interconnection", "power systems", "electrical distribution",
    "mechanical design", "design for manufacturing", "supply chain", "quality assurance",
    "regulatory compliance", "permitting", "due diligence", "financial modeling",
    "machine learning", "data pipeline", "solution architecture", "customer success",
    "technical account", "implementation", "onboarding", "integration",
]


def read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return open(path, encoding="utf-8", errors="ignore").read()


def resume_text(path: str) -> str:
    """Plain text of a built resume, from PDF or .tex."""
    if path.lower().endswith(".pdf"):
        try:
            out = subprocess.run(["pdftotext", "-layout", path, "-"],
                                 capture_output=True, timeout=30)
            return out.stdout.decode("utf-8", "ignore")
        except Exception:
            return ""
    raw = open(path, encoding="utf-8", errors="ignore").read()
    raw = re.sub(r"^\s*%.*$", " ", raw, flags=re.M)          # comments
    raw = re.sub(r"\\(begin|end)\{[^}]*\}", " ", raw)
    raw = re.sub(r"\\[a-zA-Z]+\s*(\[[^\]]*\])?", " ", raw)   # commands
    raw = re.sub(r"[{}$\\&~^_]", " ", raw)
    return re.sub(r"\s+", " ", raw)


def normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"&", " and ", s)
    s = re.sub(r"[^a-z0-9+#/. ]", " ", s)
    # Keep dots inside tokens (node.js, u.s.) but drop trailing ones, which
    # otherwise produce keywords like "projects." -- a whole run of them, or
    # "select..." survives as "select..".
    s = re.sub(r"\.+(?=\s|$)", " ", s)
    return re.sub(r"\s+", " ", s)


def stem(w: str) -> str:
    """Crude suffix folding so 'engineering' matches 'engineer'."""
    for suf in ("ingly", "ing", "ers", "er", "ies", "ied", "es", "ed", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def keyword_candidates(jd: str) -> Counter:
    """Terms the posting actually leans on, weighted by how hard it leans."""
    text = normalize(jd)
    counts: Counter = Counter()

    for p in PHRASES:
        n = text.count(p)
        if n:
            counts[p] += n * 3          # multi-word matches are high-signal

    words = [w for w in text.split()
             if w not in STOP and w not in COMPANY_TOKENS
             and len(w) > 2 and not w.isdigit()]
    for w in words:
        counts[w] += 1

    # Bigrams that recur are usually real terms of art.
    for a, b in zip(words, words[1:]):
        bg = f"{a} {b}"
        if bg not in counts:
            counts[bg] += 0
        counts[bg] += 1
    for bg in [k for k, v in counts.items() if " " in k and v < 2
               and bg_not_phrase(k)]:
        del counts[bg]
    return counts


def bg_not_phrase(k: str) -> bool:
    return k not in PHRASES


def present(term: str, hay_stems: set[str], hay_text: str) -> bool:
    if " " in term:
        return term in hay_text
    return stem(term) in hay_stems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", required=True, help="job description file, or - for stdin")
    ap.add_argument("--resume", help="built .tex or .pdf")
    ap.add_argument("--master", default=MASTER)
    ap.add_argument("--company", default="", help="employer name, so its own name isn't scored")
    ap.add_argument("--top", type=int, default=30, help="keywords to consider")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.company:
        COMPANY_TOKENS.update(w for w in normalize(args.company).split() if len(w) > 2)

    jd = strip_boilerplate(read_text(args.jd))
    if not jd.strip():
        print("empty job description", file=sys.stderr)
        return 2

    res_raw = resume_text(args.resume) if args.resume else ""
    mas_raw = open(args.master, encoding="utf-8", errors="ignore").read()

    res_text = normalize(res_raw)
    mas_text = normalize(mas_raw)
    res_stems = {stem(w) for w in res_text.split()}
    mas_stems = {stem(w) for w in mas_text.split()}

    cands = keyword_candidates(jd)
    cands = Counter({k: v for k, v in cands.items()
                     if not any(tok in k.split() for tok in COMPANY_TOKENS)})
    # Drop single words that are subsumed by a matched phrase.
    ranked = [(t, c) for t, c in cands.most_common() if c >= 2][: args.top]

    matched, selectable, gaps = [], [], []
    for term, freq in ranked:
        if present(term, res_stems, res_text):
            matched.append((term, freq))
        elif present(term, mas_stems, mas_text):
            selectable.append((term, freq))
        else:
            gaps.append((term, freq))

    total = len(ranked)
    score = round(100 * len(matched) / total) if total else 0
    reachable = round(100 * (len(matched) + len(selectable)) / total) if total else 0

    if args.json:
        print(json.dumps({
            "score": score, "reachable": reachable, "total_keywords": total,
            "matched": [t for t, _ in matched],
            "selectable": [t for t, _ in selectable],
            "gaps": [t for t, _ in gaps],
        }, indent=1))
        return 0

    print(f"ATS keyword coverage: {score}%  ({len(matched)}/{total} top keywords)")
    print(f"reachable from master.md: {reachable}%")
    print()
    print("Read the SELECTABLE/GAP split below, not the raw percentage. The 80%")
    print("figure quoted by ATS guides assumes a keyword-dense multi-page resume;")
    print("a one-page document scored against a 6,000-character posting will sit")
    print("far lower and still pass. What matters:")
    print("  * a large SELECTABLE list  -> tailoring missed evidence you have")
    print("  * a large GAP list         -> the role is a genuine stretch")
    print("Compare scores BETWEEN postings rather than against an absolute bar.\n")

    if selectable:
        print("SELECTABLE -- evidence exists in master.md but wasn't chosen.")
        print("Add those bullets to the manifest; do not write new claims.")
        for t, f in selectable:
            print(f"   {f:>3}x  {t}")
        print()
    if gaps:
        print("GAP -- the word appears nowhere in master.md. Two different cases,")
        print("and only a human can tell them apart:")
        print("  (a) The user did the work but never used this word for it --")
        print("      an internal tool that connected two systems IS integration")
        print("      work even when 'integration' isn't in master.md. Rephrasing")
        print("      real work in the posting's vocabulary is legitimate.")
        print("  (b) The user genuinely lacks it -> report on the digest's 'gaps' line.")
        print("Never invent experience to close one of these.")
        for t, f in gaps:
            print(f"   {f:>3}x  {t}")
        print()
    if matched:
        print(f"matched ({len(matched)}): " + ", ".join(t for t, _ in matched))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

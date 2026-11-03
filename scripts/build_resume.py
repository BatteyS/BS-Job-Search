"""Render a tailored resume from content/master.md and fit it to the page limit.

Content lives in exactly one place (content/master.md); the .tex template is
layout with no facts in it. This script does NOT decide what goes on the
page. It takes a manifest naming the roles and bullets to include, in order,
resolves every entry against master.md, renders it, and -- the part worth
automating -- checks the real page count and trims until it fits.

master.md can be plain text (escaped here) or LaTeX source, detected from the
file or set with `format:` in its front matter, which can also set
`max_pages` and `section_order`. Any `# Section` renders: `## Entry | ... |`
blocks the way Projects does, bare bullets the way Skills does.

Selection moved out deliberately. Cluster tags were a coarse proxy for "relevant
to this posting": they surfaced a carbon-finance internship on a battery
hardware resume and reduced five of eight roles to generic one-line summaries,
because a tag can only say which *angle* a bullet suits, never which posting.
master.md is 49 bullets. Whoever writes the manifest can read all of it against
the actual job description, which is strictly better information.

What stays mechanical is everything that must not drift: nothing reaches the
page unless it resolves to a real master.md bullet, trimming squeezes whitespace
before losing content, no role is dropped if that opens a gap in the employment
dates, and every cut is reported.

    python scripts/build_resume.py --manifest plan.json \
        --company "Peak Energy" --title "Process Engineer, ESS"
    python scripts/build_resume.py --all --out cv --max-pages 2

--company/--title also files the built PDF and the .tex it was built from to
Applications/<Company>/<Title>.{pdf,tex}. Build artifacts stay in Resume/build.
--master and --contact point at other files, which is how an example profile
or a test builds without touching yours.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(ROOT, "content/master.md")
CONTACT = os.path.join(ROOT, "content/contact.local.md")
CONTACT_EXAMPLE = os.path.join(ROOT, "content/contact.example.md")
LATEX = os.path.join(ROOT, "Resume/LaTeX")
TEMPLATE = os.path.join(LATEX, "template.tex")
BUILD = os.path.join(ROOT, "Resume/build")
PDFDIR = os.path.join(ROOT, "Resume/pdf")
APPS = os.path.join(ROOT, "Applications")

# "S" bullets are condensed one-liners, for a role that has to appear to keep the
# employment dates continuous but has little to say to this posting. Detail
# bullets (P1-P3) are for roles that lead. Priority records the user's own view
# of which bullets are strongest; it does not select anything on its own.

# The sections the builder treats specially. Every other `# Section` in
# master.md is optional: a manifest names what it wants from it.
DEFAULT_ORDER = ["Education", "Experience", "Projects", "Skills"]

# Headings that mean the work-history section -- the one the date-gap check and
# the split layout apply to. The heading the user wrote is what renders.
EXPERIENCE_HEADINGS = {"experience", "work experience", "professional experience",
                       "employment", "employment history", "work history"}

# Progressive tightening. Each tier is tried before any bullet is dropped --
# losing a line of whitespace is always better than losing a line of evidence.
DENSITY_TIERS = [
    {"VMARGIN": "0.5in", "HMARGIN": "0.5in", "ITEMSEP": "0pt", "SECSPACE": "8pt"},
    {"VMARGIN": "0.45in", "HMARGIN": "0.45in", "ITEMSEP": "0pt", "SECSPACE": "6pt"},
    {"VMARGIN": "0.4in", "HMARGIN": "0.4in", "ITEMSEP": "0pt", "SECSPACE": "5pt"},
    {"VMARGIN": "0.35in", "HMARGIN": "0.4in", "ITEMSEP": "0pt", "SECSPACE": "4pt"},
]


@dataclass
class Bullet:
    priority: str
    text: str
    # The master.md sentence this came from. A rewrite changes `text` but not
    # `source`, which is what makes duplicate detection work across rewordings.
    source: str = ""


@dataclass
class Entry:
    section: str
    title_parts: list[str]
    bullets: list[Bullet] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def employer(self) -> str:
        return self.title_parts[0] if self.title_parts else ""

    @property
    def role(self) -> str:
        return self.title_parts[1] if len(self.title_parts) > 1 else ""

    @property
    def dates(self) -> str:
        return self.title_parts[2] if len(self.title_parts) > 2 else ""


# ------------------------------------------------------------------- parsing

BULLET_RE = re.compile(r"^-\s*\[\s*(P[123]|S)\s*\]\s*(.+)$", re.S)


def parse_master(path: str) -> tuple[dict, list[Entry]]:
    raw = open(path, encoding="utf-8").read()

    front: dict = {}
    m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                front[k.strip()] = v.strip()
        raw = raw[m.end():]

    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)   # strip HTML comments

    entries: list[Entry] = []
    section = ""
    cur: Entry | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        if cur is not None and buf:
            joined = " ".join(x.strip() for x in buf)
            joined = re.sub(r"\s+", " ", joined).strip()
            bm = BULLET_RE.match(joined)
            if bm:
                text = bm.group(2).strip()
                cur.bullets.append(Bullet(bm.group(1), text, text))
        buf = []

    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("# "):
            flush()
            section = s[2:].strip()
            cur = None
        elif s.startswith("## "):
            flush()
            parts = [p.strip() for p in s[3:].split("|")]
            cur = Entry(section=section, title_parts=parts)
            entries.append(cur)
        elif s.startswith("- ["):
            flush()
            # Skills bullets hang directly off a `#` heading with no `##` role,
            # so synthesize a container for them rather than dropping them.
            if cur is None:
                cur = Entry(section=section, title_parts=[section],
                            meta={"list": True})
                entries.append(cur)
            buf = [s]
        elif s and buf:
            buf.append(s)
        elif not s:
            flush()
        elif s and cur is not None and ":" in s and not s.startswith("-"):
            k, v = s.split(":", 1)
            cur.meta[k.strip()] = v.strip()
    flush()

    # A "Skills" section has bullets but no ## heading; attach them to a synthetic entry.
    return front, entries


MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
# A season stands for its middle month; "Summer 2023" is an internship, not a date.
SEASONS = {"winter": 1, "spring": 4, "summer": 7, "fall": 10, "autumn": 10}
ONGOING = ("present", "current", "now", "ongoing", "today")

DATE_FORMATS = ('"May 2022 – May 2024", "Sept. 2019 - Dec 2021", "Summer 2023 – 2024", '
                '"05/2022 – Present", "2019 to 2021"')


def _month_index(s: str) -> int | None:
    """One end of a span -> year*12 + month, or None."""
    s = s.strip().lower().rstrip(".")
    if s.startswith(ONGOING):
        n = datetime.now()
        return n.year * 12 + n.month
    m = re.fullmatch(r"([a-z]+)\.?,?\s+(\d{4})", s)
    if m:
        word = m.group(1)
        month = MONTHS.get(word) or SEASONS.get(word)
        return int(m.group(2)) * 12 + month if month else None
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(2)) * 12 + int(m.group(1))
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(1)) * 12 + int(m.group(2))
    m = re.fullmatch(r"(\d{4})", s)
    return int(m.group(1)) * 12 + 6 if m else None


def parse_span(dates: str) -> tuple[int, int] | None:
    """'May 2022 - May 2024' -> (2022*12+5, 2024*12+5). 'Present' -> now.

    Ends are split on an en or em dash, " to ", or a hyphen with spaces round
    it; an unspaced hyphen splits only after a four-digit year ("2019-2021",
    "May 2022-May 2024"), so a numeric "2022-05" end survives. None means the
    span could not be read -- check_dates() turns that into an error rather
    than let the gap check quietly skip the role.
    """
    if not dates:
        return None
    s = dates.strip()
    parts = re.split(r"\s*[–—]\s*|\s+to\s+|\s+-\s+", s)
    if len(parts) != 2:
        m = re.fullmatch(r"(.*\d{4})-(\S.*)", s)
        parts = [m.group(1), m.group(2)] if m else parts
    if len(parts) != 2:
        return None
    a, b = _month_index(parts[0]), _month_index(parts[1])
    return (a, b) if a is not None and b is not None else None


def check_dates(entries: list["Entry"]) -> None:
    """Stop the build when a work-history role has no readable date span.

    The date-gap check is the only thing keeping the builder from cutting a
    role whose absence leaves a hole in the timeline, and it used to skip any
    role it could not read -- so "Jan 2023 - Present" would have let the
    current job be cut. Better to refuse the build and say which line to fix.
    """
    bad = [e for e in entries if e.section == "Experience" and parse_span(e.dates) is None]
    if bad:
        roles = "\n".join(f"  {e.employer} | {e.role} | {e.dates or '(no dates)'}" for e in bad)
        raise SystemExit(f"master.md: these work-history roles have dates the builder "
                         f"cannot read:\n{roles}\nWrite them like {DATE_FORMATS}.")


def creates_gap(kept: list[Entry], max_gap_months: int = 3) -> bool:
    """Would this set of roles leave an unexplained hole in the timeline?

    Only gaps *after the earliest kept role* matter -- nobody expects coverage
    before the first job shown. This is what makes an internship that sits
    entirely inside a longer role droppable: removing it changes the covered
    timeline not at all.
    """
    spans = [s for s in (parse_span(e.dates) for e in kept
                         if e.section == "Experience") if s]
    if not spans:
        return True
    spans.sort()
    reach = spans[0][1]
    for start, end in spans[1:]:
        if start - reach > max_gap_months:
            return True
        reach = max(reach, end)
    # A hole at the END is the most conspicuous kind -- it reads as "not
    # currently employed". Checking only the gaps between roles once let the
    # builder cut the current position and call the result gapless.
    now = datetime.now().year * 12 + datetime.now().month
    return (now - reach) > max_gap_months


def normalize_sections(entries: list[Entry]) -> dict[str, str]:
    """Give the work-history section its canonical name, "Experience".

    Returns canonical name -> the heading master.md actually used, which is
    what renders: a file that says "# Professional Experience" gets that
    heading, and the gap check and split layout still find the section.
    """
    display: dict[str, str] = {}
    for e in entries:
        if e.section.lower() in EXPERIENCE_HEADINGS:
            display.setdefault("Experience", e.section)
            e.section = "Experience"
        else:
            display.setdefault(e.section, e.section)
    return display


def section_kinds(entries: list[Entry]) -> dict[str, str]:
    """Section -> "list" (bare bullets, like Skills) or "entries" (`##` blocks)."""
    kinds: dict[str, str] = {}
    for e in entries:
        k = "list" if e.meta.get("list") else "entries"
        if kinds.get(e.section) != "entries":
            kinds[e.section] = k
    return kinds


def section_order(front: dict, man: dict | None, present: list[str]) -> list[str]:
    """The order sections print in.

    The manifest's `order` wins, then `section_order` in master.md's front
    matter, then Education, Experience, Projects, Skills. Sections not named
    follow -- the four in that order, then the rest in master.md order.
    """
    raw = (man or {}).get("order") or front.get("section_order") or []
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.split(",") if p.strip()]
    canon = {s.lower(): s for s in present}
    named = []
    for n in raw:
        key = "experience" if n.lower() in EXPERIENCE_HEADINGS else n.lower()
        if key not in canon:
            raise SystemExit(f"section order names {n!r}, but master.md has no such "
                             f"section; it has: {', '.join(present)}")
        named.append(canon[key])
    rest = ([s for s in DEFAULT_ORDER if s in present and s not in named]
            + [s for s in present if s not in DEFAULT_ORDER and s not in named])
    return named + rest


# ---------------------------------------------------------- text vs LaTeX

# What plain text means by the characters LaTeX treats as commands.
_TEXT_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
# Characters pdflatex's utf8 input cannot typeset by itself. Anything else it
# cannot set stops the build with "Unicode character ... not set up", which
# names the character to replace.
_UNICODE = {
    **{chr(0x2080 + i): rf"\textsubscript{{{i}}}" for i in range(10)},
    **{c: rf"\textsuperscript{{{d}}}" for c, d in zip("⁰⁴⁵⁶⁷⁸⁹", "0456789")},
    "≥": r"$\geq$", "≤": r"$\leq$", "≈": r"$\approx$", "≠": r"$\neq$",
    "→": r"$\rightarrow$", "←": r"$\leftarrow$",
}

# A master.md that escapes LaTeX's specials (\$ \% \&) or writes math
# subscripts ($_2$) is LaTeX source, written that way by hand.
LATEX_SOURCE = re.compile(r"\\[$%&#_]|\$[_^]")


def esc(s: str) -> str:
    """LaTeX-source master.md already carries its escapes; only fix markdown bold."""
    return re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)


def text_to_latex(s: str) -> str:
    """Plain text -> LaTeX: escape the specials, then **bold**."""
    out = "".join(_TEXT_ESCAPES.get(c) or _UNICODE.get(c) or c for c in s)
    return esc(out)


def master_format(path: str, front: dict) -> tuple[str, str]:
    """("latex" | "text", why). `format:` in the front matter wins.

    Plain text is the default, because "R&D" and "40%" are how people write;
    left unescaped, the first breaks the build and the second silently cuts
    the rest of its bullet off the page. A file written as LaTeX source is
    recognized by its escapes, so it keeps working without a flag.
    """
    stated = str(front.get("format", "")).strip().lower()
    if stated in ("latex", "text"):
        return stated, "set in its front matter"
    if stated:
        raise SystemExit(f"{path}: format must be text or latex, not {stated!r}")
    raw = re.sub(r"<!--.*?-->", "", open(path, encoding="utf-8").read(), flags=re.S)
    if LATEX_SOURCE.search(raw):
        return "latex", "it contains LaTeX escapes such as \\$ or \\%"
    return "text", "it contains no LaTeX escapes"


class Fmt:
    """How master.md text becomes LaTeX: `prose` for bullets and skills lines,
    `label` for names, titles, dates, places, and headings."""

    def __init__(self, mode: str):
        self.mode = mode

    def prose(self, s: str) -> str:
        return esc(s) if self.mode == "latex" else text_to_latex(s)

    def label(self, s: str) -> str:
        return s if self.mode == "latex" else text_to_latex(s)


# ------------------------------------------------------------------ rendering


def render_entry(e: Entry, fmt: Fmt) -> str:
    lines = []
    if e.section == "Skills":
        return ""
    if e.section == "Education":
        loc = fmt.label(e.meta.get("location", ""))
        lines.append(f"\\textbf{{{fmt.label(e.employer)}}} \\hfill {loc} \\\\")
        lines.append(f"{fmt.label(e.role)} \\hfill {fmt.label(e.dates)}")
        # Honors, GPA, coursework: optional, and shown whole.
        if e.bullets:
            lines.append("\\begin{itemize}")
            lines += [f"  \\item {fmt.prose(b.text)}" for b in e.bullets]
            lines.append("\\end{itemize}")
        lines.append("\\vspace{0pt}")
        return "\n".join(lines)

    head = f"\\textbf{{{fmt.label(e.employer)}}}"
    if e.role:
        head += f" -- {{{fmt.label(e.role)}}}"
    if e.dates:
        head += f"\n\\hfill \\textit{{{fmt.label(e.dates)}}}"
    lines.append(head)
    lines.append("\\begin{itemize}")
    for b in e.bullets:
        lines.append(f"  \\item {fmt.prose(b.text)}")
    lines.append("\\end{itemize}")
    lines.append("\\vspace{2pt}")
    return "\n".join(lines)


def section(name: str) -> str:
    """A LaTeX section command, with the backslash spelled out.

    Written as chr(92) because a doubled backslash in a string literal is
    exactly the thing that silently collapses when this file is edited
    through a shell heredoc.
    """
    return BS + "section{" + name + "}" + chr(10)


def build_body(plan: "Plan", edu: list[Entry], fmt: Fmt, order: list[str],
               display: dict[str, str]) -> str:
    """Render the plan, section by section in `order`, entries in manifest order.

    Order within a section is not inferred here. The manifest already decided
    it, which is why the split layout needs no relevance heuristic: a role is
    in Additional Experience because the manifest said so.
    """
    newline = chr(10)

    def rows(bullets: list[Bullet]) -> str:
        return (" " + BS + BS + newline).join(fmt.prose(b.text) for b in bullets)

    def heading(name: str) -> str:
        return section(fmt.label(display.get(name, name)))

    out = []
    for name in order:
        if name == "Education":
            if edu:
                out.append(heading("Education"))
                out += [render_entry(e, fmt) for e in edu]
        elif name == "Experience":
            if plan.variant == "split":
                primary = [e for e in plan.experience if not e.meta.get("additional")]
                secondary = [e for e in plan.experience if e.meta.get("additional")]
                if primary:
                    # "Relevant Experience" only means something next to an
                    # "Additional" section. With nothing to contrast against,
                    # the plain heading reads better and doesn't imply omitted work.
                    out.append(section("Relevant Experience") if secondary
                               else heading("Experience"))
                    out += [render_entry(e, fmt) for e in primary]
                if secondary:
                    out.append(section("Additional Experience"))
                    out += [render_entry(e, fmt) for e in secondary]
            else:
                out.append(heading("Experience"))
                out += [render_entry(e, fmt) for e in plan.experience]
        # Every other section is optional and whole. Projects in particular earns
        # its space on few postings, and a manifest that omits a section should
        # get a page without the heading rather than an empty one.
        elif name == "Projects":
            if plan.projects:
                out.append(heading("Projects"))
                out += [render_entry(e, fmt) for e in plan.projects]
        elif name == "Skills":
            if plan.skills:
                out.append(heading("Skills") + newline + rows(plan.skills) + newline)
        else:
            items = plan.extra.get(name) or []
            if items and isinstance(items[0], Bullet):
                out.append(heading(name) + newline + rows(items) + newline)
            elif items:
                out.append(heading(name))
                out += [render_entry(e, fmt) for e in items]

    return "\n".join(x for x in out if x)


def load_contact(path: str = CONTACT) -> dict:
    """Contact details, kept out of the repo.

    This is the only file holding personal contact information, so the project
    can be shared or made public without a scrub. It is gitignored, which means
    it does NOT sync between machines -- fail loudly rather than silently
    shipping a resume that says "Your Name / you@example.com".
    """
    if not os.path.exists(path):
        raise SystemExit(
            f"Missing {os.path.relpath(path, ROOT)}.\n"
            f"Copy {os.path.relpath(CONTACT_EXAMPLE, ROOT)} to it and fill in your\n"
            "details. It is gitignored, so this is a one-time step per machine."
        )
    front, _ = parse_master(path)
    missing = [k for k in ("name", "email") if not front.get(k)]
    if missing:
        raise SystemExit(
            f"{os.path.relpath(path, ROOT)} is missing: {', '.join(missing)}"
        )
    return front


# Optional links after phone, email, and location, in this order.
CONTACT_LINKS = ("linkedin", "github", "website", "portfolio")


def _href_url(s: str) -> str:
    """A URL as hyperref's \\href wants it: % and # escaped, the rest as is."""
    return s.replace("%", BS + "%").replace("#", BS + "#")


def contact_line(front: dict) -> str:
    """phone | email | location | links, leaving out any that are blank.

    contact.local.md is plain text whatever master.md is, so every value is
    escaped -- an underscore in an email address would otherwise stop the build.
    """
    t = text_to_latex
    parts = []
    if front.get("phone"):
        parts.append(t(front["phone"]))
    email = front.get("email", "")
    parts.append(f"{BS}href{{mailto:{_href_url(email)}}}{{{t(email)}}}")
    if front.get("location"):
        parts.append(t(front["location"]))
    for key in CONTACT_LINKS:
        v = (front.get(key) or "").strip()
        if v:
            url = v if re.match(r"https?://", v) else "https://" + v
            shown = re.sub(r"^https?://(www\.)?", "", v).rstrip("/")
            parts.append(f"{BS}href{{{_href_url(url)}}}{{{t(shown)}}}")
    return " $|$ ".join(parts)


def render(front: dict, body: str, density: dict) -> str:
    tpl = open(TEMPLATE, encoding="utf-8").read()
    subs = {
        "NAME": text_to_latex(front.get("name", "")),
        "CONTACT": contact_line(front),
        "BODY": body, **density,
    }
    for k, v in subs.items():
        tpl = tpl.replace(f"%%{k}%%", str(v))
    return tpl


# -------------------------------------------------------------------- latex


def compile_pdf(texpath: str) -> tuple[bool, int, str]:
    os.makedirs(BUILD, exist_ok=True)
    try:
        r = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
             "-file-line-error", "-output-directory", BUILD, texpath],
            capture_output=True, text=True, timeout=180)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return (False, 0, f"pdflatex unavailable or timed out: {e}")

    pdf = os.path.join(BUILD, os.path.splitext(os.path.basename(texpath))[0] + ".pdf")
    if not os.path.exists(pdf):
        err = "\n".join(l for l in (r.stdout or "").splitlines()
                        if re.search(r"^.*:\d+:|^!", l))[:1200]
        return (False, 0, err or "pdflatex produced no PDF")
    pages, why = page_count(pdf)
    if not pages:
        return (False, 0, f"pdflatex wrote {pdf} but its page count could not be read: {why}")
    return (True, pages, "")


def page_count(pdf: str) -> tuple[int, str]:
    """Pages in a PDF this script just built, or 0 and the reason why not.

    pdfinfo is the real measurement and stays first. The fallback is for
    machines without Poppler -- BasicTeX on macOS ships pdflatex but no pdfinfo
    -- and reads the count pdflatex reports at the end of its own log, which
    sits beside the PDF in Resume/build. Swallowing the failure and returning a
    bare 0 is what used to make a good build report "build failed:" with no
    reason, so the reason now travels with the 0.
    """
    try:
        r = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, timeout=30)
        m = re.search(r"^Pages:\s+(\d+)", r.stdout, re.M)
        if m:
            return int(m.group(1)), ""
        why = f"pdfinfo could not read it ({(r.stderr or r.stdout).strip()[:200]})"
    except (OSError, subprocess.SubprocessError) as e:
        why = f"pdfinfo unavailable ({e})"

    log = os.path.splitext(pdf)[0] + ".log"
    try:
        with open(log, encoding="utf-8", errors="replace") as fh:
            # TeX hard-wraps its log at 79 columns with no continuation marker,
            # which splits the path (and sometimes the count) across lines.
            text = "".join(fh.read().splitlines())
    except OSError as e:
        return 0, f"{why}, and the pdflatex log could not be read ({e})"
    m = re.findall(r"Output written on .*?\((\d+) pages?, \d+ bytes\)", text)
    if m:
        return int(m[-1]), ""
    return 0, f"{why}, and {log} has no 'Output written on' line"


# Characters Windows forbids in a path component, plus both separators. Kept as
# a set rather than a regex class so the backslash needs no escaping -- an
# escaped one silently dropped out of the class during an earlier edit and the
# bug is invisible until a name actually contains one.
ILLEGAL_PATH_CHARS = set('<>:"|?*/') | {chr(92)}


def safe_name(s: str) -> str:
    """Reduce a company or job title to one safe path component.

    Both fields arrive verbatim from a digest heading, and headings contain
    slashes -- "Apogee / Energy Drive Systems", "Energy / Mechanical /
    Decarbonization". os.path.join reads those as a separator, so an
    unsanitized company files the resume into a nested folder nobody thinks to
    look in. Trailing dots and spaces go too: Windows drops them silently,
    which is how a listing ends up with two folders that look identical.
    """
    s = "".join("-" if c in ILLEGAL_PATH_CHARS else c for c in s)
    return " ".join(s.split()).strip(" .")


BS = chr(92)                 # backslash, spelled out so no escaping is involved
LATEX_SPECIALS = "$&%#_"     # the ones that appear in resume prose by accident


def norm_match(s: str) -> str:
    """Compare bullet text ignoring LaTeX escapes and line wrapping.

    A LaTeX-source master.md stores rendered-ready text, so a bullet really reads
    "third-party M\\&V contractors". Requiring a caller to reproduce that in a
    match string would make every rewrite a guessing game.
    """
    return re.sub(r"\s+", " ", s.replace(BS, "")).strip().lower()


def blank_math(text: str) -> tuple[str, bool]:
    """Blank out balanced $...$ math spans so their contents aren't misjudged.

    master.md writes subscripts as real math -- CO$_2$, Li$_4$ZrF$_8$ -- so a
    check that flagged every unescaped '$' would reject the correct spelling of
    half the battery bullets. Inside math, '_' and '^' are also legitimate.

    A span only counts as math if it is short and space-free, which is what
    distinguishes CO$_2$ from a pay range like "$125,000 to $165,000" that
    happens to contain two dollar signs.
    """
    at = [i for i, c in enumerate(text) if c == "$" and (i == 0 or text[i - 1] != BS)]
    if len(at) % 2:
        return text, False
    chars = list(text)
    for a, b in zip(at[0::2], at[1::2]):
        span = text[a + 1:b]
        if len(span) > 14 or " " in span:
            return text, False
        for k in range(a, b + 1):
            chars[k] = " "
    return "".join(chars), True


def unescaped_specials(text: str) -> list[tuple[int, str]]:
    """Positions of LaTeX specials that are neither escaped nor inside math."""
    rest, ok = blank_math(text)
    if not ok:
        return [(i, "$") for i, c in enumerate(text)
                if c == "$" and (i == 0 or text[i - 1] != BS)]
    return [(i, c) for i, c in enumerate(rest)
            if c in LATEX_SPECIALS and c != "$" and (i == 0 or rest[i - 1] != BS)]


@dataclass
class Plan:
    """Exactly what goes on the page, in page order."""
    variant: str
    experience: list[Entry] = field(default_factory=list)
    projects: list[Entry] = field(default_factory=list)
    skills: list[Bullet] = field(default_factory=list)
    # Any other master.md section -> its entries, or its lines for a list
    # section like Certifications. Manifest order, which is also trim order.
    extra: dict = field(default_factory=dict)
    rewrites: list[tuple[str, str, str]] = field(default_factory=list)


SPECIAL_SECTIONS = {"Education", "Experience", "Projects", "Skills"}


def extra_section(name: str, kinds: dict[str, str]) -> str:
    """A manifest's name for an optional section -> master.md's heading."""
    found = {k.lower(): k for k in kinds if k not in SPECIAL_SECTIONS}
    if name.lower() not in found:
        if name.lower() in {s.lower() for s in SPECIAL_SECTIONS}:
            raise SystemExit(f"manifest: {name!r} has its own key; it does not go under "
                             "`sections`")
        raise SystemExit(f"manifest: no section {name!r} in master.md; optional sections "
                         f"there: {', '.join(sorted(found.values())) or 'none'}")
    return found[name.lower()]


def section_pool(entries: list[Entry], name: str) -> Entry:
    """Every line of a list section, to match against."""
    return Entry(name, [name], [b for e in entries if e.section == name for b in e.bullets])


def find_entry(entries: list[Entry], section: str, employer: str, role: str) -> Entry:
    hits = [e for e in entries
            if e.section == section
            and employer.lower() in e.employer.lower()
            and (not role or role.lower() in e.role.lower())]
    if len(hits) != 1:
        where = "; ".join(f"{e.employer} | {e.role}" for e in hits) or "nothing"
        raise SystemExit(
            f"manifest: {section} entry {employer!r} / {role!r} matched "
            f"{len(hits)} roles ({where}). Name it as it appears in master.md.")
    return hits[0]


def find_bullet(entry: Entry, match: str) -> Bullet:
    hits = [b for b in entry.bullets if norm_match(match) in norm_match(b.text)]
    if len(hits) != 1:
        raise SystemExit(
            f"manifest: under {entry.employer} | {entry.role}, match {match!r} hit "
            f"{len(hits)} bullets. Use a longer, unique fragment of the bullet.\n"
            "This is a hard error on purpose: a silently unmatched bullet would "
            "ship a resume missing evidence the manifest claimed was on it.")
    return hits[0]


def take(entry: Entry, spec: list, mode: str = "latex") -> tuple[list[Bullet], list[tuple]]:
    """Resolve a bullet spec against one role. Returns (bullets, rewrites).

    A rewrite is written the way master.md is: plain text when master.md is
    plain text (the renderer escapes it), LaTeX source when it is LaTeX.
    """
    chosen, rewrites = [], []
    for item in spec:
        if isinstance(item, str):
            item = {"match": item}
        b = find_bullet(entry, item["match"])
        text = item.get("text")
        if text:
            bad = unescaped_specials(text) if mode == "latex" else []
            if bad:
                where = ", ".join(f"{c!r} at {i}" for i, c in bad)
                raise SystemExit(
                    f"manifest: unescaped LaTeX special(s) in a rewrite: {where}.\n"
                    f"master.md carries its own escapes and the renderer adds "
                    f"none, so write them the same way: {BS}$11M, M{BS}&V, 10{BS}%.")
            rewrites.append((f"{entry.employer} - {entry.role}", b.text, text))
        chosen.append(Bullet(b.priority, text or b.text, b.source or b.text))
    return chosen, rewrites


def resolve_manifest(entries: list[Entry], man: dict, mode: str = "latex",
                     kinds: dict[str, str] | None = None) -> Plan:
    """Turn a manifest into a Plan, resolving every line against master.md.

    Nothing here can introduce content. A bullet reaches the page only by
    resolving to one that already exists, and a rewrite only replaces that
    bullet's wording -- so "never invent a claim" is structural, not a rule
    someone has to remember.
    """
    kinds = kinds or section_kinds(entries)
    plan = Plan(variant=man.get("variant", "chronological"))
    if plan.variant not in ("chronological", "split"):
        raise SystemExit(f"manifest: unknown variant {plan.variant!r}")

    for item in man.get("experience", []):
        e = find_entry(entries, "Experience", item["employer"], item.get("role", ""))
        bullets, rw = take(e, item.get("bullets", []), mode)
        plan.rewrites += rw
        ne = Entry("Experience", e.title_parts, bullets, dict(e.meta))
        ne.meta["additional"] = bool(item.get("additional"))
        plan.experience.append(ne)

    for item in man.get("projects", []):
        e = find_entry(entries, "Projects", item["employer"], item.get("role", ""))
        bullets, rw = take(e, item.get("bullets", []), mode)
        plan.rewrites += rw
        plan.projects.append(
            Entry("Projects", e.title_parts, bullets, dict(e.meta)))

    skill_pool = Entry("Skills", ["Skills"],
                       [b for e in entries if e.section == "Skills" for b in e.bullets])
    for item in man.get("skills", []):
        match = item if isinstance(item, str) else item["match"]
        plan.skills.append(find_bullet(skill_pool, match))

    # Any other section: lines by match for a list section, entries like
    # projects otherwise.
    for name, spec in (man.get("sections") or {}).items():
        s = extra_section(name, kinds)
        if kinds[s] == "list":
            pool = section_pool(entries, s)
            plan.extra[s] = [find_bullet(pool, it if isinstance(it, str) else it["match"])
                             for it in spec]
            continue
        items = []
        for item in spec:
            e = find_entry(entries, s, item["employer"], item.get("role", ""))
            bullets, rw = take(e, item.get("bullets", []), mode)
            plan.rewrites += rw
            items.append(Entry(s, e.title_parts, bullets, dict(e.meta)))
        plan.extra[s] = items

    if not plan.experience:
        raise SystemExit("manifest: 'experience' is empty -- nothing to build")
    return plan


def resolve_fill(entries: list[Entry], man: dict, mode: str = "latex",
                 kinds: dict[str, str] | None = None) -> list[dict]:
    """Resolve the manifest's `fill` candidates without placing any of them.

    Resolved up front so a typo fails the build immediately. If these were
    looked up lazily, a bad match would surface only on the runs where the page
    happened to have room -- the worst kind of intermittent bug.
    """
    kinds = kinds or section_kinds(entries)
    out = []
    for item in man.get("fill", []):
        if isinstance(item, str):
            item = {"match": item}
        kind = item.get("section", "experience")

        if kind == "skills":
            pool = Entry("Skills", ["Skills"],
                         [b for e in entries if e.section == "Skills"
                          for b in e.bullets])
            b = find_bullet(pool, item["match"])
            out.append({"kind": "skills", "bullet": b, "rewrites": [],
                        "label": f"skills line: {b.text[:52]}"})
            continue

        if kind not in ("projects", "experience"):
            s = extra_section(kind, kinds)
            if kinds[s] == "list":
                b = find_bullet(section_pool(entries, s), item["match"])
                out.append({"kind": "list", "section": s, "bullet": b, "rewrites": [],
                            "label": f"{s} line: {b.text[:52]}"})
                continue
            e = find_entry(entries, s, item["employer"], item.get("role", ""))
            bullets, rw = take(e, item.get("bullets", []), mode)
            if not bullets:
                raise SystemExit(f"fill: {item['employer']} names no bullets")
            out.append({"kind": "entries", "section": s, "entry": e, "bullets": bullets,
                        "rewrites": rw, "label": f"{len(bullets)} bullet(s) to {s}: "
                                                 f"{e.employer}"})
            continue

        sec = "Projects" if kind == "projects" else "Experience"
        e = find_entry(entries, sec, item["employer"], item.get("role", ""))
        bullets, rw = take(e, item.get("bullets", []), mode)
        if not bullets:
            raise SystemExit(f"fill: {item['employer']} names no bullets")
        what = (f"{len(bullets)} bullet(s) to {e.employer} - {e.role}"
                if not item.get("new_role")
                else f"role {e.employer} - {e.role}")
        out.append({"kind": sec.lower(), "entry": e, "bullets": bullets,
                    "rewrites": rw, "additional": bool(item.get("additional")),
                    "label": what})
    return out


def single_bullet_roles(plan: Plan) -> list[Entry]:
    """Experience entries carrying exactly one bullet.

    Projects are excluded: a one-line project reads as a project, not as a job
    the page could not say anything about.
    """
    return [e for e in plan.experience if len(e.bullets) == 1]


def thin_relevant_roles(plan: Plan) -> list[Entry]:
    """Roles under "Relevant Experience" with a single bullet.

    Only meaningful in the split layout, and only when an Additional section
    actually exists -- without one the heading renders as plain "Experience"
    and makes no relevance claim. Where the claim IS made, a role supporting it
    with one line undercuts it: the page asserts the work matters and then
    shows a single sentence. Chronological makes no such claim, so a one-line
    role there is fine.
    """
    if plan.variant != "split":
        return []
    if not any(e.meta.get("additional") for e in plan.experience):
        return []
    return [e for e in plan.experience
            if not e.meta.get("additional") and len(e.bullets) == 1]


def already_on_page(plan: Plan, cand: dict) -> bool:
    """Is this candidate's evidence already shown?

    A fill list is written by hand against a manifest, so naming a bullet the
    base already selected is an easy mistake -- and one that silently ships the
    same sentence twice. It shipped exactly that way once. Compared on `source`
    rather than rendered text, so a reworded duplicate is caught too.
    """
    shown = {b.source for e in plan.experience + plan.projects for b in e.bullets}
    shown |= {b.source for b in plan.skills}
    for items in plan.extra.values():
        for it in items:
            shown |= ({it.source} if isinstance(it, Bullet)
                      else {b.source for b in it.bullets})
    if cand["kind"] in ("skills", "list"):
        return cand["bullet"].source in shown
    return any(b.source in shown for b in cand["bullets"])


def apply_fill(plan: Plan, cand: dict):
    """Place one candidate on the page. Returns a callable that undoes it.

    Bullets join a role already on the page; a role that is not there yet is
    appended to its section. Either way the undo is exact, so a candidate that
    does not fit leaves no trace.
    """
    if cand["kind"] == "skills":
        plan.skills.append(cand["bullet"])
        return lambda: plan.skills.pop()
    if cand["kind"] == "list":
        lines = plan.extra.setdefault(cand["section"], [])
        lines.append(cand["bullet"])
        return lambda: lines.pop()

    if cand["kind"] == "entries":
        target = plan.extra.setdefault(cand["section"], [])
    else:
        target = plan.projects if cand["kind"] == "projects" else plan.experience
    e = cand["entry"]
    for existing in target:
        if (existing.employer == e.employer
                and existing.role == e.role):
            n = len(cand["bullets"])
            existing.bullets += cand["bullets"]
            cand["applied"] = f"{n} bullet(s) to {e.employer} - {e.role}"
            return lambda: existing.bullets.__delitem__(slice(-n, None))

    ne = Entry(e.section, e.title_parts, list(cand["bullets"]), dict(e.meta))
    if cand["kind"] == "experience":
        ne.meta["additional"] = cand["additional"]
    target.append(ne)
    where = " to Additional Experience" if cand.get("additional") else ""
    cand["applied"] = (f"new role {e.employer} - {e.role} ({e.dates}){where}"
                       if cand["kind"] == "experience" else
                       f"new {e.section} entry {e.employer}")
    return lambda: target.remove(ne)


# The template prints this before \end{document}: the height the last page
# can hold, the height used, and one line's height.
SLACK_RE = re.compile(r"RESUME-SLACK ([\d.]+)pt ([\d.]+)pt ([\d.]+)pt")


def free_lines(base: str) -> int | None:
    """How many more lines of text the last page would hold, or None.

    LaTeX reports this itself (see the template), so it needs no PDF tools and
    measures the text area exactly, margins excluded. pdftotext's text grid
    used to stand in for it; that counted the bottom margin as free rows and
    was missing on any machine without Poppler.
    """
    try:
        with open(os.path.join(BUILD, base + ".log"), encoding="utf-8",
                  errors="replace") as fh:
            m = SLACK_RE.findall(fh.read())
    except OSError:
        return None
    if not m:
        return None
    goal, used, line = (float(x) for x in m[-1])
    if goal > 16000 or line <= 0:      # \maxdimen: the last page is empty
        return None
    return max(0, int((goal - used) // line))


def plan_everything(entries: list[Entry], kinds: dict[str, str] | None = None) -> Plan:
    """Every bullet, for the full CV. No manifest, no selection."""
    kinds = kinds or section_kinds(entries)
    plan = Plan(variant="chronological")
    for e in entries:
        if e.section == "Experience":
            plan.experience.append(
                Entry(e.section, e.title_parts,
                      [b for b in e.bullets if b.priority != "S"], dict(e.meta)))
        elif e.section == "Projects":
            plan.projects.append(e)
        elif e.section == "Skills":
            plan.skills += list(e.bullets)
        elif e.section not in SPECIAL_SECTIONS:
            if kinds[e.section] == "list":
                plan.extra.setdefault(e.section, []).extend(e.bullets)
            else:
                plan.extra.setdefault(e.section, []).append(e)
    return plan


def drop_one(plan: Plan) -> str | None:
    """Shed the least important thing still on the page.

    Manifest order is importance order, so trimming works from the end. A whole
    role only goes when removing it leaves no gap in the employment dates --
    otherwise the trim skips past it and keeps taking bullets from further up.
    """
    for i in range(len(plan.experience) - 1, -1, -1):
        e = plan.experience[i]
        if len(e.bullets) > 1:
            gone = e.bullets.pop()
            return f"bullet from {e.employer} - {e.role}: {gone.text[:70]}..."

    for i in range(len(plan.experience) - 1, -1, -1):
        kept = plan.experience[:i] + plan.experience[i + 1:]
        if kept and not creates_gap(kept):
            gone = plan.experience.pop(i)
            return f"role {gone.employer} - {gone.role} ({gone.dates}) -- leaves no gap"

    if plan.projects:
        gone = plan.projects.pop()
        return f"project {gone.employer}"
    # Optional sections next, from the last one the manifest named.
    for name in reversed(list(plan.extra)):
        items = plan.extra[name]
        if not items:
            continue
        last = items[-1]
        if isinstance(last, Bullet):
            items.pop()
            return f"{name} line: {last.text[:60]}..."
        if len(last.bullets) > 1:
            gone = last.bullets.pop()
            return f"bullet from {name} - {last.employer}: {gone.text[:60]}..."
        items.pop()
        return f"{name} entry {last.employer}"
    if plan.skills:
        gone = plan.skills.pop()
        return f"skills line: {gone.text[:60]}..."
    return None


# --------------------------------------------------------------------- main


def main() -> int:
    # Piped, stdout is block-buffered and stderr is not, so NOT FILED landed
    # above the report it ends, where a skill reading the tail missed it.
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", metavar="JSON",
                    help="what to put on the page, in order. See resolve_manifest().")
    ap.add_argument("--all", action="store_true",
                    help="every bullet, for the full CV (no manifest needed)")
    ap.add_argument("--variant", choices=["chronological", "split"],
                    help="override the manifest's variant")
    ap.add_argument("--out", help="output basename (default: editing_<variant>)")
    ap.add_argument("--max-pages", type=int,
                    help="page limit (default: the manifest's max_pages, then "
                         "master.md's, then 1)")
    ap.add_argument("--company", help="file the PDF under Applications/<company>/")
    ap.add_argument("--title", help="filename to use when filing (the job title)")
    ap.add_argument("--master", default=MASTER, help="resume facts (default: %(default)s)")
    ap.add_argument("--contact", default=CONTACT, help="contact details (default: %(default)s)")
    args = ap.parse_args()

    if not (args.manifest or args.all):
        print("specify --manifest <file> or --all", file=sys.stderr)
        return 2
    if args.company and not args.title:
        print("--company requires --title", file=sys.stderr)
        return 2

    master_front, entries = parse_master(args.master)
    display = normalize_sections(entries)
    check_dates(entries)
    kinds = section_kinds(entries)
    mode, mode_why = master_format(args.master, master_front)
    fmt = Fmt(mode)
    front = load_contact(args.contact)

    fill = []
    man: dict = {}
    if args.all:
        plan = plan_everything(entries, kinds)
    else:
        with open(args.manifest, encoding="utf-8") as fh:
            man = json.load(fh)
        plan = resolve_manifest(entries, man, mode, kinds)
        fill = resolve_fill(entries, man, mode, kinds)
    if args.variant:
        plan.variant = args.variant
    max_pages = int(args.max_pages or man.get("max_pages")
                    or master_front.get("max_pages") or 1)
    present = list(dict.fromkeys(e.section for e in entries))
    order = section_order(master_front, man, present)

    edu = [e for e in entries if e.section == "Education"]
    base = args.out or f"editing_{plan.variant}"
    texpath = os.path.join(LATEX, base + ".tex")

    def attempt(density: dict) -> tuple[int, str]:
        body = build_body(plan, edu, fmt, order, display)
        with open(texpath, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(front, body, density))
        ok, pages, err = compile_pdf(texpath)
        return (pages if ok else 0), err

    # Whitespace before content, always: losing a line of padding is never worse
    # than losing a line of evidence.
    dropped: list[str] = []
    density = DENSITY_TIERS[0]
    pages, err = attempt(density)
    if not pages:
        print(f"build failed:\n{err}", file=sys.stderr)
        return 1

    for tier in DENSITY_TIERS[1:]:
        if pages <= max_pages:
            break
        density = tier
        pages, err = attempt(density)

    while pages > max_pages:
        what = drop_one(plan)
        if what is None:
            break
        dropped.append(what)
        pages, err = attempt(density)

    # Fill the leftover space. Trimming has a counterpart: a manifest written
    # conservatively leaves a short page, which reads as though there was
    # nothing more to say. Candidates are tried in the order the manifest lists
    # them, and each is kept only if the page count still holds.
    #
    # A candidate that does not fit gets the density ladder before it gets
    # rejected. Freezing density here was tried first and was wrong: it left
    # five resumes with an inch of white space, because a bullet needing one
    # more line had nowhere to go. A page at 0.45in margins carrying one more
    # piece of evidence beats a roomier page that stops two thirds down.
    #
    # Tightening still never buys a *trim*: if no tier fits the candidate, the
    # candidate goes, not the content the author chose.
    added: list[str] = []
    rejected: list[str] = []
    if fill and pages <= max_pages:
        for cand in fill:
            if already_on_page(plan, cand):
                rejected.append(f"{cand['label']}  [already on the page]")
                continue
            # Two one-line roles is comfortable, three is tolerable, four makes
            # the page look like a list of jobs with nothing to say about them.
            # That is the failure this whole pass was meant to fix, so filling
            # is not allowed to cause it.
            new_thin = (cand["kind"] == "experience"
                        and len(cand["bullets"]) == 1
                        and not any(e.employer == cand["entry"].employer
                                    and e.role == cand["entry"].role
                                    for e in plan.experience))
            if new_thin and len(single_bullet_roles(plan)) >= 3:
                rejected.append(
                    f"{cand['label']}  [would be a 4th single-bullet role]")
                continue
            undo = apply_fill(plan, cand)
            trial, _ = attempt(density)
            landed = density
            if not (trial and trial <= max_pages):
                start = DENSITY_TIERS.index(density) + 1
                for tier in DENSITY_TIERS[start:]:
                    trial, _ = attempt(tier)
                    if trial and trial <= max_pages:
                        landed = tier
                        break
            if trial and trial <= max_pages:
                density = landed
                added.append(cand.get("applied", cand["label"]))
                plan.rewrites += cand["rewrites"]
            else:
                rejected.append(cand.get("applied", cand["label"]))
                # Keep going rather than stopping at the first refusal -- a
                # one-line skills entry still fits where a three-bullet role did
                # not, and the author ordered the list by value, not by size.
                undo()
        pages, err = attempt(density)

    pdf_src = os.path.join(BUILD, base + ".pdf")
    os.makedirs(PDFDIR, exist_ok=True)
    shutil.copy(pdf_src, os.path.join(PDFDIR, base + ".pdf"))

    print(f"variant   : {plan.variant}")
    print(f"source    : {'--all (every bullet)' if args.all else args.manifest}")
    print(f"master    : {os.path.relpath(args.master, ROOT)} as {mode} ({mode_why})")
    print(f"density   : margins {density['VMARGIN']}, section spacing {density['SECSPACE']}"
          + ("  (tightened to fit)" if density is not DENSITY_TIERS[0] else ""))
    print(f"pages     : {pages} (limit {max_pages})")
    print(f"tex       : {texpath}")
    print(f"pdf       : {os.path.join(PDFDIR, base + '.pdf')}")

    print("\non the page, in order:")
    for e in plan.experience:
        tag = "  [additional]" if e.meta.get("additional") else ""
        print(f"  {len(e.bullets)} bullet(s)  {e.employer} - {e.role}{tag}")
    if plan.projects:
        print(f"  projects  : {', '.join(e.employer for e in plan.projects)}")
    print(f"  skills    : {len(plan.skills)} line(s)")
    for name, items in plan.extra.items():
        if items and isinstance(items[0], Bullet):
            print(f"  {name}: {len(items)} line(s)")
        elif items:
            print(f"  {name}: {', '.join(e.employer for e in items)}")

    if plan.rewrites:
        flat = re.sub(r"[^a-z0-9]", "",
                      open(texpath, encoding="utf-8").read().lower())
        print("\nbullets reworded for this posting (content/master.md unchanged):")
        for where, old, new in plan.rewrites:
            on_page = re.sub(r"[^a-z0-9]", "", new.lower())[:60] in flat
            print(f"  {where}" + ("" if on_page else "   [CUT - did not reach the page]"))
            print(f"    was: {old}")
            print(f"    now: {new}")

    if added or rejected:
        print("\nfill pass (page count re-checked after each):")
        for a in added:
            print(f"  + {a}")
    for r in rejected:
        print(f"  - {r}" + ("" if r.endswith("]") else "  [no room]"))

    # Three free lines is about half an inch of white space at the bottom --
    # enough to read as "nothing more to say". The old pdftotext estimate used
    # a threshold of 5, but counted margin rows that this measurement excludes.
    slack = free_lines(base)
    if slack is not None and slack >= 3:
        print(f"\nroughly {slack} lines of slack still on the page"
              + (" -- add more `fill` candidates" if not fill
                 else " -- every fill candidate that fits is already on"))

    if dropped:
        print("\ntrimmed to hold the page limit (in the order it went):")
        for d in dropped:
            print(f"  - {d}")

    if pages > max_pages:
        print(f"\nWARNING: still {pages} pages with nothing left to trim.",
              file=sys.stderr)

    thin = thin_relevant_roles(plan)
    if thin:
        print("\nNOT FILED -- these sit under Relevant Experience with one bullet:",
              file=sys.stderr)
        for e in thin:
            print(f"  {e.employer} - {e.role}", file=sys.stderr)
        print("A role claimed as relevant has to support the claim. Give it a "
              "second bullet,\nmove it to Additional Experience with "
              '"additional": true, or build chronological.', file=sys.stderr)
        return 1

    thin_total = single_bullet_roles(plan)
    if len(thin_total) > 3:
        print(f"\nWARNING: {len(thin_total)} single-bullet roles on the page "
              "(three is the practical ceiling):")
        for e in thin_total:
            print(f"  {e.employer} - {e.role}")

    if args.company:
        dest_dir = os.path.join(APPS, safe_name(args.company))
        os.makedirs(dest_dir, exist_ok=True)
        stem = safe_name(args.title)

        # The .tex is filed with the PDF because it is not durable where it was
        # built: every build overwrites Resume/LaTeX/editing_<variant>.tex, so
        # a batch of seven applications would leave only the seventh on disk.
        # The copy is standalone -- CTAN packages, no local includes -- so it
        # recompiles as-is if one posting ever needs a hand tweak.
        dest_pdf = os.path.join(dest_dir, stem + ".pdf")
        dest_tex = os.path.join(dest_dir, stem + ".tex")
        shutil.copy(pdf_src, dest_pdf)
        shutil.copy(texpath, dest_tex)
        print(f"\nfiled     : {dest_pdf}")
        print(f"            {dest_tex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

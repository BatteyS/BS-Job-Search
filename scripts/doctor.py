"""Check that this copy of the workflow is ready to run, and say what to fix.

Run it first on a new machine, and whenever something stops working:

    python scripts/doctor.py

Each line is one check: `ok`, `MISSING` with the fix for this operating system,
`DRAFT` for a file /setup wrote that has not been reviewed yet, or `optional` for
something only some features need. It reads files and runs
local tools only -- no network -- and changes nothing. Exit code 1 means a
required check failed.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OS = platform.system()          # Darwin, Windows, Linux

# Packages the resume and letter templates load, by file, with the CTAN package
# that provides each.
LATEX_FILES = {"geometry.sty": "geometry", "newtxtext.sty": "newtx",
               "enumitem.sty": "enumitem", "hyperref.sty": "hyperref",
               "titlesec.sty": "titlesec"}

FIX = {
    "latex": {
        "Darwin": "install BasicTeX (brew install --cask basictex, or the installer at "
                  "tug.org/mactex), open a new terminal, then run: sudo tlmgr update --self && "
                  "sudo tlmgr install enumitem titlesec newtx fontaxes xstring kastrup tex-gyre",
        "Windows": "install MiKTeX from miktex.org/download, and set it to install missing "
                   "packages on the fly when its installer asks (or later, in MiKTeX Console's "
                   "Settings): the first resume build then fetches them without stopping to ask",
        "Linux": "sudo apt install texlive-latex-recommended texlive-latex-extra "
                 "texlive-fonts-extra (or your distribution's equivalent)",
    },
    "latex_packages": {
        "Darwin": "sudo tlmgr update --self && sudo tlmgr install enumitem titlesec newtx "
                  "fontaxes xstring kastrup tex-gyre",
        "Windows": "MiKTeX installs them on the first build when it is set to install missing "
                   "packages on the fly (MiKTeX Console, Settings); or add them there by hand",
        "Linux": "sudo apt install texlive-latex-extra texlive-fonts-extra",
    },
}

# /setup marks a ground-truth file it drafted with this line until the user has
# reviewed it, so an unfinished review is visible here and resumable.
DRAFT = "<!-- /setup draft: not yet reviewed -->"

# The placeholder values in the shipped .example files.
PLACEHOLDERS = {"your-app-id", "your-app-key", "your-api-key", "you@example.com",
                "your name", ""}

results: list[tuple[str, str, str, str]] = []     # (status, what, detail, fix)


def report(status: str, what: str, detail: str = "", fix: str = "") -> None:
    results.append((status, what, detail, fix))


def rel(p: str) -> str:
    return os.path.relpath(p, ROOT)


# pyproject.toml's one optional extra, by the module it installs. Everything
# else, the page included, is a dependency that any `uv sync` keeps.
EXTRAS = {"scraped": "jobspy"}


def uv_sync(*extras: str) -> str:
    """The `uv sync` that adds `extras` and keeps those already installed. A
    sync uninstalls every extra it is not given, so a fix for one must name
    the others too."""
    keep = {e for e, mod in EXTRAS.items() if importlib.util.find_spec(mod)}
    return "uv sync" + "".join(f" --extra {e}" for e in sorted(keep | set(extras)))


def python_fix() -> str:
    if shutil.which("uv") and os.path.exists(os.path.join(ROOT, "pyproject.toml")):
        return f"{uv_sync()}   (then run scripts with: uv run python scripts/<name>.py)"
    return ("install uv (astral.sh/uv) and run: uv sync -- or: "
            f"{os.path.basename(sys.executable)} -m pip install pyyaml requests")


# ----------------------------------------------------------------- python


def check_python() -> None:
    v = sys.version_info
    shown = f"{v.major}.{v.minor}.{v.micro} at {sys.executable}"
    if v < (3, 10):
        # pyproject.toml's requires-python, which uv enforces.
        report("MISSING", "Python 3.10 or newer", shown, python_fix())
    else:
        report("ok", "Python", shown)
    for mod, pkg in (("yaml", "pyyaml"), ("requests", "requests")):
        if importlib.util.find_spec(mod):
            report("ok", f"Python package {pkg}")
        else:
            report("MISSING", f"Python package {pkg}", "", python_fix())
    if importlib.util.find_spec("pypdf"):
        report("ok", "Python package pypdf", "reads PDF resumes (scripts/extract_text.py)")
    else:
        report("optional", "Python package pypdf",
               "only for reading a PDF resume with scripts/extract_text.py; a .docx works without it",
               f"{uv_sync()}   or: pip install pypdf")


# ------------------------------------------------------------------ latex


def check_latex() -> None:
    pdflatex = shutil.which("pdflatex")
    if not pdflatex:
        report("MISSING", "pdflatex (builds resumes and letters)", "", FIX["latex"].get(OS, ""))
        return
    report("ok", "pdflatex", pdflatex)
    kpse = shutil.which("kpsewhich")
    if not kpse:
        report("optional", "LaTeX package check",
               "kpsewhich not found, so packages are checked on the first build instead")
        return
    missing = []
    for f, pkg in LATEX_FILES.items():
        r = subprocess.run([kpse, f], capture_output=True, text=True)
        if not r.stdout.strip():
            missing.append(pkg)
    if missing:
        report("MISSING", "LaTeX packages", ", ".join(sorted(set(missing))),
               FIX["latex_packages"].get(OS, ""))
    else:
        report("ok", "LaTeX packages", ", ".join(sorted(set(LATEX_FILES.values()))))


# ---------------------------------------------------------------- profile


def check_profile() -> dict:
    """The user's own files. Returns filters.yaml, parsed, for the source checks."""
    setup = "run /setup in Claude Code, which interviews you and writes it"
    review = "finish reviewing it: run /setup, which picks up where it stopped"

    def draft(path: str) -> bool:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return DRAFT in fh.read()
    try:
        import yaml
    except ImportError:
        report("MISSING", "profile checks", "need pyyaml first", python_fix())
        return {}

    contact = os.path.join(ROOT, "content/contact.local.md")
    if not os.path.exists(contact):
        report("MISSING", rel(contact), "", f"{setup}, or copy content/contact.example.md")
    else:
        from build_resume import parse_master
        front, _ = parse_master(contact)
        bad = [k for k in ("name", "email")
               if str(front.get(k, "")).strip().lower() in PLACEHOLDERS]
        report("MISSING" if bad else "ok", rel(contact),
               f"still the example's {', '.join(bad)}" if bad else "",
               "edit it with your real details" if bad else "")

    master = os.path.join(ROOT, "content/master.md")
    if not os.path.exists(master):
        report("MISSING", rel(master), "every resume fact lives here", setup)
    else:
        from build_resume import check_dates, master_format, normalize_sections, parse_master
        front, entries = parse_master(master)
        normalize_sections(entries)
        mode, _ = master_format(master, front)
        roles = sum(1 for e in entries if e.section == "Experience")
        bullets = sum(len(e.bullets) for e in entries)
        try:
            check_dates(entries)
            shape = f"{roles} roles, {bullets} bullets, read as {mode}"
            if draft(master):
                report("DRAFT", rel(master), f"written by /setup, not yet reviewed ({shape})",
                       review)
            else:
                report("ok", rel(master), shape)
        except SystemExit as e:
            report("MISSING", rel(master), str(e).splitlines()[0],
                   "fix the dates it names -- " + str(e).splitlines()[-1])

    story = os.path.join(ROOT, "content/story.md")
    if not os.path.exists(story):
        report("optional", rel(story), "only cover letters need it",
               f"{setup}, or start from content/story.example.md")
    elif draft(story):
        report("DRAFT", rel(story), "written by /setup, not yet reviewed", review)
    else:
        report("ok", rel(story))

    profile = os.path.join(ROOT, "profile/profile.md")
    if not os.path.exists(profile):
        report("MISSING", rel(profile), "the scoring rubric lives here", setup)
    elif draft(profile):
        report("DRAFT", rel(profile), "written by /setup, not yet reviewed", review)
    else:
        report("ok", rel(profile))

    feedback = os.path.join(ROOT, "profile/feedback.md")
    report("ok" if os.path.exists(feedback) else "optional", rel(feedback),
           "" if os.path.exists(feedback) else "starts empty; your digest verdicts go here")

    import tracker
    tracked = os.path.join(ROOT, tracker.TRACKER)
    if not os.path.exists(tracked):
        report("optional", rel(tracked), "the page's Applications tab writes it once you "
               "record where an application stands")
    else:
        t = tracker.load(tracked)
        broken = [e for e in t.entries if e.problem]
        if t.problem:
            report("MISSING", rel(tracked), t.problem)
        else:
            n = len(t.entries)
            report("ok", rel(tracked), f"{n} application{'' if n == 1 else 's'}" + (
                f"; {len(broken)} to fix by hand, first: {broken[0].problem}" if broken else ""))

    clusters = os.path.join(ROOT, "profile/clusters.yaml")
    if not os.path.exists(clusters):
        report("MISSING", rel(clusters), "what roles to look for", setup)
    else:
        try:
            cfg = yaml.safe_load(open(clusters, encoding="utf-8")) or {}
            from fetch_jobs import ClusterMatcher
            ClusterMatcher(cfg)
            ids = [c["id"] for c in cfg.get("clusters") or []]
            report("ok", rel(clusters), f"{len(ids)} clusters: {', '.join(ids)}")
        except (SystemExit, Exception) as e:                     # noqa: BLE001
            report("MISSING", rel(clusters), f"does not load: {str(e).splitlines()[0]}",
                   "fix the line it names")

    filters_path = os.path.join(ROOT, "profile/filters.yaml")
    if not os.path.exists(filters_path):
        report("MISSING", rel(filters_path), "where, how much, which sources", setup)
        return {}
    try:
        filters = yaml.safe_load(open(filters_path, encoding="utf-8")) or {}
    except Exception as e:                                       # noqa: BLE001
        report("MISSING", rel(filters_path), f"does not load: {e}", "fix the line it names")
        return {}
    metros = filters.get("metros") or {}
    blind = [k for k, m in metros.items() if not (m or {}).get("search_as")]
    report("ok", rel(filters_path),
           f"{len(metros)} metros, remote {(filters.get('remote') or {}).get('mode', 'include')}"
           + (f"; no search_as for {', '.join(blind)}" if blind else ""))
    return filters


# ---------------------------------------------------------------- sources


# The sources that need a key, each kept in a gitignored file,
# sources/<name>.local.yaml: name -> (label, where to register, the file's
# fields, the environment variables that win over it, what to paste). The
# page's Setup tab writes these files too.
KEYS = {
    "adzuna": ("Adzuna", "developer.adzuna.com/signup", ("app_id", "app_key"),
               ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"), "your app ID and key"),
    "usajobs": ("USAJOBS", "developer.usajobs.gov/APIRequest", ("email", "api_key"),
                ("USAJOBS_EMAIL", "USAJOBS_API_KEY"),
                "your key and the email you registered with"),
}


def _creds(path: str, keys: tuple[str, ...], env: tuple[str, ...]) -> str | None:
    """None if usable credentials exist, else what is wrong. Values never print."""
    if all(os.environ.get(k) for k in env):
        return None
    if not os.path.exists(path):
        return f"{rel(path)} does not exist"
    import yaml
    c = yaml.safe_load(open(path, encoding="utf-8")) or {}
    bad = [k for k in keys if str(c.get(k, "")).strip().lower() in PLACEHOLDERS]
    return f"{rel(path)} still has the example's {', '.join(bad)}" if bad else None


def key_problem(name: str) -> str | None:
    """None if a KEYS source's credentials are usable, else what is wrong."""
    _, _, fields, env, _ = KEYS[name]
    return _creds(os.path.join(ROOT, f"sources/{name}.local.yaml"), fields, env)


EMPLOYERS = ("/setup adds the employers you most want to work for; or add them yourself "
             "with scripts/detect_ats.py")


def check_sources(filters: dict) -> None:
    sources = filters.get("sources")
    on = ({k for k, v in sources.items() if v} if isinstance(sources, dict)
          else {"boards"})

    companies = os.path.join(ROOT, "sources/companies.yaml")
    if "boards" in on:
        if os.path.exists(companies):
            import yaml
            d = yaml.safe_load(open(companies, encoding="utf-8")) or {}
            n = len(d.get("companies") or []) + len(d.get("manual") or [])
            report("ok" if n else "optional", "company boards",
                   f"{n} in {rel(companies)}" if n else
                   "none listed yet; the aggregators still search",
                   "" if n else EMPLOYERS)
        else:
            report("optional", "company boards", f"no {rel(companies)}", EMPLOYERS)

    def key_fix(name: str) -> str:
        _, signup, _, _, what = KEYS[name]
        local = f"sources/{name}.local.yaml"
        step = (f"open {local} and paste {what} into it"
                if os.path.exists(os.path.join(ROOT, local)) else
                f"copy sources/{name}.example.yaml to {local} and paste {what} into it")
        return f"register free at {signup}, then save it in the page's Setup tab, or {step}"

    for name, (label, *_) in KEYS.items():
        if name in on:
            why = key_problem(name)
            report("MISSING" if why else "ok", f"{label} key", why or "",
                   key_fix(name) if why else "")

    scraped = sorted(on & {"indeed", "linkedin", "glassdoor", "ziprecruiter"})
    if scraped:
        if sys.version_info < (3, 10):
            run = (uv_sync("scraped") if shutil.which("uv")
                   else f"install uv (astral.sh/uv) and run: {uv_sync('scraped')}")
            report("MISSING", f"scraped boards ({', '.join(scraped)})",
                   f"JobSpy needs Python 3.10 or newer; this is {sys.version_info.major}."
                   f"{sys.version_info.minor}",
                   f"{run} -- uv fetches a newer Python itself. Or turn the scraped boards "
                   "off under `sources` in filters.yaml")
        elif not importlib.util.find_spec("jobspy"):
            report("MISSING", f"scraped boards ({', '.join(scraped)})",
                   "the JobSpy library is not installed",
                   f"{uv_sync('scraped')}   (see README.md for a pip install)")
        else:
            report("ok", f"scraped boards ({', '.join(scraped)})",
                   "at your own risk; each prints a warning when it runs")


def check_page() -> None:
    """The local page. Never holds back "Ready.": the scripts work without the
    page, and the page's other tabs without Claude Code."""
    if not os.path.isfile(os.path.join(ROOT, "ui", "claude_run.py")):
        return   # a copy without the page
    missing = [m for m in ("fastapi", "uvicorn", "claude_agent_sdk")
               if not importlib.util.find_spec(m)]
    if missing:
        report("optional", "Python packages for the page", f"{', '.join(missing)} not installed",
               f"{uv_sync()}   or: pip install fastapi uvicorn claude-agent-sdk")
        return
    sys.path.insert(0, os.path.join(ROOT, "ui"))
    import claude_run
    s = claude_run.claude_status()
    if s["available"]:
        report("ok", "Claude Code for the page", f"{s['version']} ({s['how']})")
    else:
        report("NOTE", "Claude Code for the page", s["reason"],
               "only the page's skill buttons need this; the rest of the page works "
               "without it, and BS_CLAUDE_BIN names a different binary")


def run_checks(page: bool = True) -> list[dict]:
    """Every check, in order, as {group, status, what, detail, fix}. The group
    is the check that made the row: python, latex, profile, sources, or page.
    The page's Setup tab reads these, and asks Claude Code's state itself."""
    results.clear()
    rows: list[dict] = []

    def run(group: str, check, *args):
        start = len(results)
        out = check(*args)
        rows.extend({"group": group, "status": s, "what": w, "detail": d, "fix": f}
                    for s, w, d, f in results[start:])
        return out

    run("python", check_python)
    run("latex", check_latex)
    filters = run("profile", check_profile)
    run("sources", check_sources, filters)
    if page:
        run("page", check_page)
    return rows


def main() -> int:
    print(f"Checking {ROOT} ({OS})\n")
    rows = run_checks()

    width = max(len(r["what"]) for r in rows)
    for r in rows:
        print(f"  {r['status']:8} {r['what']:<{width}}  {r['detail']}".rstrip())
        if r["fix"] and r["status"] != "ok":
            print(f"  {'':8} {'':<{width}}  fix: {r['fix']}")
    # A draft holds back "Ready." too: until it is reviewed, it is not ground truth.
    missing = sum(1 for r in rows if r["status"] in ("MISSING", "DRAFT"))
    print("\n" + ("Ready." if not missing else
                  f"{missing} thing(s) to fix before everything works; see 'fix:' above."))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

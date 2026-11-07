"""What the local page shows and does, with no web framework in it.

server.py puts routes over these; the tests call them directly. Everything
here reads this copy's own files and runs this copy's own scripts, and nothing
else: the file reads are limited to the folders named below, the only writes
are a digest's boxes, feedback.md's verdicts, the statuses in
profile/applications.yaml and the two key files, and the only commands are the
ones in COMMANDS, with their arguments checked, the git commands in the last
section, which keep the copy current and backed up, and ui/launch.sh, which
starts the page again when Job Search on the Desktop started it.

The page does what a person does between skills: reads a digest and marks it,
finds what was filed under Applications/ and records what came of each
application, runs the checks, shows how far setup has got, and updates the
copy from the template and backs it up. Scoring,
choosing bullets, and writing letters stay in Claude Code, where the skills
are; claude_run.py streams those runs the same way the registry here streams a
script.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import digest_applies  # noqa: E402
import doctor  # noqa: E402
import export_template  # noqa: E402
import tracker  # noqa: E402

DIGESTS = digest_applies.DIGESTS
APPS = digest_applies.APPS

RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# What /api/health calls this page, so a second start can tell it from
# anything else on the port.
APP_NAME = "BS Job Search"
# When this server started: a page tells a server that restarted from the one
# it loaded from by this.
STARTED = time.time()

# The files the Profile tab shows, read-only. contact.local.md is left out: it
# holds nothing the page needs, and it is the one file with contact details.
PROFILE_FILES = [
    ("profile/profile.md", "How a role is judged for you"),
    ("profile/feedback.md", "Your verdicts from past digests"),
    ("profile/clusters.yaml", "What to look for"),
    ("profile/filters.yaml", "Where, how much, and which sources"),
    ("content/master.md", "Every resume fact"),
    ("content/story.md", "Stories for cover letters"),
]

# Files under Applications/ the page will open. Anything else is listed but
# not served, so a stray download there never goes through the page.
VIEWABLE = {".pdf", ".txt", ".tex", ".md"}


# ----------------------------------------------------------------- digests

def digest_path(date: str) -> str:
    if not RE_DATE.match(date):
        raise ValueError(f"not a digest date: {date!r}")
    path = os.path.join(DIGESTS, f"{date}.md")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no digest for {date}")
    return path


def list_digests() -> list[dict]:
    """Newest first, with the counts the page shows beside each date."""
    out = []
    if not os.path.isdir(DIGESTS):
        return out
    for name in sorted(os.listdir(DIGESTS), reverse=True):
        stem, ext = os.path.splitext(name)
        if ext != ".md" or not RE_DATE.match(stem):
            continue
        r = digest_applies.parse(os.path.join(DIGESTS, name))
        out.append({
            "date": stem,
            "entries": r["total_entries"],
            "apply": len(r["apply"]),
            "skip": len(r["skip"]),
            "unmarked": len(r["unmarked"]),
            "conflicts": len(r["conflicts"]) + len(r["letter_only"]),
        })
    return out


def read_digest(date: str) -> dict:
    """digest_applies.parse() plus what it leaves out: the text above the first
    entry, and each entry's own lines (minus the boxes), for the page to render."""
    path = digest_path(date)
    lines = open(path, encoding="utf-8").read().splitlines()
    preamble: list[str] = []
    for line in lines:
        if digest_applies.RE_HEADING.match(line):
            break
        preamble.append(line)
    bodies = {n: [l for l in body if not digest_applies.RE_CHECKBOX.match(l)]
              for n, _, body in digest_applies.entry_blocks(lines)}

    r = digest_applies.parse(path)
    seen: dict[int, dict] = {}
    for key in ("apply", "skip", "conflicts", "letter_only", "unmarked"):
        for e in r[key]:
            seen.setdefault(e["n"], e)
    entries = sorted(seen.values(), key=lambda e: e["n"])
    for e in entries:
        e["body"] = "\n".join(bodies.get(e["n"], [])).strip("\n")
    return {
        "date": date,
        "preamble": "\n".join(preamble).strip("\n"),
        "entries": entries,
        "total_entries": r["total_entries"],
    }


def mark_entry(date: str, n: int, **marks) -> dict:
    """Write one entry's boxes and return the digest's new counts. `expect` and
    `entry` pass through to digest_applies.write_marks, which refuses a change
    made against an out-of-date view with tracker.Conflict."""
    with writing():
        digest_applies.write_marks(digest_path(date), n, **marks)
    return next(d for d in list_digests() if d["date"] == date)


def verdicts_section(date: str) -> dict:
    """The feedback.md section for a digest, and what to settle before it is
    appended. The page appends only when nothing needs settling."""
    text = digest_applies.verdicts(digest_applies.parse(digest_path(date)))
    section, _, settle = text.partition("Settle before appending:")
    return {
        "section": section.rstrip() + "\n",
        "settle": [s.strip() for s in settle.strip().splitlines() if s.strip()],
    }


def append_feedback(date: str) -> str:
    """Append a digest's verdicts to profile/feedback.md. Refuses while anything
    needs settling, and refuses a second copy of the same date."""
    v = verdicts_section(date)
    if v["settle"]:
        raise ValueError("settle these first: " + "; ".join(v["settle"]))
    with writing():
        return _append_feedback(date, v)


def _append_feedback(date: str, v: dict) -> str:
    path = os.path.join(ROOT, "profile", "feedback.md")
    existing = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    heading = v["section"].splitlines()[0]
    if heading in existing:
        raise ValueError(f"feedback.md already has a section for {date}")
    with open(path, "a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write("\n" + v["section"])
    return "profile/feedback.md"


# ------------------------------------------------------------ applications

def _inside(path: str, folder: str) -> bool:
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder + os.sep)


def _files_in(folder: str) -> list[dict]:
    files = []
    for fn in sorted(os.listdir(folder), key=str.lower):
        fp = os.path.join(folder, fn)
        if not os.path.isfile(fp) or fn.startswith("."):
            continue
        files.append({
            "name": fn,
            "viewable": os.path.splitext(fn)[1].lower() in VIEWABLE,
            "size": os.path.getsize(fp),
            "modified": time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(fp))),
        })
    return files


def _roles(company: str, on_disk: list[str], entries: list, index: dict,
           today: dt.date) -> list[dict]:
    """One employer's applications, each as tracker.as_dict() gives it, plus
    whether its files are here and the digest entry it came from. A folder with
    neither a filed role nor an entry gets one row for the employer as a whole."""
    rows = [tracker.as_dict(e, today) for e in entries]
    held = {e.role for e in entries}
    rows += [tracker.as_dict(tracker.Entry(company, role), today)
             for role in on_disk if role not in held]
    if not rows:
        rows = [tracker.as_dict(tracker.Entry(company, ""), today)]
    for r in rows:
        r["filed"] = r["role"] in on_disk
        r["tracked"] = r["role"] in held
        found = index.get((digest_applies.norm_company(company),
                           digest_applies.norm_company(r["role"]))) if r["role"] else None
        r["digest"] = ({k: found[k] for k in ("date", "n", "score")} if found else None)
    return sorted(rows, key=lambda r: (r["role"] != "", r["role"].casefold()))


def list_applications() -> dict:
    """Every folder under Applications/ with its files, and each employer's
    applications with where each stands in profile/applications.yaml.

    A folder whose name starts with `_` is not an employer: the page shows it
    apart, with no status, and its subfolders (resumes sent to people, grouped by
    person) each get a row. An employer the tracker names but this machine has
    no folder for is listed too, with `on_disk` false: Applications/ does not
    sync between machines, and the tracker does."""
    t = tracker.load()
    today = dt.date.today()
    index = digest_applies.digest_index()
    by_company: dict[str, list] = {}
    problems = []
    for e in t.entries:
        if e.company:
            by_company.setdefault(e.company, []).append(e)
        else:
            problems.append(f"an entry with no company: {e.problem}")

    folders = []
    if os.path.isdir(APPS):
        for name in sorted(os.listdir(APPS), key=str.lower):
            folder = os.path.join(APPS, name)
            if not os.path.isdir(folder) or name.startswith("."):
                continue
            employer = not name.startswith("_")
            files = _files_in(folder)
            if employer:
                folders.append({"company": name, "employer": True, "on_disk": True,
                                "files": files,
                                "roles": _roles(name, tracker.roles_on_disk(folder),
                                                by_company.pop(name, []), index, today)})
            elif files:
                folders.append({"company": name, "employer": False, "on_disk": True,
                                "files": files, "roles": []})
            if not employer:
                for sub in sorted(os.listdir(folder), key=str.lower):
                    if os.path.isdir(os.path.join(folder, sub)) and not sub.startswith("."):
                        folders.append({"company": f"{name}/{sub}", "employer": False,
                                        "on_disk": True, "roles": [],
                                        "files": _files_in(os.path.join(folder, sub))})
    for name in sorted(by_company, key=str.lower):
        folders.append({"company": name, "employer": True, "on_disk": False, "files": [],
                        "roles": _roles(name, [], by_company[name], index, today)})
    return {"folders": folders, "file": tracker.TRACKER, "problem": t.problem,
            "problems": problems, "statuses": list(tracker.STATUSES),
            "meaning": tracker.MEANING, "stage": tracker.STAGE, "ended": list(tracker.ENDED),
            "today": today.isoformat()}


def set_application_status(company: str, role: str = "", **change) -> dict:
    """Change where one application stands (tracker.set_status says how) and
    return the listing as it now is. Only an application the tab lists can
    change: one filed under Applications/, or one the tracker already holds."""
    listed = list_applications()
    folder = next((f for f in listed["folders"]
                   if f["employer"] and f["company"] == company), None)
    if folder is None or not any(r["role"] == role for r in folder["roles"]):
        raise ValueError(f"the Applications tab lists no application for "
                         f"{tracker.label(company, role)}")
    with writing():
        tracker.set_status(company, role, allow_new=True, **change)
    return list_applications()


def application_file(company: str, name: str) -> str:
    """The absolute path of one filed document, or an error. Only files directly
    in a company folder (or one level down inside a `_` folder), of a kind the
    page shows."""
    parts = company.split("/") + [name]
    for part in parts:
        if part in ("", ".", "..") or os.sep in part:
            raise ValueError("not a file in Applications/")
    if len(parts) > 2 and not (len(parts) == 3 and parts[0].startswith("_")):
        raise ValueError("not a file in Applications/")
    path = os.path.join(APPS, *parts)
    if not _inside(path, APPS):
        raise ValueError("not a file in Applications/")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no such file under Applications/{company}")
    if os.path.splitext(name)[1].lower() not in VIEWABLE:
        raise ValueError(f"the page does not open {os.path.splitext(name)[1]} files")
    return path


def filed(since: float, until: float | None = None) -> list[dict]:
    """The files written under Applications/ from `since` to `until` (times in
    seconds), newest first, where application_file() opens them: the run view
    lists what a skill run filed. Each names its folder and file as
    list_applications() does."""
    out = []
    if not os.path.isdir(APPS):
        return out
    for company in os.listdir(APPS):
        top = os.path.join(APPS, company)
        if company.startswith(".") or not os.path.isdir(top):
            continue
        folders = [(company, top)]
        if company.startswith("_"):   # one level down, as the page shows them
            folders += [(f"{company}/{s}", os.path.join(top, s)) for s in os.listdir(top)
                        if not s.startswith(".") and os.path.isdir(os.path.join(top, s))]
        for name, folder in folders:
            for fn in os.listdir(folder):
                path = os.path.join(folder, fn)
                if fn.startswith(".") or not os.path.isfile(path):
                    continue
                mtime = os.path.getmtime(path)
                if mtime >= since and (until is None or mtime <= until):
                    out.append({"company": name, "name": fn, "modified": mtime,
                                "viewable": os.path.splitext(fn)[1].lower() in VIEWABLE})
    return sorted(out, key=lambda f: -f["modified"])


def posting_path(company: str, title: str) -> str:
    """The posting filed for one application, Applications/<company>/<title> -
    posting.txt, or an error: what /interview-prep is started for. Only an
    employer's folder has applications."""
    if not company or not title:
        raise ValueError("pick an application: a company and a job title")
    if company.startswith("_"):
        raise ValueError(f"{company} is not an employer's folder")
    return application_file(company, f"{title} - posting.txt")


# ------------------------------------------------------------------ profile

def list_profile_files() -> list[dict]:
    return [{"path": rel, "about": about, "exists": os.path.isfile(os.path.join(ROOT, rel))}
            for rel, about in PROFILE_FILES]


def read_profile_file(rel: str) -> str:
    if rel not in {p for p, _ in PROFILE_FILES}:
        raise ValueError(f"{rel} is not one of the profile files")
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


# ------------------------------------------------------------ the phone's copy

# What a phone keeps for reading while the Mac is away (ui/sw.js): the digests,
# the applications and where each stands, and the profile files, as the page's
# own routes answer them. Nothing else: never keys, contact details, run
# transcripts, or what Setup and Runs show, which need the Mac anyway.
SNAPSHOT_PATH = re.compile(r"^/api/(digests(/\d{4}-\d{2}-\d{2}(/verdicts)?)?|applications|profile(/.+)?)$")


def snapshot() -> dict:
    """Every read the phone keeps, by the route that answers it, with a tag
    that changes when any of them does. ui/build_demo.py bundles the same
    answers for a demo."""
    import hashlib
    answers = {
        "/api/digests": list_digests(),
        "/api/applications": list_applications(),
        "/api/profile": list_profile_files(),
    }
    for d in answers["/api/digests"]:
        answers[f"/api/digests/{d['date']}"] = read_digest(d["date"])
        answers[f"/api/digests/{d['date']}/verdicts"] = verdicts_section(d["date"])
    for p in answers["/api/profile"]:
        if p["exists"]:
            answers[f"/api/profile/{p['path']}"] = read_profile_file(p["path"])
    body = json.dumps(answers, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return {"etag": hashlib.sha256(body.encode("utf-8")).hexdigest()[:24], "answers": answers}


# -------------------------------------------------------------------- setup

# The six files /setup writes, in its order, and whether the scan and the
# resumes need each. story.md is the one they do not: only letters read it.
SETUP_FILES = [
    ("content/contact.local.md", "Your name, email and links", True),
    ("content/master.md", "Every resume fact", True),
    ("content/story.md", "Stories for cover letters", False),
    ("profile/profile.md", "How a role is judged for you", True),
    ("profile/clusters.yaml", "What to look for", True),
    ("profile/filters.yaml", "Where, how much, and which sources", True),
]


# The resume /setup builds from every bullet in master.md, to check it (Step 3e).
TEST_RESUME = "Resume/pdf/editing_cv.pdf"


def setup_state() -> dict:
    """How far setup has got: each file it writes is missing, a draft (written
    by /setup, not yet reviewed), or done. `ready` once every needed file is
    done and no draft is left; until then the page opens on its Setup tab.
    `test_resume` once setup has built one. Fast, because the page asks on
    every load: it reads only for the draft line."""
    files = []
    for rel, about, needed in SETUP_FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            state = "missing"
        else:
            with open(path, encoding="utf-8", errors="replace") as fh:
                state = "draft" if doctor.DRAFT in fh.read() else "done"
        files.append({"path": rel, "about": about, "needed": needed, "state": state})
    ready = all(f["state"] == "done" or (f["state"] == "missing" and not f["needed"])
                for f in files)
    resume = os.path.join(ROOT, TEST_RESUME)
    test = ({"path": TEST_RESUME, "modified": int(os.path.getmtime(resume))}
            if os.path.isfile(resume) else None)
    return {"files": files, "ready": ready, "test_resume": test}


def test_resume() -> str:
    """The test resume's path, for the Setup tab to open."""
    path = os.path.join(ROOT, TEST_RESUME)
    if not os.path.isfile(path):
        raise FileNotFoundError("setup has not built the test resume yet")
    return path


# doctor.py keeps its rows in one list, so two checks at once would mix them.
_checking = threading.Lock()


def setup_checks() -> dict:
    """doctor.py's checks as rows, for the Setup tab, and where each key source
    stands. Claude Code is left out (the tab asks claude_run itself), and so are
    doctor's rows for the keys, which `keys` replaces with a form."""
    with _checking:
        rows = doctor.run_checks(page=False)
    keyed = {f"{label} key" for label, *_ in doctor.KEYS.values()}
    return {"checks": [r for r in rows if r["what"] not in keyed], "keys": key_status(),
            "latex_install": "latex" in COMMANDS}


def _filters() -> dict | None:
    path = os.path.join(ROOT, "profile", "filters.yaml")
    if not os.path.isfile(path):
        return None
    import yaml
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return None


def key_status() -> list[dict]:
    """Each source that needs a key: whether one is saved, and whether
    filters.yaml turns the source on (None until filters.yaml can be read; no
    `sources` block means the company boards only). Never the values."""
    filters = _filters()
    sources = (filters or {}).get("sources")
    out = []
    for name, (label, signup, fields, *_) in doctor.KEYS.items():
        on = None if filters is None else (
            bool(sources.get(name)) if isinstance(sources, dict) else False)
        out.append({"source": name, "label": label, "signup": "https://" + signup,
                    "fields": list(fields), "file": f"sources/{name}.local.yaml",
                    "saved": doctor.key_problem(name) is None, "on": on})
    return out


# A key or an ID as a source issues it: one run of visible characters.
KEY_VALUE = re.compile(r"[^\s\x00-\x1f\x7f]{1,300}")


def save_keys(name: str, values: dict) -> str:
    """Write one source's key file, sources/<name>.local.yaml, from what was
    typed into the Setup tab, and return its path. Only the key lines change,
    so an existing file keeps its comments and other settings; a new one starts
    from the source's example. The values are never returned or logged."""
    if name not in doctor.KEYS:
        raise ValueError(f"no source named {name!r} takes a key")
    label, _, fields, *_ = doctor.KEYS[name]
    if not isinstance(values, dict) or set(values) != set(fields):
        raise ValueError(f"{label} takes {' and '.join(fields)}")
    clean = {}
    for field in fields:
        value = values[field].strip() if isinstance(values[field], str) else ""
        if not KEY_VALUE.fullmatch(value):
            raise ValueError(f"{field} must be filled in, with no spaces or line breaks")
        if value.lower() in doctor.PLACEHOLDERS:
            raise ValueError(f"{field} is still the example's placeholder")
        if field == "email" and not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", value):
            raise ValueError("email must be the address the key was registered under")
        clean[field] = value

    rel = f"sources/{name}.local.yaml"
    path = os.path.join(ROOT, rel)
    text = ""
    for src in (path, os.path.join(ROOT, "sources", f"{name}.example.yaml")):
        if os.path.isfile(src):
            with open(src, encoding="utf-8") as fh:
                text = fh.read()
            break
    for field, value in clean.items():
        line = f"{field}: {json.dumps(value)}"   # a JSON string is a YAML string
        text, n = re.subn(rf"^{field}:.*$", lambda _m: line, text, count=1, flags=re.M)
        if not n:
            text = (text.rstrip("\n") + "\n" if text.strip() else "") + line + "\n"
    import yaml
    back = yaml.safe_load(text) or {}
    if any(back.get(f) != v for f, v in clean.items()):
        raise ValueError(f"{rel} would not read back as typed, so nothing was saved")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)   # an older file, copied by hand, may be readable by all
    return rel


# ------------------------------------------------------------------ the port

def probe_port(port: int, host: str = "127.0.0.1") -> tuple[str, str]:
    """What holds the page's port, before the server tries to take it:
    ("free", ""), ("this", root) when this folder's page already runs there,
    ("another", root) when the page of another copy does, or ("other", "") for
    any other program. A second start then opens the running page instead of
    failing on the port."""
    import socket
    import urllib.request
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex((host, port)) != 0:
            return "free", ""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=2) as r:
            info = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return "other", ""
    if not isinstance(info, dict) or info.get("app") != APP_NAME:
        return "other", ""
    root = str(info.get("root") or "")
    same = bool(root) and os.path.realpath(root) == os.path.realpath(ROOT)
    return ("this" if same else "another"), root


# -------------------------------------------------------------- who may ask

# The names this page answers to. It listens on 127.0.0.1 only, but a browser
# sends the name its page was loaded under: a site that points its own name at
# 127.0.0.1 (DNS rebinding) would otherwise read this page as its own.
LOCAL_NAMES = ("127.0.0.1", "localhost", "[::1]")

def manifest(name: str = "BS Job Search") -> dict:
    """The web app manifest that makes the page an app on a phone's home
    screen: its name under the icon, the icon itself (ui/icon.py), and opening
    full screen. Every path is relative, so a demo in a subfolder works too."""
    return {"name": name, "short_name": "Job Search", "start_url": "./", "scope": "./",
            "display": "standalone", "background_color": "#17120d", "theme_color": "#17120d",
            "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
                      {"src": "icon-512.png", "sizes": "512x512", "type": "image/png",
                       "purpose": "maskable"}]}


# Phone access (ui/phone.py): this Mac's Tailscale address and the account it
# answers, per machine and never tracked.
REMOTE = os.path.join(ROOT, "data", "ui-remote.json")
_remote: dict = {"mtime": None, "value": None}


def remote_access() -> dict | None:
    """{host, login, port} once ui/phone.py has set phone access up, else None.
    Read again whenever the file changes, so turning it on or off needs no
    restart."""
    try:
        mtime = os.path.getmtime(REMOTE)
    except OSError:
        return None
    if _remote["mtime"] != mtime:
        try:
            with open(REMOTE, encoding="utf-8") as fh:
                value = json.load(fh)
            ok = isinstance(value, dict) and value.get("host") and value.get("login")
            _remote.update(mtime=mtime, value=value if ok else None)
        except (OSError, ValueError):
            _remote.update(mtime=mtime, value=None)
    return _remote["value"]


def save_remote_access(host: str | None, login: str | None = None, port: int = 8765) -> None:
    """Record phone access, or with no host, remove it."""
    if not host:
        try:
            os.remove(REMOTE)
        except FileNotFoundError:
            pass
        return
    os.makedirs(os.path.dirname(REMOTE), exist_ok=True)
    fd = os.open(REMOTE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"host": host.lower(), "login": login, "port": port}, fh, indent=1)


def refusal(host: str | None, origin: str | None, login: str | None = None,
            forwarded: bool = False) -> str | None:
    """Why the page will not answer a request, or None when it will.

    It answers only requests addressed to this machine by name, which stops DNS
    rebinding. A request that carries an Origin must also come from the page
    itself. Browsers send one with every POST and PUT, so another site's form or
    script cannot start a run or answer a card, although the browser lets it
    send the request. curl and scripts send none, and are answered.

    A phone's request arrives forwarded by `tailscale serve` (ui/phone.py),
    which names the Tailscale account asking (`login`, from its
    Tailscale-User-Login header, which serve sets and strips from what it
    forwards). That is answered only once phone access is set up, only for the
    account recorded then, and only at this Mac's tailnet address, whose own
    pages are the one other origin allowed."""
    host = (host or "").strip().lower()
    name = host[:host.find("]") + 1] if host.startswith("[") else host.split(":")[0]
    if forwarded or login is not None:
        remote = remote_access()
        if not remote:
            return "This page answers this Mac alone: phone access is not set up here."
        if (login or "").strip().lower() != str(remote["login"]).lower():
            return f"This page answers a phone only through Tailscale, signed in as {remote['login']}."
        if name not in LOCAL_NAMES and name != remote["host"]:
            return f"This page answers only at {remote['host']}, not {host or 'no host'}."
        if origin is not None and origin.strip().lower() not in (f"https://{remote['host']}",
                                                                 f"http://{host}"):
            return "A page on another site cannot use this one."
        return None
    if name not in LOCAL_NAMES:
        return f"This page answers only at 127.0.0.1 or localhost, not {host or 'no host'}."
    if origin is not None and origin.strip().lower() != f"http://{host}":
        return "A page on another site cannot use this one."
    return None


# --------------------------------------------------------------------- runs

def _script(name: str, *args: str) -> list[str]:
    return [sys.executable, "-u", os.path.join(SCRIPTS, f"{name}.py"), *args]


def _date_arg(params: dict) -> str:
    date = str(params.get("date") or "")
    digest_path(date)   # raises on a bad or missing date
    return date


# name -> (label, what it does, argv from the page's parameters). The page's
# buttons come from this list, so adding a command here is the whole job.
COMMANDS: dict[str, tuple[str, str, object]] = {
    "doctor": ("Doctor", "Check the machine, the profile, and the keys",
               lambda p: _script("doctor")),
    "applies": ("What is marked", "The roles marked apply, and where each files",
                lambda p: _script("digest_applies", "--date", _date_arg(p))),
    "fetch": ("Fetch postings", "Save every apply's posting beside where its resume goes",
              lambda p: _script("digest_applies", "--date", _date_arg(p), "--fetch")),
    "outcomes": ("Outcomes", "What came of each application, as the next scan reads it",
                 lambda p: _script("digest_applies", "--outcomes")),
}
if platform.system() != "Windows":   # where Windows has MiKTeX instead
    COMMANDS["latex"] = ("Install LaTeX",
                         "TinyTeX and the packages the templates use, in your home folder, "
                         "with no password", lambda p: _script("install_latex"))


class Run:
    """One command's output as it arrives. Readers wait on `changed`."""

    def __init__(self, name: str, argv: list[str]):
        self.id = uuid.uuid4().hex[:12]
        self.name = name
        self.argv = argv
        self.lines: list[str] = []
        self.status = "running"
        self.returncode: int | None = None
        self.started = time.time()
        self.changed = threading.Condition()

    def _append(self, line: str) -> None:
        with self.changed:
            self.lines.append(line)
            self.changed.notify_all()

    def _finish(self, code: int | None, status: str) -> None:
        with self.changed:
            self.returncode = code
            self.status = status
            self.changed.notify_all()

    def run(self) -> None:
        try:
            proc = subprocess.Popen(self.argv, cwd=ROOT, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace")
        except OSError as exc:
            self._append(f"could not start: {exc}")
            self._finish(None, "failed")
            return
        assert proc.stdout is not None
        for line in proc.stdout:
            self._append(line.rstrip("\n"))
        code = proc.wait()
        self._finish(code, "done" if code == 0 else "failed")

    def follow(self, start: int = 0):
        """Yield (index, line) from `start`, then None once the run has ended."""
        i = start
        while True:
            with self.changed:
                while i >= len(self.lines) and self.status == "running":
                    self.changed.wait(timeout=0.5)
                if i < len(self.lines):
                    line = self.lines[i]
                elif self.status != "running":
                    yield None
                    return
                else:
                    continue
            yield i, line
            i += 1

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": "script", "status": self.status,
                "returncode": self.returncode, "started": self.started,
                "lines": len(self.lines)}


# What a run is doing that nothing should cut off. "idle", a skill whose turn
# has ended, is not among them.
WORKING = ("starting", "running", "waiting")


class Runs:
    """The runs this server has started, newest last: scripts (Run) and skills
    (claude_run.ClaudeRun), which share id, name, status, follow() and summary()."""

    def __init__(self) -> None:
        self._runs: dict = {}
        self._lock = threading.Lock()

    def add(self, run) -> None:
        with self._lock:
            self._runs[run.id] = run

    def active_claude(self):
        """The skill run still going, if any. Skills run one at a time: they
        share data/seen.sqlite, the digests and Applications/."""
        with self._lock:
            for r in self._runs.values():
                if r.summary().get("kind") == "claude" and r.status in (
                        "starting", "running", "waiting", "idle"):
                    return r
        return None

    def start_skill(self, name: str, params: dict | None = None,
                    resume: str | None = None, prompt: str | None = None):
        import claude_run   # here, not at the top: it needs the Agent SDK only when a run starts
        active = self.active_claude()
        if active is not None and active.status in WORKING:
            raise RuntimeError(f"{active.name} is still {active.status}; end it first")
        if active is not None:   # idle: its turn is over, and Past runs can resume it
            active.stop()
        run = claude_run.start_skill(name, params, resume=resume, prompt=prompt)
        self.add(run)
        return run

    def commands(self) -> list[dict]:
        return [{"name": k, "label": v[0], "about": v[1],
                 "needs_date": k in ("applies", "fetch")} for k, v in COMMANDS.items()]

    def start(self, name: str, params: dict | None = None) -> Run:
        if name not in COMMANDS:
            raise ValueError(f"no command named {name!r}")
        argv = COMMANDS[name][2](params or {})
        run = Run(name, argv)
        self.add(run)
        threading.Thread(target=run.run, name=f"run-{run.id}", daemon=True).start()
        return run

    def get(self, run_id: str) -> Run:
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(run_id)
            return self._runs[run_id]

    def list(self) -> list[dict]:
        with self._lock:
            return [r.summary() for r in self._runs.values()]

    def working(self) -> bool:
        """Whether any run, script or skill, is working: starting, running, or
        waiting on a card. A skill whose turn has ended and waits for a reply is
        idle, not working: it holds nothing open, and Past runs picks its
        conversation up again after it has been ended."""
        with self._lock:
            return any(r.status in WORKING for r in self._runs.values())


# ----------------------------------------------------------------- restart
# A page started by ui/launch.sh (Job Search on the Desktop) has no window to
# close and start again, so it restarts itself: the launcher, started on its
# own, waits for this server to stop, then starts it again on the same port,
# through `uv run`, which installs whatever an update added.

RESTART_BY_HAND = ("This page was started in a terminal, so it restarts there: stop it with "
                   "Ctrl+C in that window (or close the window), then start it the same way again.")


def launcher() -> str | None:
    """ui/launch.sh, when that is what started this server."""
    path = os.environ.get("BS_LAUNCHER")
    return path if path and os.path.isfile(path) else None


def by_launchd() -> bool:
    """Whether launchd started this server, at a request (ui/phone.py)."""
    return os.environ.get("BS_LAUNCHD") == "1"


def restart(port: int, runs: "Runs", popen=subprocess.Popen) -> None:
    """Start the launcher that will start this page again once it has stopped.
    The caller stops the server after answering. Under launchd there is nothing
    to start: the next request does it, through the launcher, which installs
    what an update added first."""
    path = launcher()
    if not path and not by_launchd():
        raise Stop(RESTART_BY_HAND)
    if runs.working():
        raise Stop("A run is still working in the Runs tab. Let it finish, or stop it, then "
                   "restart: a skill's conversation can be picked up again from Past runs.")
    if by_launchd():
        return
    popen(["/bin/sh", path, "--restart", str(port)], cwd=ROOT, stdin=subprocess.DEVNULL,
          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def launchd_sockets(name: str = "Listeners") -> list:
    """The listening sockets launchd holds for this page and hands to the
    process it started (macOS's launch_activate_socket). That process must be
    the one launchd started, which is why ui/launch.sh --launchd ends in exec."""
    import ctypes
    import socket
    if sys.platform != "darwin":
        raise RuntimeError("launchd hands out sockets on macOS only")
    lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    fds = ctypes.POINTER(ctypes.c_int)()
    count = ctypes.c_size_t(0)
    err = lib.launch_activate_socket(name.encode(), ctypes.byref(fds), ctypes.byref(count))
    if err:
        raise OSError(err, f"launchd has no {name} socket for this process: {os.strerror(err)}")
    socks = [socket.socket(fileno=fds[i]) for i in range(count.value)]
    lib.free(fds)
    return socks


class Idle:
    """How long since the page last asked the server for anything. An open
    page asks at least once a minute (app.js), so a long silence means no tab
    has it open, and `server.py --idle-exit` stops the server then."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._last = clock()

    def touch(self) -> None:
        self._last = self._clock()

    def seconds(self) -> float:
        return self._clock() - self._last

    def should_exit(self, minutes: float, runs: "Runs") -> bool:
        """True once nothing has asked for `minutes` and no run is working: a
        working run keeps the server up, since stopping it would cut the run
        off. An idle conversation does not, or one finished skill would keep
        the page up for good; Past runs picks it up again."""
        return minutes > 0 and self.seconds() >= minutes * 60 and not runs.working()


# ------------------------------------------------------- updates and backup
# A copy is a git repository laid out one of four ways, and the page keeps it
# current and backed up, so nobody has to run git:
#
#   clone      Cloned from the template, which is `origin`. An update brings the
#              template's new commits in. Nothing is pushed anywhere.
#   backup     Pushed to a repository of the user's own (`origin`), with the
#              template as a second remote, `template`. An update merges the
#              template in, then pushes; Back up commits the user's own files,
#              then pushes.
#   unrelated  Made with GitHub's "Use this template", so it shares no history
#              with the template. Its first update takes the template's files
#              one by one, as a merge would, and joins the two histories, so it
#              is a clone or a backup from then on.
#   unlinked   No remote for the template, until link_template() adds one.
#
# Nothing here forces, rebases, resets, cleans, or stashes. An update that would
# write over work not committed here, or that conflicts with a change made here,
# stops before anything changes (a merge that conflicts is aborted). Nothing is
# pushed to a repository anyone can read.

TEMPLATE_URL = "https://github.com/BatteyS/BS-Job-Search.git"
TEMPLATE_BRANCH = "main"
TEMPLATE_REMOTE = "template"
BACKUP_HELP = "https://github.com/BatteyS/BS-Job-Search#backing-up-and-a-second-machine"

# What Back up commits: the folders a person's own work is in. The template's
# files there (the examples) stay out, and so does anything named .local.,
# which holds contact details or keys, and is gitignored besides.
BACKUP_FOLDERS = ("profile", "content", "digests", "sources")

# Files whose change the running page cannot pick up: its packages and its
# Python. A change to one of these, or to Python the page loads, needs a restart.
RESTART_FILES = {"pyproject.toml", "uv.lock", ".python-version"}

# How the template labels each export, as its commit's subject.
RE_LABEL = re.compile(r"BS-Job-Search-(v\d+(?:\.\d+)*)")

# Hosts that answer a stranger over https, so a backup there can be checked
# for being public even when this copy reaches it over ssh.
PUBLIC_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org")

ABOUT = {
    "clone": "Cloned from the template, so updates come straight from it. It is not backed "
             "up anywhere else.",
    "backup": "Backed up to a repository of your own, with the template linked for updates.",
    "unrelated": "Made from the template with GitHub's Use this template, so it shares no "
                 "history with it yet. Its first update takes the template's new files and "
                 "joins the two.",
    "unlinked": "Not linked to the template, so this copy gets no updates from it.",
}
NOT_A_REPO = ("This folder is not a git repository, so the page cannot update it or back it "
              "up. A copy made with git clone can be: see the README's Get started.")
NO_BACKUP = ("This copy is only on this machine: it has no repository of its own to back up "
             "to. The README's Backing up, and a second machine, says how to make one.")
PUBLIC = ("Anyone can read {url}, so the page will not back up to it: your profile and "
          "resume facts would be public. Make the repository private (on GitHub, at the "
          "bottom of its Settings), then back up again.")
NEED_NAME = ("Git labels each change in this copy's history with a name and an email, and "
             "has neither yet. Give them below, then try again.")


class Stop(Exception):
    """Why an update or a backup did not go ahead, in plain words. Nothing has
    changed when one is raised."""


_git_lock = threading.Lock()                    # one fetch, update or backup at a time
WRITE_WAIT = 5.0                                # seconds a page write waits for one


@contextlib.contextmanager
def writing():
    """The page's own writes to tracked files (marks, statuses, verdicts) share
    the git lock, so none lands in the middle of an update's merge or a backup's
    commit. A write waits a few seconds for one to finish, then says so."""
    if not _git_lock.acquire(timeout=WRITE_WAIT):
        raise Stop("An update or a backup is changing this copy's files. "
                   "Try again once it has finished.")
    try:
        yield
    finally:
        _git_lock.release()


def git_busy() -> bool:
    """Whether a fetch, update or backup is running: /api/health says, so a
    phone sending changes can wait for it."""
    return _git_lock.locked()
_checked: dict = {"at": None, "error": None}    # the last fetch, for the page to show
_started: dict = {"head": None}                 # the commit the running page started on
_private: set = set()                           # addresses a check found private


def _git(*args: str, input: str | None = None, timeout: int = 60,
         env: dict | None = None) -> subprocess.CompletedProcess:
    """Run git in this copy. It never waits on a person: no terminal (a password
    prompt would sit in the page's own window, where nobody is looking), no
    askpass, no editor. Its messages are in English and its paths literal, and
    nobody's color or log settings change what it prints."""
    run_env = {k: v for k, v in os.environ.items()
               if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    run_env.update(GIT_TERMINAL_PROMPT="0", GIT_EDITOR="true", GIT_MERGE_AUTOEDIT="no",
                   GIT_LITERAL_PATHSPECS="1", GIT_OPTIONAL_LOCKS="0", LC_ALL="C", **(env or {}))
    io = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
    argv = ["git", "-c", "color.ui=never", "-c", "log.showSignature=false",
            "-c", "log.showRoot=true", *args]
    try:
        return subprocess.run(argv, cwd=ROOT, env=run_env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              start_new_session=True, **io)
    except FileNotFoundError:
        raise Stop("git is not installed on this machine, so the page cannot update this "
                   "copy or back it up.")
    except subprocess.TimeoutExpired:
        raise Stop(f"git took more than {timeout} seconds, so the page stopped it. "
                   "Try again in a while.")


def _said(r: subprocess.CompletedProcess) -> str:
    """What git said about a failure, short."""
    lines = [l.strip() for l in (r.stderr + "\n" + r.stdout).splitlines() if l.strip()]
    return " ".join(lines[:3])[:400] or f"exit code {r.returncode}"


def _ok(*args: str, **kw) -> str:
    r = _git(*args, **kw)
    if r.returncode != 0:
        raise Stop(f"git {args[0]} failed: {_said(r)}")
    return r.stdout


def _z(text: str) -> list[str]:
    return [p for p in text.split("\0") if p]


def _rev(ref: str) -> str | None:
    r = _git("rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def _count(*revs: str) -> int:
    return int(_ok("rev-list", "--count", *revs).strip() or 0)


def _names(*revs: str, only: str = "") -> list[str]:
    """The paths that differ between two commits, or across `a...b`; `only`
    narrows them as --diff-filter does (A, added)."""
    return _z(_ok("diff", "--name-only", "--no-renames", "-z",
                  *([f"--diff-filter={only}"] if only else []), *revs))


def _branch() -> str | None:
    return _git("symbolic-ref", "-q", "--short", "HEAD").stdout.strip() or None


def _remotes() -> dict[str, str]:
    """Each remote's name and fetch address."""
    out = {}
    for item in _z(_git("config", "-z", "--get-regexp", r"^remote\..*\.url$").stdout):
        key, _, url = item.partition("\n")
        out[key[len("remote."):-len(".url")]] = url
    return out


def _changes() -> list[tuple[str, str]]:
    """(status, path) for each file with work not committed; `??` is a file git
    does not track yet."""
    out = _ok("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
    return [(e[:2], e[3:]) for e in _z(out) if len(e) > 3]


def _tree(ref: str) -> dict[str, tuple[str, str]]:
    """path -> (mode, blob) for each file in a commit."""
    out = {}
    for entry in _z(_ok("ls-tree", "-r", "-z", "--full-tree", ref)):
        meta, _, path = entry.partition("\t")
        mode, kind, obj = meta.split()
        if kind == "blob":
            out[path] = (mode, obj)
    return out


def _identity() -> bool:
    """Whether git has a name and email to label a commit with. One it would
    make up from this machine's user and host names does not count."""
    return all(_git("config", "--get", f"user.{k}").stdout.strip()
               or os.environ.get(f"GIT_AUTHOR_{k.upper()}") for k in ("name", "email"))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _files(paths: list[str]) -> str:
    shown = paths if len(paths) <= 6 else paths[:5]
    more = f" and {len(paths) - 5} more" if len(paths) > 6 else ""
    if more or len(shown) == 1:
        return ", ".join(shown) + more
    return ", ".join(shown[:-1]) + " and " + shown[-1]


# ------------------------------------------------- where a remote points

def _split_url(url: str) -> tuple[str, str] | None:
    """(host, path) of a network address, without user, password, port or .git;
    None for a folder on disk."""
    u = url.strip()
    if "://" in u:
        scheme, rest = u.split("://", 1)
        if scheme.lower() == "file":
            return None
        hostpart, _, path = rest.partition("/")
        host = hostpart.rsplit("@", 1)[-1].split(":")[0]
    else:
        m = re.match(r"^(?:[^@/]+@)?([\w.-]{2,}):(?!//)(.+)$", u)   # git@github.com:owner/repo
        if not m or os.path.exists(u):
            return None
        host, path = m.groups()
    path = path.strip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    return host, path


def _repo_key(url: str) -> str:
    """One spelling for a repository however git was given it, so the template
    is known by https or ssh, with or without .git or a token, and a folder on
    disk by its real path."""
    split = _split_url(url)
    if split is None:
        u = url.strip()
        if u.lower().startswith("file://"):
            u = u[len("file://"):]
        return os.path.normcase(os.path.realpath(u))
    return f"{split[0].lower()}/{split[1].lower()}"


def _shown(url: str) -> str:
    """A remote's address as the page shows it: never with a password or token."""
    split = _split_url(url)
    return f"{split[0]}/{split[1]}" if split else url


def _readable_by_anyone(url: str) -> bool:
    """Whether anyone can read the repository at `url` without signing in. It
    asks as a stranger would, over https with git's credential helpers off, so
    only an address on a network is asked about, and one found private is not
    asked about again."""
    split = _split_url(url)
    if split is None:
        return False
    u = url.strip()
    if re.match(r"^https?://", u, re.I):
        address = re.sub(r"^(https?://)[^/@]*@", r"\1", u)
    elif split[0].lower() in PUBLIC_HOSTS:
        address = f"https://{split[0]}/{split[1]}.git"
    else:
        return False                    # an ssh host of its own: no stranger's way in
    if address in _private:
        return False
    r = _git("-c", "credential.helper=", "-c", "core.askPass=", "ls-remote", "--quiet",
             address, "HEAD", timeout=30, env={"GIT_ASKPASS": "", "SSH_ASKPASS": ""})
    if r.returncode == 0:
        return True
    _private.add(address)
    return False


def _tref(remote: str) -> str:
    return f"refs/remotes/{remote}/{TEMPLATE_BRANCH}"


def _layout(remotes: dict[str, str]) -> dict:
    """This copy's layout (see above), which remote is the template, and the
    user's own remote, if it has one."""
    key = _repo_key(TEMPLATE_URL)
    origin = remotes.get("origin")
    if origin is not None and _repo_key(origin) == key:
        return {"layout": "clone", "template": "origin", "own": None}
    own = "origin" if origin is not None else None
    name = next((n for n in sorted(remotes, key=lambda n: (n != TEMPLATE_REMOTE, n))
                 if _repo_key(remotes[n]) == key), None)
    if name is None:
        return {"layout": "unlinked", "template": None, "own": own}
    ref = _tref(name)
    if _rev(ref) and _git("merge-base", "HEAD", ref).returncode == 1:
        return {"layout": "unrelated", "template": name, "own": own}
    return {"layout": "backup" if own else "clone", "template": name, "own": own}


# ----------------------------------------------------------- where it stands

def remember_start() -> None:
    """Note the commit the running page's code came from. server.py calls this
    as the page starts, so copy_status() can say when an update has changed
    code the page has loaded since, and the page must be started again."""
    if os.path.exists(os.path.join(ROOT, ".git")):
        try:
            _started["head"] = _rev("HEAD")
        except Stop:
            pass


def _needs_restart(paths: list[str]) -> bool:
    """Whether a change to these files reaches code the page cannot reload: its
    packages, its Python, its own code (loaded at start, or by its first skill
    run), or a script it has imported."""
    if any(p in RESTART_FILES or (p.startswith("ui/") and p.endswith(".py")) for p in paths):
        return True
    scripts = {os.path.realpath(os.path.join(ROOT, p)) for p in paths if p.endswith(".py")}
    return bool(scripts) and any(
        os.path.realpath(m.__file__) in scripts
        for m in list(sys.modules.values()) if getattr(m, "__file__", None))


def _restart_needed(head: str) -> bool:
    start = _started["head"]
    if not start or start == head:
        return False
    try:
        return _needs_restart(_names(start, head))
    except Stop:
        return False


def copy_status() -> dict:
    """Where this copy stands: its layout, how far behind the template it is as
    of the last check, which files an update would write that hold work not
    committed here, and what is not backed up. It reads, and changes nothing:
    check_copy() fetches first. Paths are from the copy's root."""
    out = {"layout": "none", "about": NOT_A_REPO, "branch": None, "identity": False,
           "dirty": [], "template": None, "backup": None, "restart": False,
           "checked": _checked["at"], "error": _checked["error"],
           "busy": _git_lock.locked(), "help": BACKUP_HELP}
    if not os.path.exists(os.path.join(ROOT, ".git")):
        return out
    try:
        out.update(_status())
    except Stop as exc:
        out["about"] = str(exc)
    return out


def _status() -> dict:
    head = _rev("HEAD")
    if head is None:
        return {"about": "This copy has no commits yet, so there is nothing to update."}
    remotes = _remotes()
    lay = _layout(remotes)
    entries = _changes()
    busy = {p for _, p in entries}
    branch = _branch()
    s = {"layout": lay["layout"], "about": ABOUT[lay["layout"]], "branch": branch,
         "identity": _identity(), "dirty": sorted({p for xy, p in entries if xy != "??"}),
         "restart": _restart_needed(head)}
    if branch is None:
        s["about"] += (" It is not on a branch right now (git calls this a detached HEAD), so "
                       "the page leaves it alone.")
    if lay["template"]:
        s["template"] = _template_status(remotes, lay, busy)
    s["backup"] = _backup_status(remotes, lay, branch, entries, busy)
    return s


def _label(ref: str) -> str | None:
    m = RE_LABEL.fullmatch(_ok("log", "-1", "--format=%s", ref).strip())
    return m.group(1) if m else None


# --------------------------------------------------------------- version

RE_MERGED_PR = re.compile(r"Merge pull request #(\d+)\b")
_version: dict = {"head": "", "value": None}


def version() -> dict:
    """Which version of the page this copy runs, for its title and header.

    `label` is the template export it is at, "v1.55", from the nearest commit
    whose subject is an export's label, with "+3" when it has three commits
    since. A copy with no export in its history (the private repository the
    exports are made from) is labeled by the latest pull request merged into
    it, "#59", the number its next export would take. `commit` and `date` are
    HEAD's, and `changed` says whether tracked code differs from it. All empty
    in a folder that is not a git repository, such as a demo. Kept per HEAD,
    so it is git's work once per commit."""
    empty = {"label": "", "commit": "", "date": "", "changed": False}
    try:
        head = _rev("HEAD")
    except Stop:
        return empty
    if not head:
        return empty
    changed = bool(_git("status", "--porcelain", "--untracked-files=no", "--", "ui", "scripts")
                   .stdout.strip())
    if _version["head"] == head and _version["value"]:
        return {**_version["value"], "changed": changed}
    label = ""
    r = _git("log", "-1", "--format=%H%x00%s", "-E",
             r"--grep=^BS-Job-Search-v[0-9]+(\.[0-9]+)*$", "HEAD")
    if r.returncode == 0 and r.stdout.strip():
        sha, subject = r.stdout.strip().split("\x00", 1)
        m = RE_LABEL.fullmatch(subject.strip())
        if m:
            since = _count(f"{sha}..HEAD")
            label = m.group(1) + (f"+{since}" if since else "")
    if not label:
        r = _git("log", "-1", "--format=%s", "-E", r"--grep=^Merge pull request #[0-9]+", "HEAD")
        m = RE_MERGED_PR.match(r.stdout.strip()) if r.returncode == 0 else None
        if m:
            label = f"#{m.group(1)}"
    date = _git("log", "-1", "--format=%cs", "HEAD").stdout.strip()
    value = {"label": label, "commit": head[:7], "date": date}
    _version.update(head=head, value=value)
    return {**value, "changed": changed}


def version_text(v: dict | None = None) -> str:
    """The version as the page shows it: "v1.55 · 96cb983", with "edited"
    when tracked code differs from that commit. "" outside git."""
    v = v if v is not None else version()
    parts = [p for p in (v["label"], v["commit"]) if p]
    return " · ".join(parts) + (" · edited" if v["changed"] and parts else "")


def _notes(rev: str, n: int = 20) -> list[dict]:
    """The template's release notes: each export's label, and what it says
    changed and why."""
    out = []
    for rec in _ok("log", f"--max-count={n}", "--format=%s%x1f%b%x1e", rev).split("\x1e"):
        subject, _, body = rec.strip("\n").partition("\x1f")
        if subject.strip():
            out.append({"subject": subject.strip(), "body": body.strip()[:3000]})
    return out


def _template_status(remotes: dict, lay: dict, busy: set) -> dict:
    name = lay["template"]
    ref = _tref(name)
    t = {"remote": name, "url": _shown(remotes[name]), "behind": None, "unit": "updates",
         "version": None, "notes": [], "blocked": [], "conflicts": []}
    if not _rev(ref):
        return t                                     # not fetched yet: a check will say
    t["version"] = _label(ref)
    if lay["layout"] == "unrelated":
        plan = _file_plan(ref)
        n = len(plan["take"]) + len(plan["remove"]) + len(plan["conflicts"])
        t.update(behind=n, unit="files", conflicts=plan["conflicts"],
                 blocked=_plan_clash(plan, busy), notes=_notes(ref, 1) if n else [])
    else:
        t.update(behind=_count(f"HEAD..{ref}"), notes=_notes(f"HEAD..{ref}"),
                 blocked=_clash(ref, busy))
    return t


def _backed_up(path: str) -> bool:
    """Whether Back up commits this path: one of the user's own files."""
    return (path.split("/", 1)[0] in BACKUP_FOLDERS
            and ".local." not in path.rsplit("/", 1)[-1]
            and not export_template.is_engine(path))


def _backup_status(remotes: dict, lay: dict, branch: str | None,
                   entries: list, busy: set) -> dict:
    """What is not backed up: the user's files with work not committed, and
    commits not pushed, to `origin`, or for a copy with no repository of its
    own, to anywhere at all. Also what was backed up from another machine and
    has not been brought in here."""
    own = lay["own"]
    b = {"remote": own, "url": _shown(remotes[own]) if own else None,
         "changes": sorted({p for _, p in entries if _backed_up(p)}),
         "other": sorted({p for xy, p in entries if xy != "??" and not _backed_up(p)}),
         "unpushed": _count("HEAD", "--not", f"--remotes={own}" if own else "--remotes"),
         "behind": 0, "blocked": []}
    oref = f"refs/remotes/{own}/{branch}" if own and branch else None
    if oref and _rev(oref):
        b["behind"] = _count(f"HEAD..{oref}")
        if b["behind"]:
            b["blocked"] = _clash(oref, busy)
    return b


def _clash(ref: str, busy: set) -> list[str]:
    """The files bringing in `ref` would write that hold work not committed
    here: changed or untracked, or, for a file it adds, anything already there."""
    added = _names(f"HEAD...{ref}", only="A")
    return sorted((set(_names(f"HEAD...{ref}")) & busy)
                  | {p for p in added if os.path.lexists(os.path.join(ROOT, p))})


# -------------------------------------------- a copy with no shared history

def _template_history(ref: str, ours: dict) -> tuple[dict, dict]:
    """The template's files at the commit of its history most like `ours`, and
    every blob the template has ever had at each path, from one pass over that
    history, oldest first."""
    out = _ok("log", "--reverse", "--first-parent", "--raw", "--no-renames", "--no-abbrev",
              "-z", "--format=%x01", ref)
    tree: dict = {}
    shipped: dict = {}
    best: dict = {}
    best_score = 0

    def weigh() -> None:
        nonlocal best, best_score
        score = sum(1 for p, (_, blob) in tree.items() if ours.get(p, ("", ""))[1] == blob)
        if score and score >= best_score:            # a tie goes to the later commit
            best, best_score = dict(tree), score

    tokens = out.split("\0")
    i, started = 0, False
    while i < len(tokens):
        tok = tokens[i].lstrip("\n")
        if tok.startswith("\x01"):
            if started:
                weigh()
            started = True
        elif tok.startswith(":") and i + 1 < len(tokens):
            _, new_mode, old_blob, new_blob, status = tok[1:].split()[:5]
            path = tokens[i + 1]
            for blob in (old_blob, new_blob):
                if blob.strip("0"):
                    shipped.setdefault(path, set()).add(blob)
            if status.startswith("D"):
                tree.pop(path, None)
            else:
                tree[path] = (new_mode, new_blob)
            i += 2
            continue
        i += 1
    if started:
        weigh()
    return best, shipped


def _file_plan(ref: str) -> dict:
    """What updating a copy that shares no history with the template takes from
    `ref`, file by file, as a merge would. A file this copy has not changed (it
    holds a version the template shipped, or the version it started from) gets
    the template's new one, or goes if the template dropped it. A file the
    template has not changed since keeps this copy's version, so the user's own
    files and changes stay. A file both changed is a conflict. "Since" is the
    template commit most like this copy."""
    ours, theirs = _tree("HEAD"), _tree(ref)
    base, shipped = _template_history(ref, ours)
    take, remove, conflicts = [], [], []
    for p in sorted(set(ours) | set(theirs) | set(base)):
        o, t, b = (x.get(p, (None, None)) for x in (ours, theirs, base))
        if o[1] == t[1]:
            if t[1] is not None and o[0] != t[0]:
                take.append(p)                       # the same file, but not executable here
            continue
        if o[1] is None or o[1] == b[1] or o[1] in shipped.get(p, ()):
            (take if t[1] is not None else remove).append(p)
        elif t[1] != b[1]:
            conflicts.append(p)
    return {"take": take, "remove": remove, "conflicts": conflicts,
            "ours": ours, "theirs": theirs}


def _plan_clash(plan: dict, busy: set) -> list[str]:
    paths = set(plan["take"]) | set(plan["remove"])
    new = [p for p in plan["take"] if p not in plan["ours"]]
    return sorted((paths & busy) | {p for p in new if os.path.lexists(os.path.join(ROOT, p))})


# ------------------------------------------------------------- what it does

@contextlib.contextmanager
def _exclusive(runs=None):
    """One fetch, update or backup at a time, and none while a skill is working,
    so nothing changes files under it."""
    active = runs.active_claude() if runs is not None else None
    if active is not None and active.status in ("starting", "running", "waiting"):
        raise Stop(f"{active.name} is {active.status}. Wait for it to finish, so nothing "
                   "changes files under it.")
    if not _git_lock.acquire(blocking=False):
        raise Stop("An update or a backup is already running. Wait for it to finish.")
    try:
        yield
    finally:
        _git_lock.release()


def _ready() -> tuple[dict, dict, str]:
    """The remotes, layout and branch of a copy the page may change, or Stop."""
    if not os.path.exists(os.path.join(ROOT, ".git")):
        raise Stop(NOT_A_REPO)
    if _rev("HEAD") is None:
        raise Stop("This copy has no commits yet, so there is nothing to update.")
    branch = _branch()
    if branch is None:
        raise Stop("This copy is not on a branch right now (git calls this a detached HEAD), "
                   "so the page leaves it alone.")
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if _rev(name):
            raise Stop("git is partway through a merge here, started outside the page. Finish "
                       "or abort it first: the page will not touch it.")
    for name in ("rebase-merge", "rebase-apply", "index.lock"):
        path = _ok("rev-parse", "--git-path", name).strip()
        if os.path.exists(path if os.path.isabs(path) else os.path.join(ROOT, path)):
            raise Stop("Another git command is running in this copy, or one stopped partway "
                       "(a rebase, or a lock it left). Let it finish, or finish it, first.")
    remotes = _remotes()
    return remotes, _layout(remotes), branch


def _need_identity() -> None:
    if not _identity():
        raise Stop(NEED_NAME)


def _network_problem(r: subprocess.CompletedProcess, where: str) -> str:
    """A fetch or push that failed, in plain words. `where` is what it tried
    to reach: "the template", "your backup"."""
    low = (r.stderr + "\n" + r.stdout).lower()
    where_ = where[:1].upper() + where[1:]
    if "rejected" in low:
        if "fetch first" in low or "non-fast-forward" in low:
            return f"{where_} changed while this ran. Try again."
        return f"{where_} refused the push: {_said(r)}"
    if any(s in low for s in ("could not resolve", "network is unreachable", "timed out",
                              "connection refused", "failed to connect", "no route to host",
                              "connection reset")):
        return f"Could not reach {where}: check the internet connection, then try again."
    if any(s in low for s in ("authentication", "could not read username", "permission denied",
                              "terminal prompts disabled", "error: 401", "error: 403",
                              "repository not found")):
        return (f"{where_} did not let this machine in. Sign in to GitHub on this machine "
                "(in a terminal, gh auth login), then try again.")
    return f"git could not reach {where}: {_said(r)}"


def _fetch_template(remote: str) -> None:
    """The template's main branch only: its gh-pages branch is the demos."""
    r = _git("fetch", "--quiet", "--no-tags", remote,
             f"+refs/heads/{TEMPLATE_BRANCH}:{_tref(remote)}", timeout=90)
    if r.returncode != 0:
        raise Stop(_network_problem(r, "the template"))


def _fetch_own(remote: str) -> None:
    r = _git("fetch", "--quiet", "--no-tags", remote, timeout=90)
    if r.returncode != 0:
        raise Stop(_network_problem(r, "your backup"))


def _push(remote: str, branch: str) -> str | None:
    """Push this branch to the user's own repository: None once pushed, else
    why not, in plain words. Never forced, and never to a repository anyone can
    read."""
    url = _git("remote", "get-url", "--push", remote).stdout.strip()
    if _readable_by_anyone(url):
        return PUBLIC.format(url=_shown(url))
    r = _git("push", "--quiet", "--porcelain", remote, f"HEAD:refs/heads/{branch}", timeout=120)
    return None if r.returncode == 0 else _network_problem(r, "your backup")


def _integrate(ref: str, message: str, where: str) -> int:
    """Bring `ref`'s new commits into this branch and say how many there were: a
    fast-forward when the branch has nothing of its own, else a merge, never a
    rebase. Stops with nothing changed when that would write over work not
    committed here, or when it conflicts, aborting the merge."""
    behind = _count(f"HEAD..{ref}")
    if not behind:
        return 0
    clash = _clash(ref, {p for _, p in _changes()})
    if clash:
        fix = ("Back up first, then try again." if where == "your backup" else
               "Commit those changes or undo them first (Claude Code, in this folder, can do "
               "either), then update again.")
        raise Stop(f"Bringing in {where} would write over {_files(clash)}, which "
                   f"{'has' if len(clash) == 1 else 'have'} changes on this machine that are "
                   f"not committed. {fix}")
    if _count(f"{ref}..HEAD"):
        _need_identity()
        r = _git("merge", "--no-autostash", "--ff", "--no-edit", "-q", "-m", message, ref,
                 timeout=120)
    else:
        r = _git("merge", "--no-autostash", "--ff-only", "-q", ref, timeout=120)
    if r.returncode != 0:
        conflicted = _z(_git("diff", "--name-only", "--diff-filter=U", "-z").stdout)
        if _rev("MERGE_HEAD"):
            _git("merge", "--abort")
        if conflicted:
            who = ("on this machine and on another one" if where == "your backup"
                   else "here and in the template")
            raise Stop(f"{_files(conflicted)} changed both {who}, in ways git cannot combine "
                       "by itself, so the merge was undone. To settle it, open Claude Code in "
                       f"this folder and ask it to merge {ref.split('/', 2)[-1]} and resolve the "
                       "conflict.")
        raise Stop(f"git stopped bringing in {where}: {_said(r)}")
    return behind


def _take_template(ref: str, label: str) -> int:
    """The first update of a copy that shares no history with the template: the
    files _file_plan() takes, in one commit whose second parent is the
    template, which joins the two histories. Built in an index of its own and
    then fast-forwarded to, so nothing on disk changes until git's own checks
    have passed."""
    plan = _file_plan(ref)
    if plan["conflicts"]:
        c = plan["conflicts"]
        raise Stop(f"{_files(c)} {'was' if len(c) == 1 else 'were'} changed in this copy, and "
                   "the template has changed them since, so the page will not choose between "
                   "the two. To settle it, open Claude Code in this folder and ask it to "
                   f"bring in the template's version of {'it' if len(c) == 1 else 'them'}, "
                   "keeping your changes.")
    paths = plan["take"] + plan["remove"]
    if not paths:
        return 0
    clash = _plan_clash(plan, {p for _, p in _changes()})
    if clash:
        raise Stop(f"The update would write over {_files(clash)}, which "
                   f"{'has' if len(clash) == 1 else 'have'} changes on this machine that are "
                   "not committed. Commit those changes or undo them first (Claude Code, in "
                   "this folder, can do either), then update again.")
    _need_identity()
    index = _ok("rev-parse", "--git-path", "bs-job-search-update.index").strip()
    index = index if os.path.isabs(index) else os.path.join(ROOT, index)
    env = {"GIT_INDEX_FILE": index}
    try:
        _ok("read-tree", "HEAD", env=env)
        lines = [f"{plan['theirs'][p][0]} {plan['theirs'][p][1]}\t{p}" for p in plan["take"]]
        lines += [f"0 {plan['ours'][p][1]}\t{p}" for p in plan["remove"]]
        _ok("update-index", "-z", "--index-info", input="".join(f"{l}\0" for l in lines), env=env)
        tree = _ok("write-tree", env=env).strip()
    finally:
        if os.path.exists(index):
            os.remove(index)
    message = (f"Update from the template to {label}, and join its history\n\n"
               "This copy was made with GitHub's Use this template, so it shared no history "
               f"with the template. This takes {_plural(len(plan['take']), 'file')} from the "
               f"template, drops {_plural(len(plan['remove']), 'file')} it no longer has, and "
               "records the template as merged, so later updates are ordinary merges.")
    commit = _ok("commit-tree", tree, "-p", _rev("HEAD"), "-p", _rev(ref), "-m", message).strip()
    r = _git("merge", "--no-autostash", "--ff-only", "-q", commit, timeout=120)
    if r.returncode != 0:
        raise Stop(f"git stopped the update: {_said(r)}")
    return len(paths)


def check_copy() -> dict:
    """Fetch the template, and the user's own repository if there is one,
    quietly, then say where the copy stands. A fetch that fails (no
    connection) is noted for the page, not raised."""
    if os.path.exists(os.path.join(ROOT, ".git")) and _git_lock.acquire(blocking=False):
        try:
            _checked["error"] = None
            try:
                lay = _layout(_remotes())
                if lay["own"]:
                    _fetch_own(lay["own"])
                if lay["template"]:
                    _fetch_template(lay["template"])
            except Stop as exc:
                _checked["error"] = str(exc)
            _checked["at"] = time.time()
        finally:
            _git_lock.release()
    return copy_status()


def update_copy(runs=None) -> dict:
    """Bring the copy up to date: for one with a repository of its own, first
    what another machine backed up there, then the template's updates; then
    push them, so the backup has them too. Returns what happened, in words,
    the files that changed, whether the page should be reloaded, and the status
    after it. Stops with nothing changed (see _integrate)."""
    with _exclusive(runs):
        remotes, lay, branch = _ready()
        if not lay["template"]:
            raise Stop("This copy is not linked to the template yet. Link it, then update.")
        if _started["head"] is None:
            remember_start()                 # a page started some other way: count from here
        old = _rev("HEAD")
        if lay["own"]:
            _fetch_own(lay["own"])
        _fetch_template(lay["template"])
        _checked.update(at=time.time(), error=None)
        lay = _layout(remotes)               # whether the histories are shared, now it is known
        done, ok, note = [], True, ""
        if lay["own"] and _rev(f"refs/remotes/{lay['own']}/{branch}"):
            n = _integrate(f"refs/remotes/{lay['own']}/{branch}",
                           "Bring in what another machine backed up", "your backup")
            if n:
                done.append(f"{_plural(n, 'change')} from your backup")
        tref = _tref(lay["template"])
        label = _label(tref) or f"its commit {_rev(tref)[:7]}"
        try:
            if lay["layout"] == "unrelated":
                n = _take_template(tref, label)
                what = _plural(n, "file")
            else:
                n = _integrate(tref, f"Update from the template to {label}", "the template")
                what = _plural(n, "update")
        except Stop as exc:
            if not done:
                raise
            ok, note, n = False, f" Then it stopped: {exc}", 0
        if n:
            done.append(f"{what} from the template")
        message = ("Brought in " + " and ".join(done) + "." if done
                   else "Already up to date.") + note
        if ok and lay["own"] and _count("HEAD", "--not", f"--remotes={lay['own']}"):
            why = _push(lay["own"], branch)
            ok = why is None
            message += " Not backed up yet: " + why if why else " Backed up."
        new = _rev("HEAD")
        changed = _names(old, new) if new != old else []
    reload = any(p.startswith("ui/") and p.endswith((".html", ".js", ".css")) for p in changed)
    return {"ok": ok, "message": message, "changed": changed, "reload": reload,
            "status": copy_status()}


def _commit_message(text) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(text or "").replace("\r\n", "\n")).strip()
    if not text:
        raise ValueError("Say in a few words what changed: it labels this backup in the history.")
    if len(text) > 2000:
        raise ValueError("Keep the message under 2,000 characters.")
    return text


def back_up(message: str | None, runs=None) -> dict:
    """Commit the user's own files (BACKUP_FOLDERS) with their message, bring in
    what another machine backed up, and push. The message is needed only when
    there are files to commit. Stops with nothing changed when there is nowhere
    to push, git has no name to commit under, or anyone could read the backup.
    Returns what happened, in words, and the status after."""
    if message is not None and str(message).strip():
        message = _commit_message(message)
    with _exclusive(runs):
        remotes, lay, branch = _ready()
        own = lay["own"]
        if not own:
            raise Stop(NO_BACKUP)
        paths = sorted({p for _, p in _changes() if _backed_up(p)})
        if paths:
            message = _commit_message(message)
        url = _git("remote", "get-url", "--push", own).stdout.strip()
        if _readable_by_anyone(url):
            raise Stop(PUBLIC.format(url=_shown(url)))
        if paths:
            _need_identity()
            listed = "".join(f"{p}\0" for p in paths)
            _ok("add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul", input=listed)
            _ok("commit", "-q", "-m", message, "--pathspec-from-file=-", "--pathspec-file-nul",
                input=listed)
        saved = f"Saved {_plural(len(paths), 'file')} on this machine"
        try:
            _fetch_own(own)
            oref = f"refs/remotes/{own}/{branch}"
            brought = _integrate(oref, "Bring in what another machine backed up",
                                 "your backup") if _rev(oref) else 0
        except Stop as exc:
            if not paths:
                raise
            ok, message = False, f"{saved}, but could not back them up. {exc}"
        else:
            got = f"Brought in {_plural(brought, 'change')} from your backup. " if brought else ""
            why = _push(own, branch) if _count("HEAD", "--not", f"--remotes={own}") else None
            if why is None:
                ok, message = True, got + (f"Backed up {_plural(len(paths), 'file')} to "
                                           f"{_shown(url)}." if paths else "Nothing new to back up.")
            elif paths:
                ok, message = False, f"{got}{saved}, but could not back them up. {why}"
            elif brought:
                ok, message = False, f"{got}Could not back up the rest. {why}"
            else:
                raise Stop(why)
    return {"ok": ok, "message": message, "status": copy_status()}


def save_identity(name, email) -> dict:
    """Give git the name and email it labels this copy's commits with, for this
    copy only, as /setup does, and return the status."""
    name, email = str(name or "").strip(), str(email or "").strip()
    if not name or len(name) > 100 or re.search(r"[\x00-\x1f\x7f<>]", name):
        raise ValueError("Give a name, on one line")
    if len(email) > 254 or not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", email):
        raise ValueError("Give an email address, like you@example.com")
    if not os.path.exists(os.path.join(ROOT, ".git")):
        raise Stop(NOT_A_REPO)
    with _exclusive():
        _ok("config", "--local", "user.name", name)
        _ok("config", "--local", "user.email", email)
    return copy_status()


def link_template() -> dict:
    """Add the template as the `template` remote of a copy with no remote for
    it, and fetch it. copy_status() then says whether the two share history."""
    if not os.path.exists(os.path.join(ROOT, ".git")):
        raise Stop(NOT_A_REPO)
    with _exclusive():
        remotes = _remotes()
        name = _layout(remotes)["template"]
        if name is None:
            if TEMPLATE_REMOTE in remotes:
                raise Stop(f"This copy already has a remote named {TEMPLATE_REMOTE}, for "
                           f"{_shown(remotes[TEMPLATE_REMOTE])}, which is not the template. "
                           "Rename or remove that remote first.")
            _ok("remote", "add", TEMPLATE_REMOTE, TEMPLATE_URL)
            name = TEMPLATE_REMOTE
        try:
            _fetch_template(name)
            _checked.update(at=time.time(), error=None)
        except Stop as exc:
            _checked["error"] = str(exc)
    return copy_status()

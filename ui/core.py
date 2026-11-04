"""What the local page shows and does, with no web framework in it.

server.py puts routes over these; the tests call them directly. Everything
here reads this copy's own files and runs this copy's own scripts, and nothing
else: the file reads are limited to the folders named below, the only writes
are a digest's boxes, feedback.md's verdicts, the statuses in
profile/applications.yaml and the two key files, and the only commands are the
ones in COMMANDS, with their arguments checked.

The page does what a person does between skills: reads a digest and marks it,
finds what was filed under Applications/ and records what came of each
application, runs the checks, and shows how far setup has got. Scoring,
choosing bullets, and writing letters stay in Claude Code, where the skills
are; claude_run.py streams those runs the same way the registry here streams a
script.
"""

from __future__ import annotations

import datetime as dt
import json
import os
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
import tracker  # noqa: E402

DIGESTS = digest_applies.DIGESTS
APPS = digest_applies.APPS

RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# What /api/health calls this page, so a second start can tell it from
# anything else on the port.
APP_NAME = "BS Job Search"

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
    """Write one entry's boxes and return the digest's new counts."""
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
    return {"checks": [r for r in rows if r["what"] not in keyed], "keys": key_status()}


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


def refusal(host: str | None, origin: str | None) -> str | None:
    """Why the page will not answer a request, or None when it will.

    It answers only requests addressed to this machine by name, which stops DNS
    rebinding. A request that carries an Origin must also come from the page
    itself. Browsers send one with every POST and PUT, so another site's form or
    script cannot start a run or answer a card, although the browser lets it
    send the request. curl and scripts send none, and are answered."""
    host = (host or "").strip().lower()
    name = host[:host.find("]") + 1] if host.startswith("[") else host.split(":")[0]
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
        if active is not None:
            raise RuntimeError(f"{active.name} is still {active.status}; end it first")
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

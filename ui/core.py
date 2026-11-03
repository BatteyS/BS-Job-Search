"""What the local page shows and does, with no web framework in it.

server.py puts routes over these; the tests call them directly. Everything
here reads this copy's own files and runs this copy's own scripts, and nothing
else: the file reads are limited to the folders named below, and the only
commands are the ones in COMMANDS, with their arguments checked.

The page does what a person does between skills: reads a digest and marks it,
finds what was filed under Applications/, runs the checks. Scoring, choosing
bullets, and writing letters stay in Claude Code, where the skills are. The
run registry is written so a later version can stream a skill the same way it
streams a script.
"""

from __future__ import annotations

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


def list_applications() -> list[dict]:
    """Every folder under Applications/ with its files. A folder whose name
    starts with `_` is not an employer: the page shows it apart, and its
    subfolders (resumes sent to people, grouped by person) each get a row."""
    out = []
    if not os.path.isdir(APPS):
        return out
    for name in sorted(os.listdir(APPS), key=str.lower):
        folder = os.path.join(APPS, name)
        if not os.path.isdir(folder) or name.startswith("."):
            continue
        employer = not name.startswith("_")
        files = _files_in(folder)
        if employer or files:
            out.append({"company": name, "employer": employer, "files": files})
        if not employer:
            for sub in sorted(os.listdir(folder), key=str.lower):
                if os.path.isdir(os.path.join(folder, sub)) and not sub.startswith("."):
                    out.append({"company": f"{name}/{sub}", "employer": False,
                                "files": _files_in(os.path.join(folder, sub))})
    return out


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


# ------------------------------------------------------------------ profile

def list_profile_files() -> list[dict]:
    return [{"path": rel, "about": about, "exists": os.path.isfile(os.path.join(ROOT, rel))}
            for rel, about in PROFILE_FILES]


def read_profile_file(rel: str) -> str:
    if rel not in {p for p, _ in PROFILE_FILES}:
        raise ValueError(f"{rel} is not one of the profile files")
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


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

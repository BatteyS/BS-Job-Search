"""The local page's reads and writes, through ui/core.py: marking a digest in
place, the verdicts gate, the Applications listing and its statuses, and the
file guards. The routes in ui/server.py are thin over these; the check in front
of them, which refuses other hosts and other sites, is also tried through the
app itself, and so is the status route."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys

import pytest
import yaml

from helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "ui"))
import core  # noqa: E402
import digest_applies  # noqa: E402
import doctor  # noqa: E402
import tracker  # noqa: E402

DIGEST = """# Job digest — 2026-11-02

**Clusters:** nursing

> Mark each entry `apply` or `skip — reason`.

---

### 1. Acme Energy — Project Engineer · **84** · Sacramento · $128,000
- [ ] apply
- [ ] skip — reason:
- [ ] cover letter

**Why:** Owns a storage deployment end to end.
**Resume:** chronological · **Effort:** low
[View posting](https://example.com/1)

---

### 2. Birch Grid — Field Engineer · **80** · Sacramento
- [ ] apply
- [x] skip — reason: wants 8+ years

### 3. Cedar Power — Analyst · **75** · Sacramento
- [x] apply
- [ ] skip — reason:
- [ ] cover letter
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A scratch repo with one digest, an Applications/ folder, and a feedback.md."""
    (tmp_path / "digests").mkdir()
    (tmp_path / "digests" / "2026-11-02.md").write_text(DIGEST, encoding="utf-8")
    apps = tmp_path / "Applications"
    (apps / "Acme Energy").mkdir(parents=True)
    (apps / "Acme Energy" / "Project Engineer.pdf").write_bytes(b"%PDF-1.4 stub")
    (apps / "Acme Energy" / "Project Engineer.tex").write_text("x", encoding="utf-8")
    (apps / "Acme Energy" / "notes.docx").write_bytes(b"not served")
    (apps / "_Not employers" / "Sent to a friend").mkdir(parents=True)
    (apps / "_Not employers" / "Sent to a friend" / "Resume.pdf").write_bytes(b"%PDF-1.4 stub")
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "feedback.md").write_text("# Feedback\n", encoding="utf-8")
    for mod in (digest_applies, core):
        monkeypatch.setattr(mod, "ROOT", str(tmp_path))
        monkeypatch.setattr(mod, "DIGESTS", str(tmp_path / "digests"))
        monkeypatch.setattr(mod, "APPS", str(apps))
    monkeypatch.setattr(tracker, "ROOT", str(tmp_path))
    return tmp_path


def digest_text(repo) -> str:
    return (repo / "digests" / "2026-11-02.md").read_text(encoding="utf-8")


# ----------------------------------------------------------------- marks

def test_marks_change_only_the_boxes(repo):
    before = digest_text(repo)
    core.mark_entry("2026-11-02", 1, apply=True, letter=True)
    after = digest_text(repo)
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert changed == [("- [ ] apply", "- [x] apply"), ("- [ ] cover letter", "- [x] cover letter")]
    assert len(before.splitlines()) == len(after.splitlines())
    assert after.endswith("- [ ] cover letter\n")   # the file's end is untouched


def test_skip_with_reason_and_unskip_clears_it(repo):
    core.mark_entry("2026-11-02", 1, skip=True, skip_reason="wants 10+ years")
    assert "- [x] skip — reason: wants 10+ years" in digest_text(repo)
    e = next(e for e in core.read_digest("2026-11-02")["entries"] if e["n"] == 1)
    assert e["marked_skip"] and e["skip_reason"] == "wants 10+ years"

    core.mark_entry("2026-11-02", 1, skip=False)
    assert "- [ ] skip — reason:\n" in digest_text(repo)
    assert "10+ years" not in digest_text(repo)


def test_reason_alone_keeps_the_tick(repo):
    core.mark_entry("2026-11-02", 2, skip_reason="too senior")
    assert "- [x] skip — reason: too senior" in digest_text(repo)


def test_letter_line_is_added_to_an_old_entry(repo):
    core.mark_entry("2026-11-02", 2, letter=True)
    text = digest_text(repo)
    assert "- [x] skip — reason: wants 8+ years\n- [x] cover letter\n" in text
    assert text.count("cover letter") == 3


def test_unknown_entry_and_bad_date(repo):
    with pytest.raises(ValueError):
        core.mark_entry("2026-11-02", 9, apply=True)
    with pytest.raises(ValueError):
        core.read_digest("../profile")
    with pytest.raises(FileNotFoundError):
        core.read_digest("2026-01-01")


def test_counts_follow_the_marks(repo):
    assert core.list_digests() == [{"date": "2026-11-02", "entries": 3, "apply": 1,
                                    "skip": 1, "unmarked": 1, "conflicts": 0}]
    counts = core.mark_entry("2026-11-02", 1, apply=True)
    assert counts["apply"] == 2 and counts["unmarked"] == 0


def test_read_digest_keeps_the_text_and_drops_the_boxes(repo):
    d = core.read_digest("2026-11-02")
    assert d["preamble"].startswith("# Job digest") and "Mark each entry" in d["preamble"]
    one = d["entries"][0]
    assert "**Why:**" in one["body"] and "[View posting]" in one["body"]
    assert "apply" not in one["body"]
    assert one["already_built"] is True


# -------------------------------------------------------------- verdicts

def test_verdicts_wait_until_settled_then_append_once(repo):
    core.mark_entry("2026-11-02", 2, skip_reason="")   # a skip with no reason
    v = core.verdicts_section("2026-11-02")
    assert v["section"].startswith("### 2026-11-02 — 3 scored, 1 apply, 1 skip")
    assert any("no reason" in s for s in v["settle"])
    with pytest.raises(ValueError, match="settle"):
        core.append_feedback("2026-11-02")

    core.mark_entry("2026-11-02", 2, skip_reason="wants 8+ years")
    core.mark_entry("2026-11-02", 1, apply=True)
    assert core.append_feedback("2026-11-02") == "profile/feedback.md"
    text = (repo / "profile" / "feedback.md").read_text(encoding="utf-8")
    assert text.startswith("# Feedback\n\n### 2026-11-02 — 3 scored, 2 apply, 1 skip")
    assert "| 1 | Acme Energy — Project Engineer | 84 | Sacramento |" in text
    with pytest.raises(ValueError, match="already"):
        core.append_feedback("2026-11-02")


# ---------------------------------------------------------- applications

def test_applications_listing_and_file_guards(repo):
    apps = core.list_applications()["folders"]
    assert [a["company"] for a in apps] == ["_Not employers/Sent to a friend", "Acme Energy"]
    acme = next(a for a in apps if a["company"] == "Acme Energy")
    assert acme["employer"] is True
    assert {f["name"]: f["viewable"] for f in acme["files"]} == {
        "Project Engineer.pdf": True, "Project Engineer.tex": True, "notes.docx": False}
    friend = next(a for a in apps if not a["employer"])
    assert [f["name"] for f in friend["files"]] == ["Resume.pdf"]

    assert core.application_file("Acme Energy", "Project Engineer.pdf").endswith(".pdf")
    assert core.application_file("_Not employers/Sent to a friend", "Resume.pdf").endswith(".pdf")
    with pytest.raises(ValueError):
        core.application_file("Acme Energy", "notes.docx")
    with pytest.raises(ValueError):
        core.application_file("..", "feedback.md")
    with pytest.raises(ValueError):
        core.application_file("Acme Energy/deeper", "Project Engineer.pdf")
    with pytest.raises(ValueError):
        core.application_file("_Not employers/../Acme Energy", "Project Engineer.pdf")
    with pytest.raises(FileNotFoundError):
        core.application_file("Acme Energy", "missing.pdf")


def test_the_tab_shows_where_each_application_stands(repo):
    old = repo / "Applications" / "Old Clinic"
    old.mkdir()
    (old / "Resume (Old Clinic).pdf").write_bytes(b"%PDF-1.4 stub")
    tracker.set_status("Acme Energy", "Project Engineer", status="applied", allow_new=True)
    tracker.set_status("Faraway Health", "Charge Nurse", status="applied", allow_new=True)
    listing = core.list_applications()
    folders = {f["company"]: f for f in listing["folders"]}

    [acme] = folders["Acme Energy"]["roles"]
    assert (acme["role"], acme["status"], acme["filed"], acme["tracked"]) == (
        "Project Engineer", "applied", True, True)
    assert acme["digest"] == {"date": "2026-11-02", "n": 1, "score": 84}
    [whole] = folders["Old Clinic"]["roles"]          # no role in its file names
    assert (whole["role"], whole["status"], whole["tracked"]) == ("", None, False)
    away = folders["Faraway Health"]                  # its folder is on another machine
    assert away["on_disk"] is False and away["files"] == []
    assert away["roles"][0]["status"] == "applied" and not away["roles"][0]["filed"]
    assert folders["_Not employers/Sent to a friend"]["roles"] == []
    assert listing["statuses"] == list(tracker.STATUSES) and not listing["problem"]


def test_the_tab_changes_only_what_it_lists(repo):
    listing = core.set_application_status("Acme Energy", "Project Engineer", status="applied")
    acme = next(f for f in listing["folders"] if f["company"] == "Acme Energy")
    assert acme["roles"][0]["status"] == "applied"
    assert "- company: Acme Energy" in (repo / tracker.TRACKER).read_text(encoding="utf-8")
    entry = next(e for e in core.read_digest("2026-11-02")["entries"] if e["n"] == 1)
    assert entry["status"] == "applied"               # the digest shows it too
    for company, role in (("Acme Energy", "Analyst"), ("Nowhere Inc", ""),
                          ("_Not employers/Sent to a friend", ""), ("..", "")):
        with pytest.raises(ValueError, match="lists no application"):
            core.set_application_status(company, role, status="applied")


def test_interview_prep_needs_a_filed_posting(repo):
    """What the Interview prep button sends, a company and a job title, must
    name a posting filed in an employer's folder."""
    folder = repo / "Applications" / "Acme Energy"
    (folder / "Project Engineer - posting.txt").write_text("posting", encoding="utf-8")
    assert core.posting_path("Acme Energy", "Project Engineer") == str(
        folder / "Project Engineer - posting.txt")
    with pytest.raises(FileNotFoundError):
        core.posting_path("Acme Energy", "Analyst")
    for company, title in [("", "Project Engineer"), ("Acme Energy", ""), ("..", "x"),
                           ("Acme Energy", "../../profile/feedback"),
                           ("_Not employers/Sent to a friend", "Resume")]:
        with pytest.raises(ValueError):
            core.posting_path(company, title)


def test_profile_files_are_an_allowlist(repo):
    assert core.read_profile_file("profile/feedback.md") == "# Feedback\n"
    with pytest.raises(ValueError):
        core.read_profile_file("content/contact.local.md")
    with pytest.raises(ValueError):
        core.read_profile_file("../etc/passwd")


# ------------------------------------------------------------------ setup

@pytest.fixture
def fresh(repo, monkeypatch):
    """The scratch repo as a copy before /setup: doctor pointed at it, the key
    examples in sources/, and no key in the environment."""
    monkeypatch.setattr(doctor, "ROOT", str(repo))
    (repo / "sources").mkdir()
    for name in doctor.KEYS:
        shutil.copy(os.path.join(ROOT, "sources", f"{name}.example.yaml"), repo / "sources")
    for _, _, _, env, _ in doctor.KEYS.values():
        for var in env:
            monkeypatch.delenv(var, raising=False)
    return repo


def test_setup_is_ready_once_the_needed_files_are_written_and_reviewed(fresh):
    s = core.setup_state()
    assert [f["state"] for f in s["files"]] == ["missing"] * 6 and not s["ready"]
    for rel, _, needed in core.SETUP_FILES:
        if needed:
            (fresh / rel).parent.mkdir(parents=True, exist_ok=True)
            (fresh / rel).write_text("written\n", encoding="utf-8")
    assert core.setup_state()["ready"]   # story.md: only letters need it

    (fresh / "content/master.md").write_text(f"{doctor.DRAFT}\n# Experience\n", encoding="utf-8")
    s = core.setup_state()
    assert not s["ready"]
    assert {f["path"]: f["state"] for f in s["files"]}["content/master.md"] == "draft"


def test_the_test_resume_is_offered_once_setup_has_built_it(fresh):
    assert core.setup_state()["test_resume"] is None
    with pytest.raises(FileNotFoundError):
        core.test_resume()
    pdf = fresh / core.TEST_RESUME
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 stub")
    assert core.setup_state()["test_resume"]["path"] == core.TEST_RESUME
    assert os.path.samefile(core.test_resume(), pdf)


def test_a_key_is_saved_to_its_file_and_never_read_back(fresh):
    assert [(k["source"], k["saved"], k["on"]) for k in core.key_status()] == [
        ("adzuna", False, None), ("usajobs", False, None)]
    assert core.save_keys("adzuna", {"app_id": " abc123 ", "app_key": "s3cr3t-key"}) == \
        "sources/adzuna.local.yaml"
    path = fresh / "sources/adzuna.local.yaml"
    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text) == {"app_id": "abc123", "app_key": "s3cr3t-key"}
    assert text.startswith("# Adzuna API credentials")   # the example's comments come along
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    status = core.key_status()
    assert status[0]["saved"] and not status[1]["saved"]
    assert "s3cr3t" not in json.dumps(status) + json.dumps(core.setup_checks())


def test_a_key_file_keeps_everything_else_it_holds(fresh):
    path = fresh / "sources/usajobs.local.yaml"
    path.write_text('# mine\nemail: "you@example.com"\napi_key: "your-api-key"\n'
                    "agencies: [DOE]\n", encoding="utf-8")
    core.save_keys("usajobs", {"email": "pat@example.org", "api_key": "K3Y"})
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# mine\n")
    assert yaml.safe_load(text) == {"email": "pat@example.org", "api_key": "K3Y",
                                    "agencies": ["DOE"]}


@pytest.mark.parametrize("name,values", [
    ("indeed", {"key": "x"}),                                    # takes no key
    ("adzuna", {"app_id": "abc"}),                               # a field missing
    ("adzuna", {"app_id": "abc", "app_key": "x", "extra": "y"}),
    ("adzuna", {"app_id": "", "app_key": "x"}),
    ("adzuna", {"app_id": "two words", "app_key": "x"}),
    ("adzuna", {"app_id": "abc", "app_key": "line\nbreak"}),
    ("adzuna", {"app_id": "your-app-id", "app_key": "x"}),       # the example's placeholder
    ("adzuna", {"app_id": 12345, "app_key": "x"}),
    ("usajobs", {"email": "not-an-email", "api_key": "x"}),
])
def test_what_is_not_a_key_is_refused_and_nothing_written(fresh, name, values):
    with pytest.raises(ValueError):
        core.save_keys(name, values)
    assert not list((fresh / "sources").glob("*.local.yaml"))


def test_whether_a_source_is_on_comes_from_filters(fresh):
    filters = fresh / "profile/filters.yaml"
    filters.write_text("sources:\n  boards: true\n  adzuna: true\n", encoding="utf-8")
    assert [k["on"] for k in core.key_status()] == [True, False]
    filters.write_text("metros: {}\n", encoding="utf-8")   # no sources block: boards only
    assert [k["on"] for k in core.key_status()] == [False, False]


def test_the_checks_leave_the_keys_to_the_form(fresh):
    (fresh / "profile/filters.yaml").write_text("sources:\n  adzuna: true\n", encoding="utf-8")
    c = core.setup_checks()
    assert {r["group"] for r in c["checks"]} <= {"python", "latex", "profile", "sources"}
    assert not any(r["what"].endswith(" key") for r in c["checks"])
    assert c["keys"][0]["on"] is True and not c["keys"][0]["saved"]


# ------------------------------------------------------------------ runs

def test_runs_stream_output_and_check_their_arguments(repo, monkeypatch):
    runs = core.Runs()
    names = ["doctor", "applies", "fetch", "outcomes"] + ([] if sys.platform == "win32" else ["latex"])
    assert [c["name"] for c in runs.commands()] == names
    with pytest.raises(ValueError):
        runs.start("rm")
    with pytest.raises(ValueError):
        runs.start("applies", {"date": "2026-11-02; rm -rf /"})

    monkeypatch.setattr(core, "_script", lambda name, *a: [sys.executable, "-c",
                                                           "print('one'); print('two')"])
    run = runs.start("doctor")
    got = [item for item in run.follow() if item is not None]
    assert [line for _, line in got] == ["one", "two"]
    assert run.status == "done" and run.returncode == 0
    assert runs.get(run.id).summary()["lines"] == 2
    with pytest.raises(KeyError):
        runs.get("nope")


def test_a_quiet_run_gives_its_follower_a_beat_and_loses_nothing():
    """With a beat, following a run that has nothing new yields BEAT, so the
    stream reading it gets a turn, and goes on from where it was."""
    import threading
    changed = threading.Condition()
    items, state = ["one"], {"active": True}
    got = core.follow(changed, items, lambda: state["active"], beat=0.05)
    assert next(got) == (0, "one")
    assert next(got) is core.BEAT
    assert next(got) is core.BEAT
    with changed:
        items.append("two")
        changed.notify_all()
    assert next(got) == (1, "two")
    state["active"] = False
    assert next(got) is None
    assert list(core.follow(changed, items, lambda: False, start=1)) == [(1, "two"), None]


# ------------------------------------------------------------------ the port
# Small servers on loopback, standing in for what might hold the page's port.

def _serve(health: dict | None):
    import http.server
    import json
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if health is None or self.path != "/api/health":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(health).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_second_start_can_tell_this_page_from_anything_else(tmp_path):
    import socket

    this = _serve({"app": core.APP_NAME, "root": core.ROOT})
    another = _serve({"app": core.APP_NAME, "root": str(tmp_path)})
    stranger = _serve(None)
    try:
        assert core.probe_port(this.server_port) == ("this", core.ROOT)
        assert core.probe_port(another.server_port) == ("another", str(tmp_path))
        assert core.probe_port(stranger.server_port) == ("other", "")
    finally:
        for s in (this, another, stranger):
            s.shutdown()
            s.server_close()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert core.probe_port(free) == ("free", "")


# ----------------------------------------------------------- the start files

def test_the_start_files_run_the_page_and_ship_with_the_template():
    import export_template
    for name in ("start.command", "start.cmd"):
        with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
            assert "run ui/server.py" in fh.read(), name
        assert export_template.is_engine(name)


@pytest.mark.skipif(os.name != "posix", reason="a shell script")
def test_start_command_runs_uv_from_its_own_folder(tmp_path):
    import subprocess
    script = os.path.join(ROOT, "start.command")
    assert os.access(script, os.X_OK), "double-clicking needs it executable"
    (tmp_path / "bin").mkdir()
    stub = tmp_path / "bin" / "uv"
    stub.write_text('#!/bin/sh\necho "uv $* in $(pwd -P)"\n', encoding="utf-8")
    stub.chmod(0o755)
    r = subprocess.run([script, "--no-open"], capture_output=True, text=True, cwd=str(tmp_path),
                       env={"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == f"uv run ui/server.py --no-open in {os.path.realpath(ROOT)}"


# --------------------------------------------------------------- who may ask

@pytest.mark.parametrize("host,origin", [
    ("127.0.0.1:8765", None),
    ("127.0.0.1:8765", "http://127.0.0.1:8765"),
    ("localhost:8765", "http://localhost:8765"),
    ("[::1]:8765", None),
])
def test_the_page_answers_itself(host, origin):
    assert core.refusal(host, origin) is None


@pytest.mark.parametrize("host,origin", [
    ("rebind.attacker.example:8765", None),          # DNS rebinding: the site's own name
    ("127.0.0.1.attacker.example:8765", None),
    ("", None), (None, None), ("[::1", None),
    ("127.0.0.1:8765", "https://attacker.example"),  # another site's form or script
    ("127.0.0.1:8765", "null"),                      # a sandboxed frame
    ("127.0.0.1:8765", "http://localhost:3000"),     # a page on another local port
])
def test_the_page_refuses_everyone_else(host, origin):
    assert core.refusal(host, origin)


def _ask(app, method: str, path: str, headers: dict, body: bytes = b"") -> int:
    """One request through the app, as uvicorn hands it over. Returns the status."""
    import asyncio
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "root_path": "", "client": ("127.0.0.1", 50000),
             "server": ("127.0.0.1", 8765),
             "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]}
    sent = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_the_server_refuses_before_any_route_runs():
    pytest.importorskip("fastapi")
    import server
    here = {"host": "127.0.0.1:8765"}
    assert _ask(server.app, "GET", "/api/health", here) == 200
    assert _ask(server.app, "GET", "/api/health", {"host": "rebind.attacker.example:8765"}) == 403
    # No command has this name, so nothing runs: a 400 is the route answering.
    assert _ask(server.app, "POST", "/api/runs/nosuch", here) == 400
    assert _ask(server.app, "POST", "/api/runs/nosuch",
                {**here, "origin": "http://127.0.0.1:8765"}) == 400
    assert _ask(server.app, "POST", "/api/runs/nosuch",
                {**here, "origin": "https://attacker.example"}) == 403


def test_a_status_goes_through_its_route(repo):
    pytest.importorskip("fastapi")
    import server
    here = {"host": "127.0.0.1:8765", "content-type": "application/json"}
    acme = {"company": "Acme Energy", "role": "Project Engineer"}

    def put(change: dict, headers=here) -> int:
        return _ask(server.app, "PUT", "/api/applications/status", headers,
                    json.dumps(change).encode())

    assert put({**acme, "status": "applied"}) == 200
    for bad in ({**acme, "colour": "red"}, {**acme, "status": 3}, {**acme, "undo": "yes"},
                {"status": "applied"}, {**acme, "status": "applied"},
                {**acme, "status": "heard back", "date": "2999-01-01"}):
        assert put(bad) == 400, bad
    assert put({**acme, "undo": False, "note": "a recruiter wrote"}) == 200
    assert put({**acme, "status": "rejected"},
               {**here, "origin": "https://attacker.example"}) == 403
    [row] = next(f for f in core.list_applications()["folders"]
                 if f["company"] == "Acme Energy")["roles"]
    assert (row["status"], row["note"]) == ("applied", "a recruiter wrote")


def test_the_copys_routes_are_behind_the_same_check(tmp_path, monkeypatch):
    """Update, Back up and the rest change the copy and reach GitHub, so another
    site must not reach them either. Pointed at a folder that is no repository,
    the page's own requests are answered with a stop, and nothing runs."""
    pytest.importorskip("fastapi")
    import server
    monkeypatch.setattr(core, "ROOT", str(tmp_path))
    here = {"host": "127.0.0.1:8765"}
    page = {**here, "origin": "http://127.0.0.1:8765"}
    assert _ask(server.app, "GET", "/api/copy", here) == 200
    for method, path in [("POST", "/api/copy/check"), ("POST", "/api/copy/update"),
                         ("POST", "/api/copy/backup"), ("POST", "/api/copy/link"),
                         ("PUT", "/api/copy/identity")]:
        assert _ask(server.app, method, path, {**here, "origin": "https://attacker.example"}) == 403
        assert _ask(server.app, method, path, {"host": "rebind.attacker.example:8765"}) == 403
    assert _ask(server.app, "POST", "/api/copy/update", page) == 409
    assert _ask(server.app, "POST", "/api/copy/link", page) == 409


# ------------------------------------------------------------------ stopping
# Under launchd (ui/phone.py), a page that has stopped serving but not exited
# holds the port: launchd starts no other while it lives, and queues every
# request for it. Job Search on the Desktop waited two minutes on one before
# opening a page elsewhere, and the phone got nothing.

STOPPING = """
import os, sys, threading
root, index, port = sys.argv[1:4]
sys.path.insert(0, os.path.join(root, "ui"))
import claude_run, server
claude_run.INDEX = index
run = claude_run.ClaudeRun("setup", "/setup", "/bin/true")
run.id = "waiting"
run._set_status("idle")   # its turn is over, and it waits for a reply
server.runs.add(run)
server.app.get("/api/stuck")(lambda: threading.Event().wait())   # never returns
# The real beat and deadline (2 and 30 seconds) scaled down, the deadline still
# many beats long: a stream cancelled just after a beat ends a whole beat later.
# With both at 2, the quit below, which lands about on a beat, could cut off the
# stream as though it would never end.
server.STREAM_BEAT = 0.25
server.EXIT_DEADLINE = 2
sys.argv = ["server.py", "--no-open", "--port", port]
server.main()
"""


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(os.name != "posix", reason="a real server, stopped and timed")
@pytest.mark.parametrize("tab", ["closed", "left open", "stuck"])
def test_the_page_stops_though_a_stream_follows_a_run_that_waits(tmp_path, tab):
    """A stream following a skill that waits for a reply has nothing to send
    until the reply comes, which may be never. Asked to stop, the page stops
    within seconds all the same, with the tab that opened the stream closed or
    still open. A request that never ends is cut off at the deadline."""
    pytest.importorskip("fastapi")
    import socket
    import time
    import urllib.request
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen([sys.executable, "-c", STOPPING, ROOT, str(tmp_path / "runs.json"),
                             str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    stream = None
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=1).read()
                break
            except OSError:
                assert proc.poll() is None, proc.stdout.read()
                time.sleep(0.1)
        stream = socket.create_connection(("127.0.0.1", port), timeout=5)
        stream.sendall(f"GET /api/runs/waiting/stream HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n"
                       .encode())
        got = b""
        while b"data:" not in got:      # its first event, then nothing more
            got += stream.recv(4096)
        assert b" 200 " in got
        time.sleep(0.5)
        if tab == "closed":
            stream.close()
        if tab == "stuck":
            stuck = socket.create_connection(("127.0.0.1", port), timeout=5)
            stuck.sendall(f"GET /api/stuck HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
        quit_ = urllib.request.Request(base + "/api/quit", data=b"{}", method="POST",
                                       headers={"Content-Type": "application/json"})
        assert json.loads(urllib.request.urlopen(quit_, timeout=5).read()) == {"quitting": True}
        asked = time.monotonic()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pytest.fail("the page had not stopped 30 seconds after it was asked to")
        assert time.monotonic() - asked < 15
        printed = proc.stdout.read()
        assert ("ending it" in printed) == (tab == "stuck"), printed
    finally:
        if stream is not None:
            stream.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()


def test_idle_exit_waits_for_silence_and_for_runs_to_end():
    now = [0.0]
    idle = core.Idle(clock=lambda: now[0])
    runs = core.Runs()
    assert not idle.should_exit(10, runs)
    now[0] = 599
    assert not idle.should_exit(10, runs)
    now[0] = 600
    assert idle.should_exit(10, runs)
    assert not idle.should_exit(0, runs)          # 0 means never

    class Going:
        id, name, status = "r1", "scan", "running"
    runs.add(Going())
    assert not idle.should_exit(10, runs)         # a working run keeps it up
    Going.status = "waiting"                      # on a card, for whoever comes back
    assert not idle.should_exit(10, runs)
    Going.status = "idle"                         # its turn is over: Past runs resumes it
    assert idle.should_exit(10, runs)
    Going.status = "done"
    assert idle.should_exit(10, runs)
    idle.touch()
    assert not idle.should_exit(10, runs)


def test_only_a_page_the_launcher_started_restarts_itself(tmp_path, monkeypatch):
    """Job Search on the Desktop runs ui/launch.sh, which tells the server where
    it is; a page started in a terminal is restarted there, by hand."""
    started = []
    popen = lambda argv, **kw: started.append((argv, kw))   # noqa: E731
    runs = core.Runs()
    monkeypatch.delenv("BS_LAUNCHER", raising=False)
    assert core.launcher() is None
    with pytest.raises(core.Stop, match="terminal"):
        core.restart(8765, runs, popen=popen)

    launch = tmp_path / "launch.sh"
    launch.write_text("#!/bin/sh\n")
    monkeypatch.setenv("BS_LAUNCHER", str(launch))
    assert core.launcher() == str(launch)
    core.restart(8766, runs, popen=popen)
    (argv, kw), = started
    assert argv == ["/bin/sh", str(launch), "--restart", "8766"]
    assert kw["start_new_session"] is True   # it outlives the server that started it

    class Going:
        id, name, status = "r1", "setup", "waiting"
    runs.add(Going())
    with pytest.raises(core.Stop, match="still working"):
        core.restart(8766, runs, popen=popen)
    assert len(started) == 1
    Going.status = "idle"                         # a finished turn does not hold it
    core.restart(8766, runs, popen=popen)
    assert len(started) == 2


def test_starting_a_skill_ends_one_that_waits_for_a_reply(monkeypatch):
    """One skill works at a time, but one whose turn is over holds nothing: the
    next skill ends it, and Past runs can pick its conversation up again."""
    import claude_run

    class Old:
        id, name, status = "r1", "job-scan", "idle"
        def summary(self):
            return {"kind": "claude"}
        def stop(self):
            Old.status = "done"

    class New(Old):
        id, name, status = "r2", "tailor-resume", "starting"
    monkeypatch.setattr(claude_run, "start_skill", lambda *a, **k: New())
    runs = core.Runs()
    runs.add(Old())
    assert runs.start_skill("tailor-resume").id == "r2"
    assert Old.status == "done"
    Old.status = "running"
    with pytest.raises(RuntimeError, match="still running"):
        runs.start_skill("cover-letter")


def test_what_a_run_filed_is_listed_by_when_it_was_written(repo):
    apps = repo / "Applications"
    resume = apps / "Acme Energy" / "Project Engineer.pdf"
    nested = apps / "_Not employers" / "Sent to a friend" / "Resume.pdf"
    for path, when in ((resume, 1000.0), (nested, 2000.0)):
        os.utime(path, (when, when))
    os.utime(apps / "Acme Energy" / "Project Engineer.tex", (10.0, 10.0))
    os.utime(apps / "Acme Energy" / "notes.docx", (10.0, 10.0))
    got = core.filed(500)
    assert [(f["company"], f["name"]) for f in got] == [
        ("_Not employers/Sent to a friend", "Resume.pdf"), ("Acme Energy", "Project Engineer.pdf")]
    assert [f["name"] for f in core.filed(500, until=1500)] == ["Project Engineer.pdf"]
    for f in got:   # each opens where the Applications tab opens it
        assert core.application_file(f["company"], f["name"])


def test_the_launcher_and_installer_are_plain_sh():
    """Both run under the sh every Mac has, and under dash, the strictest."""
    for name in ("install.sh", "ui/launch.sh"):
        for shell in ("sh", "bash", "dash"):
            path = shutil.which(shell)
            if path:
                r = subprocess.run([path, "-n", os.path.join(ROOT, name)], capture_output=True, text=True)
                assert r.returncode == 0, f"{shell} -n {name}: {r.stderr}"


# ------------------------------------------- changes made against a view

ACME = {"company": "Acme Energy", "title": "Project Engineer"}


def test_a_mark_for_the_role_it_was_ticked_for_is_written(repo):
    core.mark_entry("2026-11-02", 1, apply=True, expect={"apply": False}, entry=ACME)
    assert "- [x] apply" in digest_text(repo).split("### 2.")[0]
    # Names are compared loosely, the way the digest index joins them.
    core.mark_entry("2026-11-02", 1, letter=True, entry={"company": "ACME energy", "title": "project engineer"})


def test_a_mark_for_a_role_that_moved_is_refused(repo):
    before = digest_text(repo)
    with pytest.raises(tracker.Conflict) as refused:
        core.mark_entry("2026-11-02", 1, apply=True, entry={"company": "Birch Grid", "title": "Field Engineer"})
    assert "now Acme Energy — Project Engineer" in str(refused.value)
    assert refused.value.current["company"] == "Acme Energy"
    assert digest_text(repo) == before


def test_each_box_is_judged_apart(repo):
    # Entry 2 is skipped. Ticking apply against apply as seen still works.
    core.mark_entry("2026-11-02", 2, apply=True, expect={"apply": False})
    # Already at its new value: nothing to do, and nothing refused.
    assert digest_applies.write_marks(str(repo / "digests" / "2026-11-02.md"), 2, apply=True,
                                      expect={"apply": False}) is False
    # Changed elsewhere to something else: refused, with what is there now.
    with pytest.raises(tracker.Conflict) as refused:
        core.mark_entry("2026-11-02", 2, skip=False, expect={"skip": False})
    assert "skip is ticked" in str(refused.value)
    assert refused.value.current["skip_reason"] == "wants 8+ years"
    with pytest.raises(tracker.Conflict, match="skip reason is “wants 8"):
        core.mark_entry("2026-11-02", 2, skip_reason="too far", expect={"skip_reason": "too senior"})
    core.mark_entry("2026-11-02", 2, skip_reason="too far", expect={"skip_reason": " wants  8+ years "})
    assert "reason: too far" in digest_text(repo)


def test_a_digest_is_written_whole_through_a_file_beside_it(repo):
    path = repo / "digests" / "2026-11-02.md"
    path.chmod(0o640)
    core.mark_entry("2026-11-02", 1, apply=True)
    assert sorted(p.name for p in (repo / "digests").iterdir()) == ["2026-11-02.md"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def _answer(method: str, path: str, body: dict) -> tuple[int, dict]:
    """One JSON request through the page: its status and what it said."""
    import asyncio
    import server
    raw = json.dumps(body).encode()
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "root_path": "", "client": ("127.0.0.1", 50000),
             "server": ("127.0.0.1", 8765),
             "headers": [(b"host", b"127.0.0.1:8765"), (b"content-type", b"application/json")]}
    sent, asked = [], []

    async def receive():
        if not asked:
            asked.append(True)
            return {"type": "http.request", "body": raw, "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    asyncio.run(server.app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    text = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(text) if text else {}


def test_the_routes_answer_409_with_what_is_there_now(repo):
    pytest.importorskip("fastapi")
    status, said = _answer("PUT", "/api/digests/2026-11-02/entries/2",
                           {"skip": False, "expect": {"skip": False}, "entry": {"company": "Birch Grid", "title": "Field Engineer"}})
    assert status == 409 and said["detail"]["current"]["skip"] is True
    assert "changed since" in said["detail"]["message"]
    for bad in ({"apply": True, "expect": {"colour": 1}}, {"apply": True, "expect": {"apply": "yes"}},
                {"apply": True, "entry": {"company": "Acme Energy"}}, {"apply": True, "expect": []}):
        assert _answer("PUT", "/api/digests/2026-11-02/entries/1", bad)[0] == 400, bad
    acme = {"company": "Acme Energy", "role": "Project Engineer"}
    assert _answer("PUT", "/api/applications/status", {**acme, "status": "applied", "expect_last": ""})[0] == 200
    status, said = _answer("PUT", "/api/applications/status", {**acme, "status": "heard back", "expect_last": ""})
    assert status == 409 and said["detail"]["current"]["last"].endswith(" applied")
    assert _answer("PUT", "/api/applications/status", {**acme, "status": "heard back", "expect_last": 3})[0] == 400


def test_a_write_waits_for_an_update_then_says_so(repo, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.setattr(core, "WRITE_WAIT", 0.05)
    status, said = _answer("GET", "/api/health", {})
    assert said["git"] is False
    with core._git_lock:
        assert _answer("GET", "/api/health", {})[1]["git"] is True
        status, said = _answer("PUT", "/api/digests/2026-11-02/entries/1", {"apply": True})
        assert status == 409 and "update or a backup" in said["detail"]
    assert _answer("PUT", "/api/digests/2026-11-02/entries/1", {"apply": True})[0] == 200


def test_a_skip_cannot_stand_beside_an_apply_ticked_since(repo):
    seen = {"apply": False, "skip": False, "letter": False, "skip_reason": ""}
    core.mark_entry("2026-11-02", 1, apply=True)                     # elsewhere, since
    with pytest.raises(tracker.Conflict, match="apply is ticked now"):
        core.mark_entry("2026-11-02", 1, skip=True, skip_reason="too far", expect=seen, entry=ACME)
    assert "- [ ] skip" in digest_text(repo).split("### 2.")[0]
    # A letter can stand beside an apply: both stay.
    core.mark_entry("2026-11-02", 1, letter=True, expect=seen, entry=ACME)
    # Unticking apply in the same change settles it, once apply was seen ticked.
    core.mark_entry("2026-11-02", 1, skip=True, apply=False, letter=False,
                    expect={**seen, "apply": True, "letter": True})
    assert "- [x] skip — reason: too far" not in digest_text(repo)
    assert "- [x] skip" in digest_text(repo).split("### 2.")[0]


# ------------------------------------------------------------ the phone's copy
# What a phone keeps for reading while the Mac is away (ui/sw.js): the snapshot
# core.snapshot() sends, its route, and the page's files the worker saves.

def _request(method: str, path: str, headers: dict | None = None) -> tuple[int, dict, bytes]:
    """One request through the page, as uvicorn hands it over: its status,
    its headers, and what it sent."""
    import asyncio
    import server
    sent_headers = {"host": "127.0.0.1:8765", **(headers or {})}
    path, _, query = path.partition("?")
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": query.encode(), "root_path": "", "client": ("127.0.0.1", 50000),
             "server": ("127.0.0.1", 8765),
             "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in sent_headers.items()]}
    sent, asked = [], []

    async def receive():
        # The request once; after that, a connection that stays open. A file's
        # response listens for a disconnect while it sends, and must not spin.
        if not asked:
            asked.append(True)
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    asyncio.run(server.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    head = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in start["headers"]}
    return start["status"], head, b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


def test_the_snapshot_holds_what_the_phone_reads_and_nothing_else(repo):
    (repo / "content").mkdir()
    (repo / "content" / "contact.local.md").write_text("Phone: 555-0100, me@example.com\n", encoding="utf-8")
    (repo / "profile" / "profile.md").write_text("# How a role is judged\n", encoding="utf-8")
    snap = core.snapshot()
    paths = set(snap["answers"])
    assert {"/api/digests", "/api/digests/2026-11-02", "/api/digests/2026-11-02/verdicts", "/api/applications",
            "/api/profile", "/api/profile/profile/profile.md", "/api/profile/profile/feedback.md"} <= paths
    assert all(core.SNAPSHOT_PATH.match(p) for p in paths)
    assert not {p for p in paths if p.startswith(("/api/setup", "/api/commands", "/api/skills", "/api/claude",
                                                    "/api/runs", "/api/usage", "/api/copy", "/api/keys"))}
    text = json.dumps(snap["answers"])
    assert "555-0100" not in text and "me@example.com" not in text and "contact.local" not in text
    assert snap["answers"]["/api/profile/profile/profile.md"] == "# How a role is judged\n"
    assert snap["answers"]["/api/digests/2026-11-02"]["entries"][0]["company"] == "Acme Energy"
    assert "Acme Energy" in [f["company"] for f in snap["answers"]["/api/applications"]["folders"]]
    # The tag follows the files: a tick changes it, and nothing else does.
    assert core.snapshot()["etag"] == snap["etag"]
    core.mark_entry("2026-11-02", 1, apply=True)
    assert core.snapshot()["etag"] != snap["etag"]


def test_the_snapshot_route_tags_its_answer_and_spares_a_current_copy(repo):
    pytest.importorskip("fastapi")
    status, head, body = _request("GET", "/api/snapshot")
    assert status == 200 and head["etag"].startswith('"') and head["cache-control"] == "no-cache"
    snap = json.loads(body)
    assert f'"{snap["etag"]}"' == head["etag"] and "/api/digests" in snap["answers"]
    status, again, body = _request("GET", "/api/snapshot", {"if-none-match": head["etag"]})
    assert status == 304 and not body and again["etag"] == head["etag"]
    assert _request("GET", "/api/snapshot", {"if-none-match": f'W/{head["etag"]}, "other"'})[0] == 304
    assert _request("GET", "/api/snapshot", {"if-none-match": '"stale"'})[0] == 200
    # A phone that is not set up is refused, like every other route.
    assert _request("GET", "/api/snapshot", {"tailscale-user-login": "x@github"})[0] == 403
    assert _request("GET", "/sw.js", {"tailscale-user-login": "x@github"})[0] == 403


def test_the_page_and_the_worker_are_served_with_their_types_and_a_policy(repo):
    pytest.importorskip("fastapi")
    import re
    status, head, body = _request("GET", "/")
    assert status == 200 and head["content-security-policy"].startswith("default-src 'self'")
    assert b'<script src="app.js">' in body
    import icon
    status, head, body = _request("GET", "/sw.js")
    assert status == 200 and head["content-type"].startswith("text/javascript")
    assert head["cache-control"] == "no-cache" and b"self.addEventListener" in body
    sw = body.decode("utf-8")
    # The worker as served names the icons by the drawing's fingerprint (icon.stamp_worker).
    v = icon.fingerprint()
    assert f'const ICONS = "{v}";' in sw
    files = re.findall(r'"([^"]*)"', re.search(r"const FILES = \[(.*?)\]", sw).group(1))
    named = re.findall(r'"([^"]*)"', re.search(r"const NAMED = \[(.*?)\]", sw).group(1))
    assert files == ["", "app.js", "style.css"]
    # Every icon file the page names, and its manifest: none left to the Mac alone.
    assert set(named) == {*icon.FILES, "manifest.webmanifest"}
    kinds = {"/": "text/html", ".js": "text/javascript", ".css": "text/css",
             ".webmanifest": "application/manifest+json", ".png": "image/png"}
    for p in ["/" + f for f in files] + [f"/{n}?v={v}" for n in named]:
        status, head, body = _request("GET", p)
        assert status == 200 and body, p
        ext = os.path.splitext(p.partition("?")[0])[1]
        assert head["content-type"].startswith(kinds.get(p) or kinds[ext]), p
    # The page carries what the worker takes as Job Search's own (MARK).
    mark = re.search(r'const MARK = "(.*?)";', sw).group(1)
    assert mark in _request("GET", "/")[2].decode("utf-8")
    # The reads the worker keeps are the ones the snapshot sends.
    kept = re.search(r"const KEPT = /(.*)/;", sw).group(1)
    assert kept.replace("\\/", "/") == core.SNAPSHOT_PATH.pattern


def test_the_tab_icon_is_named_in_the_page_by_the_drawings_fingerprint(repo):
    """Safari keeps a tab's icon by the icon's address for good, and ignores one
    a script swaps in. So the page as served names every icon file, and its
    manifest, with ?v=<fingerprint> (icon.stamp), and a new drawing has new
    addresses: Safari went on showing the icon from before the redesign."""
    pytest.importorskip("fastapi")
    import re
    import icon
    v = icon.fingerprint()
    status, _, body = _request("GET", "/")
    page = body.decode("utf-8")
    assert status == 200
    # With a sizes attribute, Safari fetched the first icon and never another.
    assert f'<link rel="icon" type="image/png" href="favicon.png?v={v}">' in page
    assert f'href="apple-touch-icon.png?v={v}"' in page
    assert f'href="manifest.webmanifest?v={v}"' in page
    assert not re.search(r'href="[^"?]+\.(png|ico|webmanifest)"', page), "an icon without its fingerprint"

    # Under the current fingerprint a file never changes, so it is kept for good;
    # any other address, an older page's, is asked for again.
    status, head, body = _request("GET", f"/favicon.png?v={v}")
    assert status == 200 and head["content-type"] == "image/png"
    assert "immutable" in head["cache-control"] and body == icon.png(64)
    # Filled to the edge: Safari puts white behind a tab icon's clear pixels.
    assert all(not tile for _, tile in icon.FILES.values())
    status, head, body = _request("GET", "/favicon.png?v=0ld")
    assert status == 200 and head["cache-control"] == "no-cache"
    for name, (size, tile) in icon.FILES.items():
        assert _request("GET", f"/{name}?v={v}")[2] == icon.png(size, tile=tile), name
    assert _request("GET", "/nothing.png")[0] == 404

    # A browser asks for /favicon.ico where a page names no icon.
    status, head, body = _request("GET", "/favicon.ico")
    assert status == 200 and head["content-type"] == "image/x-icon" and body[:4] == b"\0\0\1\0"
    assert body == icon.ico((16, 32, 48, 64), tile=False)

    status, head, body = _request("GET", f"/manifest.webmanifest?v={v}")
    assert status == 200 and "immutable" in head["cache-control"]
    assert all(i["src"].endswith(f".png?v={v}") for i in json.loads(body)["icons"])


def test_the_icons_fingerprint_follows_the_drawing():
    import hashlib
    import icon
    with open(icon.__file__, "rb") as fh:
        assert icon.fingerprint() == hashlib.sha256(fh.read()).hexdigest()[:12]
    v = icon.fingerprint()
    page = '<link rel="icon" href="favicon.png"><a href="favicon.png.txt">'
    assert icon.stamp(page) == f'<link rel="icon" href="favicon.png?v={v}"><a href="favicon.png.txt">'


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the service worker")
def test_the_phones_copy_keeps_each_icon_by_its_fingerprint():
    """ui/sw.js, run in Node against a stand-in Mac (tests/sw_harness.js). It
    used to answer favicon.png?v=<new drawing> with the favicon.png saved at
    install, so a redesigned icon never reached a phone that had the worker."""
    r = subprocess.run(["node", os.path.join(ROOT, "tests", "sw_harness.js"),
                        os.path.join(ROOT, "ui", "sw.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    seen = json.loads(r.stdout)
    copy = "bs-job-search-1"
    assert "/favicon.png?v=a1" in seen["installed"][copy] and "/favicon.png" not in seen["installed"][copy]
    # The icon by its address, from the copy, with nothing asked of the Mac.
    assert seen["icon"]["text"] == "favicon.png drawn as a1" and seen["icon"]["asked"] == []
    # Another drawing's address, or none, is the Mac's to answer.
    assert not seen["older"]["intercepted"] and not seen["bare"]["intercepted"]
    # The icon on the home screen opens ./?from=icon: the same page, from the copy.
    assert "BS Job Search" in seen["fromIcon"]["text"]

    # A new drawing is a new worker: it saves the new icons and drops the old,
    # and keeps this phone's choices and what it saved for reading.
    assert not [u for u in seen["redrawn"][copy] if "?v=a1" in u]
    assert {"/favicon.png?v=b2", "/apple-touch-icon.png?v=b2", "/__settings", "/api/digests"} <= set(seen["redrawn"][copy])
    assert seen["newIcon"]["text"] == "favicon.png drawn as b2" and seen["newIcon"]["asked"] == []
    assert seen["touchIcon"]["text"] == "apple-touch-icon.png drawn as b2"
    assert not seen["oldIcon"]["intercepted"]
    assert seen["settings"] == {"profile": False, "documents": False}
    # No icon refresh tells the page its code changed, which reloads it.
    assert "page" not in seen["told"]

    # Another app's page at this address: the copy and the worker go.
    assert seen["unregistered"] and "forgotten" in seen["told"]
    assert seen["left"] == {} and not seen["afterTakeover"]["intercepted"]


def test_the_phones_choices_default_to_profile_kept_and_documents_not():
    """Phase 4 (ui/sw.js): the profile files' text is kept unless turned off,
    filed documents, which carry contact details, only when turned on and only
    those filed in the last 30 days, in a cache of their own that a new
    version of the worker does not throw away."""
    import re
    with open(os.path.join(ROOT, "ui", "sw.js"), encoding="utf-8") as fh:
        sw = fh.read()
    assert "const DEFAULTS = { profile: true, documents: false };" in sw
    assert "const DAYS = 30;" in sw
    assert "name !== CACHE && name !== DOCS" in sw
    doc = re.compile(re.search(r"const DOC = /(.*)/;", sw).group(1).replace("\\/", "/"))
    # The paths app.js's fileUrl() makes, one level down inside a `_` folder too.
    assert doc.match("/api/applications/Acme%20Energy/Project%20Engineer.pdf")
    assert doc.match("/api/applications/_Not%20employers%2FSent%20to%20a%20friend/Resume.pdf")
    assert not doc.match("/api/applications") and not doc.match("/api/applications/status/x/y")

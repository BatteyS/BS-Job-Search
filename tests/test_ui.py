"""The local page's reads and writes, through ui/core.py: marking a digest in
place, the verdicts gate, the Applications listing, and the file guards. The
routes in ui/server.py are thin over these; the check in front of them, which
refuses other hosts and other sites, is also tried through the app itself."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys

import pytest
import yaml

from helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "ui"))
import core  # noqa: E402
import digest_applies  # noqa: E402
import doctor  # noqa: E402

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
    apps = core.list_applications()
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
    assert [c["name"] for c in runs.commands()] == ["doctor", "applies", "fetch"]
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


def _ask(app, method: str, path: str, headers: dict) -> int:
    """One request through the app, as uvicorn hands it over. Returns the status."""
    import asyncio
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "root_path": "", "client": ("127.0.0.1", 50000),
             "server": ("127.0.0.1", 8765),
             "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

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

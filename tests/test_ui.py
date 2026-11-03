"""The local page's reads and writes, through ui/core.py: marking a digest in
place, the verdicts gate, the Applications listing, and the file guards. The
routes in ui/server.py are thin over these, and need the `ui` extra, which the
tests do not."""

from __future__ import annotations

import os
import sys

import pytest

from helpers import ROOT

sys.path.insert(0, os.path.join(ROOT, "ui"))
import core  # noqa: E402
import digest_applies  # noqa: E402

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

"""The template export: what is shared, and the personal-data check."""

from __future__ import annotations

import json
import os
import re
import sys

import pytest

from helpers import ROOT, run
import export_template as x

sys.path.insert(0, os.path.join(ROOT, "ui"))
import core  # noqa: E402

PRIVATE = ["profile/profile.md", "profile/filters.yaml", "profile/applications.yaml",
           "content/master.md",
           "content/story.md", "content/contact.local.md", "CLAUDE.local.md",
           "digests/2026-08-12.md", "data/seen.sqlite", "sources/companies.yaml",
           "sources/seed_companies.txt", "sources/adzuna.local.yaml",
           "Applications/Acme/Analyst.pdf", "Resume/.vscode/settings.json"]
SHARED = ["scripts/fetch_jobs.py", ".claude/skills/setup/SKILL.md", "presets/metros.yaml",
          "examples/nurse-sacramento/master.md", "content/story.example.md", "LICENSE",
          "Resume/LaTeX/template.tex", "tests/test_export.py", "scripts/tracker.py",
          "examples/nurse-sacramento/demo/applications.yaml"]


@pytest.mark.parametrize("path", PRIVATE)
def test_a_profile_is_never_shared(path):
    assert not x.is_engine(path)


@pytest.mark.parametrize("path", SHARED)
def test_the_engine_is_shared(path):
    assert x.is_engine(path)


def check(tmp_path, name: str, text: str, terms=()) -> list[str]:
    (tmp_path / name).write_text(text, encoding="utf-8")
    rxs = [(label, re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.I)) for label, t in terms]
    return x.scan(str(tmp_path), [name], rxs)


def test_it_finds_an_email_a_phone_and_a_name(tmp_path):
    # Assembled here, so this file does not itself trip the check it tests.
    email, phone = "pat.lee" + "@" + "gmail.com", "(415) 867" + "-5309"
    hits = check(tmp_path, "notes.md",
                 f"Write to {email}\nor call {phone}\nThanks, Pat Lee\n",
                 terms=[("your name", "Pat Lee")])
    assert [h.split(":")[1] for h in hits] == ["1", "2", "3"], hits


def test_it_lets_the_placeholders_through(tmp_path):
    assert check(tmp_path, "contact.example.md",
                 "email: you@example.com\nphone: (555) 555-5555\n"
                 "git clone git@github.com:owner/repo.git\n") == []


def test_only_the_license_may_name_its_holder(tmp_path):
    terms = [("your name", "Pat Lee")]
    assert check(tmp_path, "LICENSE", "Copyright (c) 2026 Pat Lee\n", terms) == []
    assert check(tmp_path, "README.md", "Copyright (c) 2026 Pat Lee\n", terms) != []


def record_phone_access(tmp_path, monkeypatch, text: str) -> None:
    """Phone access recorded as `text`, in a copy that is otherwise empty."""
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / x.REMOTE).write_text(text, encoding="utf-8")
    monkeypatch.setattr(x, "ROOT", str(tmp_path))


def test_it_finds_this_macs_tailnet_address_and_login(tmp_path, monkeypatch):
    """A GitHub login is no email address, so only the recorded login finds it.
    Each name in the address is looked for alone, and only this Mac's: the
    phone tests' made-up address goes through."""
    # The file the check reads is the one ui/phone.py writes.
    assert os.path.normpath(os.path.join(ROOT, x.REMOTE)) == os.path.normpath(core.REMOTE)
    record_phone_access(tmp_path, monkeypatch, json.dumps(
        {"host": "jordans-mbp.tail7e3a91.ts.net", "login": "jordan@github", "port": 8765}))
    (tmp_path / "notes.md").write_text(
        "Open https://jordans-mbp.tail7e3a91.ts.net/ on the phone\n"
        "Tailscale is signed in as jordan@github\n"
        "This Mac is Jordans-MBP\n"
        "on the tailnet tail7e3a91\n"
        "The phone tests use averys-mac.tail1234.ts.net\n", encoding="utf-8")
    hits = x.scan(str(tmp_path), ["notes.md"], x.personal_terms())
    assert sorted({h.split(":")[1] for h in hits}) == ["1", "2", "3", "4"], hits


def test_phone_access_it_cannot_read_stops_the_check(tmp_path, monkeypatch):
    record_phone_access(tmp_path, monkeypatch, '{"host": "jordans-mbp.tail7e')
    with pytest.raises(SystemExit, match="ui-remote.json cannot be read"):
        x.personal_terms()
    os.remove(tmp_path / x.REMOTE)                  # never set up: nothing to look for
    assert x.personal_terms() == []


def test_this_copy_passes():
    code, out = run("export_template", "--check")
    assert code == 0, out


def test_the_readme_checks_out_what_the_template_ships():
    """README's update for a copy with no shared history lists the paths to take
    from the template: every ENGINE pattern, and nothing else."""
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    command = re.search(r"git checkout template/main -- (.*?)\n```", readme, re.S)
    assert command, "README has no checkout command"
    listed = command.group(1).replace("\\\n", " ").split()
    bases = [p[:-2] if p.endswith("/*") else p for p in x.ENGINE]
    for base in bases:
        assert any(base == p or base.startswith(p + "/") for p in listed), base
    for p in listed:
        assert any(base == p or base.startswith(p + "/") for base in bases), p

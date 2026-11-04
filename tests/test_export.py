"""The template export: what is shared, and the personal-data check."""

from __future__ import annotations

import re

import pytest

from helpers import run
import export_template as x

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


def test_this_copy_passes():
    code, out = run("export_template", "--check")
    assert code == 0, out

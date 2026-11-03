"""doctor.py on a fresh copy, and the advice it gives."""

from __future__ import annotations

import importlib.util
import os
import shutil

import doctor
from helpers import ROOT, run

# What a fresh copy of the workflow holds before /setup: the engine, no profile.
ENGINE = ["scripts", "presets", "Resume/LaTeX", "content/contact.example.md",
          "content/story.example.md", "sources/adzuna.example.yaml",
          "sources/usajobs.example.yaml", "pyproject.toml"]


def fresh_copy(path) -> None:
    for item in ENGINE:
        src, dst = os.path.join(ROOT, item), path / item
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)


def test_a_fresh_copy_points_to_setup(tmp_path):
    fresh_copy(tmp_path)
    code, out = run("doctor", cwd=str(tmp_path))
    assert code == 1, out
    assert "Traceback" not in out
    for missing in ("content/master.md", "profile/profile.md", "profile/clusters.yaml",
                    "profile/filters.yaml"):
        line = next(ln for ln in out.splitlines() if missing in ln)
        assert line.split()[0] == "MISSING", line
    assert "run /setup in Claude Code" in out


def test_a_setup_draft_reads_as_a_draft(tmp_path):
    fresh_copy(tmp_path)
    (tmp_path / "content/story.md").write_text(
        f"{doctor.DRAFT}\n\n# Why this field\n\nA sentence.\n", encoding="utf-8")
    _, out = run("doctor", cwd=str(tmp_path))
    line = next(ln for ln in out.splitlines() if "content/story.md" in ln)
    assert line.split()[0] == "DRAFT", line


def test_a_uv_fix_keeps_the_extras_already_installed(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(doctor.importlib.util, "find_spec",
                        lambda name, *a: object() if name == "jobspy" else
                        (None if name == "pypdf" else real(name, *a)))
    assert doctor.uv_sync("pdf") == "uv sync --extra pdf --extra scraped"
    assert doctor.uv_sync() == "uv sync --extra scraped"


def test_the_draft_marker_matches_the_setup_skill():
    skill = open(os.path.join(ROOT, ".claude/skills/setup/SKILL.md"), encoding="utf-8").read()
    assert doctor.DRAFT in skill

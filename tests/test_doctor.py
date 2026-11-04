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


def test_a_uv_fix_keeps_the_extra_already_installed(monkeypatch):
    real = importlib.util.find_spec
    installed = {"jobspy": True}
    monkeypatch.setattr(doctor.importlib.util, "find_spec",
                        lambda name, *a: (object() if installed[name] else None)
                        if name in installed else real(name, *a))
    assert doctor.uv_sync() == "uv sync --extra scraped"
    installed["jobspy"] = False
    assert doctor.uv_sync() == "uv sync"
    assert doctor.uv_sync("scraped") == "uv sync --extra scraped"


def test_the_checks_say_which_check_made_each_row(tmp_path, monkeypatch):
    fresh_copy(tmp_path)
    monkeypatch.setattr(doctor, "ROOT", str(tmp_path))
    rows = doctor.run_checks(page=False)
    groups = [r["group"] for r in rows]
    assert groups == sorted(groups, key=["python", "latex", "profile", "sources"].index)
    assert {"python", "latex", "profile"} <= set(groups)
    master = next(r for r in rows if r["what"] == "content/master.md")
    assert master["group"] == "profile" and master["status"] == "MISSING"
    assert doctor.run_checks(page=False) == rows   # a second run starts clean


def test_the_tracker_is_optional_until_it_breaks(tmp_path, monkeypatch):
    fresh_copy(tmp_path)
    monkeypatch.setattr(doctor, "ROOT", str(tmp_path))

    def row() -> dict:
        return next(r for r in doctor.run_checks(page=False)
                    if r["what"] == os.path.join("profile", "applications.yaml"))

    assert row()["status"] == "optional"
    path = tmp_path / "profile" / "applications.yaml"
    path.parent.mkdir()
    path.write_text("applications:\n- company: Acme\n  history: [2026-10-02 applied]\n",
                    encoding="utf-8")
    assert (row()["status"], row()["detail"]) == ("ok", "1 application")
    path.write_text("applications: [\n", encoding="utf-8")
    assert row()["status"] == "MISSING" and "does not load" in row()["detail"]


def test_the_draft_marker_matches_the_setup_skill():
    skill = open(os.path.join(ROOT, ".claude/skills/setup/SKILL.md"), encoding="utf-8").read()
    assert doctor.DRAFT in skill

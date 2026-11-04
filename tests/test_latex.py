"""scripts/latex.py finds the TeX that can build the templates wherever it is
installed, and doctor.py says how to install it without a password. Each TeX
here is a folder of fake programs: pdflatex, and a kpsewhich that knows some
of the files the templates load."""

from __future__ import annotations

import os
import sys

import pytest

import doctor
import latex

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fakes are shell scripts")


@pytest.fixture(autouse=True)
def no_system_tex(monkeypatch):
    """Only the fakes: whatever TeX this machine has stays out of it."""
    monkeypatch.setattr(latex, "system_dirs", lambda system: [])


def fake_tex(folder, knows=latex.FILES, kpsewhich=True) -> str:
    """A TeX bin folder whose kpsewhich finds the files in `knows`."""
    os.makedirs(folder, exist_ok=True)
    pdflatex = os.path.join(folder, "pdflatex")
    with open(pdflatex, "w") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(pdflatex, 0o755)
    if kpsewhich:
        kpse = os.path.join(folder, "kpsewhich")
        cases = "".join(f"    {f}) echo /tex/{f} ;;\n" for f in knows)
        with open(kpse, "w") as fh:
            fh.write("#!/bin/sh\nfor f in \"$@\"; do\n  case $f in\n" + cases + "  esac\ndone\n")
        os.chmod(kpse, 0o755)
    return pdflatex


def test_a_complete_tex_wins_over_one_earlier_on_path(tmp_path):
    partial = fake_tex(tmp_path / "basictex", knows=["geometry.sty", "hyperref.sty"])
    complete = fake_tex(tmp_path / "full")
    path = os.pathsep.join([str(tmp_path / "basictex"), str(tmp_path / "full")])
    assert latex.find(path=path, system="Linux", home=str(tmp_path)) == (complete, [])
    exe, missing = latex.find(path=str(tmp_path / "basictex"), system="Linux", home=str(tmp_path))
    assert exe == partial
    assert "newtx" in missing and "kastrup" in missing and "geometry" not in missing


def test_tinytex_is_found_without_path_naming_it(tmp_path):
    exe = fake_tex(tmp_path / "Library" / "TinyTeX" / "bin" / "universal-darwin")
    assert latex.find(path="", system="Darwin", home=str(tmp_path)) == (exe, [])
    assert latex.is_tinytex(exe, system="Darwin", home=str(tmp_path))
    assert latex.tool("kpsewhich", exe).endswith("kpsewhich")
    assert latex.tool("tlmgr", exe) is None


def test_no_tex_at_all(tmp_path):
    assert latex.find(path=str(tmp_path), system="Linux", home=str(tmp_path)) == (
        None, latex.PACKAGES)


def test_without_kpsewhich_nothing_is_called_missing(tmp_path):
    exe = fake_tex(tmp_path / "bin", kpsewhich=False)
    assert latex.find(path=str(tmp_path / "bin"), system="Linux", home=str(tmp_path)) == (exe, [])


def test_doctor_points_a_mac_at_the_no_password_install(monkeypatch):
    monkeypatch.setattr(doctor, "OS", "Darwin")
    monkeypatch.setattr(latex, "find", lambda: (None, latex.PACKAGES))
    rows = doctor.run_checks(page=False)
    row = next(r for r in rows if r["group"] == "latex")
    assert row["status"] == "MISSING"
    assert "install_latex.py" in row["fix"] and "sudo" not in row["fix"]


def test_doctor_says_what_a_system_tex_lacks(monkeypatch, tmp_path):
    exe = fake_tex(tmp_path / "texbin", knows=["geometry.sty"])
    monkeypatch.setattr(doctor, "OS", "Darwin")
    monkeypatch.setattr(latex, "find", lambda: (exe, ["newtx", "titlesec"]))
    rows = [r for r in doctor.run_checks(page=False) if r["group"] == "latex"]
    assert rows[1]["status"] == "MISSING" and rows[1]["detail"] == "newtx, titlesec"
    # A system TeX's tlmgr needs sudo, so the no-password way comes first.
    assert rows[1]["fix"].index("install_latex.py") < rows[1]["fix"].index("sudo")

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


def test_the_list_covers_what_newtxtext_loads():
    """newtxtext.sty's own \\RequirePackage lines, wherever a TeX here has it:
    each needs a file the check looks for, or a fresh TinyTeX misses it."""
    import re
    import subprocess
    found = [d for d in latex.bin_dirs() if os.path.isfile(os.path.join(d, "kpsewhich"))]
    if not found:
        pytest.skip("no TeX here to read newtxtext.sty from")
    path = subprocess.run([os.path.join(found[0], "kpsewhich"), "newtxtext.sty"],
                          capture_output=True, text=True).stdout.strip()
    if not path:
        pytest.skip("this TeX has no newtxtext.sty")
    wanted = set()
    for line in open(path, encoding="utf-8", errors="replace"):
        if line.lstrip().startswith("%"):
            continue
        m = re.match(r"\s*\\RequirePackage(\[[^]]*\])?\{([^}]*)\}", line)
        if m and not m.group(1):     # an optioned load is fontspec, for xelatex and lualatex
            wanted |= {p.strip() for p in m.group(2).split(",")}
    in_kernel = {"ifthen", "textcomp", "mweights", "fontspec"}
    have = {f.rsplit(".", 1)[0] for f in latex.FILES}
    assert wanted - in_kernel <= have, f"latex.FILES misses {sorted(wanted - in_kernel - have)}"


def test_tinytex_is_asked_for_no_path_after_its_folder(monkeypatch):
    import install_latex
    calls = []
    monkeypatch.setattr(install_latex.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(install_latex, "run", lambda argv, **kw: calls.append(argv) or 0)
    assert install_latex.install_tinytex()
    script = calls[0][calls[0].index("-o") + 1]
    assert calls[1] == ["sh", script, os.path.dirname(script), "--no-path"]


def test_a_file_the_test_page_lacks_is_found_and_added(monkeypatch):
    import subprocess
    import install_latex
    builds = iter([(False, "! LaTeX Error: File `xpatch.sty' not found.\n"), (True, "")])
    monkeypatch.setattr(install_latex, "test_build", lambda exe: next(builds))
    monkeypatch.setattr(install_latex.latex, "tool", lambda name, exe=None: "/tiny/bin/tlmgr")
    index = "tlmgr: package repository https://mirror.example (not verified)\nxpatch:\n\ttexmf-dist/tex/latex/xpatch/xpatch.sty\n"
    monkeypatch.setattr(install_latex.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, index, ""))
    added = []
    monkeypatch.setattr(install_latex, "tlmgr_install", lambda tlmgr, pkgs: added.extend(pkgs) or True)
    assert install_latex.ready("/tiny/bin/pdflatex", can_add=True) == 0
    assert added == ["xpatch"]
    # A system TeX is not changed: the user is told what it lacks.
    builds = iter([(False, "! LaTeX Error: File `scalefnt.sty' not found.\n")])
    monkeypatch.setattr(install_latex, "test_build", lambda exe: next(builds))
    assert install_latex.ready("/Library/TeX/texbin/pdflatex", can_add=False) == 1

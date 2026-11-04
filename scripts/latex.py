"""Find the pdflatex that can build the resume and letter templates.

LaTeX can be on PATH, in TinyTeX in your own folder (what
scripts/install_latex.py installs, with no password), or in MacTeX or BasicTeX
under /Library/TeX/texbin. Each place is looked in whether or not PATH names
it, so a page or a terminal started before LaTeX was installed still finds it,
and a TeX that lacks the templates' packages loses to one that has them.

    from latex import find
    pdflatex, missing = find()   # a path, and the CTAN packages it still lacks

doctor.py and the builders use it, and install_latex.py decides from it what
to install.
"""

from __future__ import annotations

import glob
import os
import platform
import shutil
import subprocess

# The file each template needs, by the CTAN package that provides it: what
# template.tex and letter.tex load, and what newtxtext.sty loads in turn
# (fontaxes, xstring, and kastrup's binhex.tex), which BasicTeX and TinyTeX
# both leave out.
FILES = {
    "geometry.sty": "geometry", "newtxtext.sty": "newtx", "fontaxes.sty": "fontaxes",
    "xstring.sty": "xstring", "binhex.tex": "kastrup", "enumitem.sty": "enumitem",
    "hyperref.sty": "hyperref", "titlesec.sty": "titlesec", "tgtermes.sty": "tex-gyre",
}
# What tlmgr installs to provide them. One already there is skipped.
PACKAGES = sorted(set(FILES.values()))

EXE = ".exe" if platform.system() == "Windows" else ""


def tinytex_root(system: str | None = None, home: str | None = None) -> str:
    """Where TinyTeX installs for this user, by its own installer's default."""
    system = system or platform.system()
    home = home or os.path.expanduser("~")
    if system == "Darwin":
        return os.path.join(home, "Library", "TinyTeX")
    if system == "Windows":
        return os.path.join(os.environ.get("APPDATA") or home, "TinyTeX")
    return os.path.join(home, ".TinyTeX")


def system_dirs(system: str) -> list[str]:
    """Where a system-wide TeX keeps its programs: MacTeX's and BasicTeX's
    /Library/TeX/texbin, TeX Live's own folders, and MiKTeX's on Windows,
    which a page started before MiKTeX was installed has not got on PATH."""
    if system == "Windows":
        return [os.path.join(os.environ.get(v, ""), *rel) for v, rel in (
            ("LOCALAPPDATA", ("Programs", "MiKTeX", "miktex", "bin", "x64")),
            ("ProgramFiles", ("MiKTeX", "miktex", "bin", "x64"))) if os.environ.get(v)]
    out = ["/Library/TeX/texbin"] if system == "Darwin" else []
    return out + sorted(glob.glob("/usr/local/texlive/*/bin/*"), reverse=True)


def bin_dirs(path: str | None = None, system: str | None = None,
             home: str | None = None) -> list[str]:
    """Every folder that may hold pdflatex, in the order they are tried: PATH
    first, as a terminal would, then TinyTeX, then the system TeX folders."""
    system = system or platform.system()
    path = os.environ.get("PATH", "") if path is None else path
    out = [d for d in path.split(os.pathsep) if d]
    out += sorted(glob.glob(os.path.join(tinytex_root(system, home), "bin", "*")))
    out += system_dirs(system)
    seen, dirs = set(), []
    for d in out:
        key = os.path.normcase(os.path.abspath(d))
        if key not in seen:
            seen.add(key)
            dirs.append(d)
    return dirs


def missing_in(bindir: str) -> list[str]:
    """The CTAN packages the TeX in `bindir` lacks, by asking its kpsewhich for
    every file at once. Without a kpsewhich nothing can be checked, so nothing
    is reported missing: the first build says what is."""
    kpse = os.path.join(bindir, "kpsewhich" + EXE)
    if not os.path.isfile(kpse):
        return []
    try:
        r = subprocess.run([kpse, *FILES], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    found = {os.path.basename(line.strip()) for line in r.stdout.splitlines() if line.strip()}
    return sorted({pkg for f, pkg in FILES.items() if f not in found})


def find(path: str | None = None, system: str | None = None,
         home: str | None = None) -> tuple[str | None, list[str]]:
    """(pdflatex, missing packages): the first pdflatex whose TeX has every
    package, or else the first one found, with what it lacks; (None, every
    package) when there is none at all. Looked up afresh on every call, never
    remembered, so a page that is running sees a LaTeX installed meanwhile."""
    first: tuple[str | None, list[str]] = (None, list(PACKAGES))
    for d in bin_dirs(path, system, home):
        exe = os.path.join(d, "pdflatex" + EXE)
        if not os.path.isfile(exe) or not os.access(exe, os.X_OK):
            continue
        missing = missing_in(d)
        if not missing:
            return exe, []
        if first[0] is None:
            first = (exe, missing)
    return first


def pdflatex() -> str:
    """The pdflatex to build with: the best find() has, else the bare name, so
    a missing LaTeX fails with the usual not-found error."""
    return find()[0] or shutil.which("pdflatex") or "pdflatex"


def tool(name: str, exe: str | None = None) -> str | None:
    """Another program from the same TeX as `exe` (default: find()'s), such as
    tlmgr, or None when that TeX lacks it."""
    exe = exe or find()[0]
    if not exe:
        return None
    path = os.path.join(os.path.dirname(exe), name + EXE)
    return path if os.path.isfile(path) else None


def is_tinytex(exe: str | None, system: str | None = None, home: str | None = None) -> bool:
    """Whether `exe` is the user's own TinyTeX, which tlmgr changes without sudo."""
    if not exe:
        return False
    root = os.path.realpath(tinytex_root(system, home))
    return os.path.realpath(exe).startswith(root + os.sep)

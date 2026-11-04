"""Install LaTeX, which typesets resumes and letters, without a password.

    python scripts/install_latex.py            # install what is missing
    python scripts/install_latex.py --check    # say what is here, change nothing

What it does depends on what this machine already has:

  * a TeX with every package the templates load: nothing;
  * TinyTeX of your own that lacks some of them: adds them with its tlmgr;
  * no TeX at all, or MacTeX or BasicTeX without them, whose tlmgr needs sudo:
    installs TinyTeX with TinyTeX's own installer (yihui.org/tinytex), into
    your own folder (~/Library/TinyTeX on a Mac, ~/.TinyTeX on Linux), then
    adds the packages. An existing TeX is left as it is.

Nothing is written outside your home folder, so nothing asks for a password,
which is what lets the page's Setup tab run it, and install.sh. Builds find
TinyTeX without PATH naming it (scripts/latex.py), so nothing needs restarting
afterwards. It ends by building a test page, the real proof that the fonts
work. Windows has MiKTeX for this instead, which fetches packages as a build
asks for them.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import latex  # noqa: E402

# TinyTeX's installer for macOS and Linux, from its own repository. It
# downloads TinyTeX-1, a TeX Live of about 64 MB with the packages most
# documents use, and --no-path keeps it from touching /usr/local/bin or
# /etc/paths.d, which would need sudo.
INSTALLER = "https://raw.githubusercontent.com/rstudio/tinytex/main/tools/install-bin-unix.sh"

# A page with the templates' preamble: building it proves the packages load
# and their fonts are set up, which finding the files alone does not.
TEST_PAGE = r"""\documentclass[11pt]{article}
\usepackage[top=0.5in, bottom=0.5in, left=0.5in, right=0.5in]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{newtxtext}
\usepackage{enumitem}
\usepackage{hyperref}
\usepackage{titlesec}
\begin{document}
\section*{Test}
\begin{itemize}[leftmargin=*]
\item R\&D, 40\%, \textbf{bold} and \textit{italic}.
\end{itemize}
\end{document}
"""

WINDOWS = ("On Windows, install MiKTeX from miktex.org/download and let it install missing "
           "packages on the fly when its installer asks: the first resume build then fetches "
           "what it needs.")


def say(text: str = "") -> None:
    print(text, flush=True)


def run(argv: list[str], **kw) -> int:
    """Run a command with its output streamed, as the page shows it."""
    say("$ " + " ".join(argv))
    try:
        return subprocess.run(argv, **kw).returncode
    except OSError as exc:
        say(f"could not run {argv[0]}: {exc}")
        return 127


def tinytex_pdflatex(root: str) -> str | None:
    """TinyTeX's pdflatex, in bin/<platform>/ under its folder, if it has one."""
    bins = os.path.join(root, "bin")
    for platform_dir in sorted(os.listdir(bins)) if os.path.isdir(bins) else []:
        exe = os.path.join(bins, platform_dir, "pdflatex" + latex.EXE)
        if os.path.isfile(exe):
            return exe
    return None


def install_tinytex() -> bool:
    """TinyTeX's own installer, downloaded first, so a cut-off download is
    never run."""
    if not shutil.which("curl"):
        say("curl is missing, and TinyTeX's installer needs it.")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "install-bin-unix.sh")
        if run(["curl", "-fsSL", "--retry", "2", "-o", script, INSTALLER]) != 0:
            say("Could not download TinyTeX's installer. Check the internet connection, "
                "then try again.")
            return False
        return run(["sh", script, "--no-path"]) == 0


def tlmgr_install(tlmgr: str, packages: list[str]) -> bool:
    """Add packages with tlmgr. A tlmgr older than its repository refuses to
    install anything until it has updated itself, so that comes first when it
    asks."""
    def attempt() -> tuple[int, str]:
        say("$ " + " ".join([tlmgr, "install", *packages]))
        p = subprocess.run([tlmgr, "install", *packages], capture_output=True, text=True,
                           errors="replace")
        out = (p.stdout or "") + (p.stderr or "")
        say(out.rstrip())
        return p.returncode, out

    code, out = attempt()
    if code != 0 and "update --self" in out:
        say("tlmgr has to update itself first.")
        if run([tlmgr, "update", "--self"]) == 0:
            code, out = attempt()
    if code != 0 and ("not compatible" in out or "ross release" in out):
        say(f"This TinyTeX is from an earlier year's TeX Live, which tlmgr cannot update across. "
            f"Rename the folder {latex.tinytex_root()} (to keep it) or delete it, then run "
            f"this again for a current one.")
    return code == 0


def test_build(exe: str) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        tex = os.path.join(tmp, "test.tex")
        with open(tex, "w", encoding="utf-8") as fh:
            fh.write(TEST_PAGE)
        try:
            p = subprocess.run([exe, "-interaction=nonstopmode", "-halt-on-error",
                                "-output-directory", tmp, tex],
                               capture_output=True, text=True, errors="replace", timeout=180)
        except (OSError, subprocess.SubprocessError) as exc:
            say(f"pdflatex did not run: {exc}")
            return False
        if os.path.isfile(os.path.join(tmp, "test.pdf")):
            return True
        errors = [ln for ln in p.stdout.splitlines() if ln.startswith("!") or ".tex:" in ln]
        say("\n".join(errors[:12]) or p.stdout[-1500:])
        return False


def describe(exe: str | None, missing: list[str]) -> str:
    if not exe:
        return "No LaTeX on this machine."
    kind = "TinyTeX" if latex.is_tinytex(exe) else "LaTeX"
    return (f"{kind} at {exe}" + (f", without {', '.join(missing)}" if missing else
                                   ", with every package the templates use"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="say what is here, change nothing")
    args = ap.parse_args(argv)

    exe, missing = latex.find()
    say(describe(exe, missing))
    if exe and not missing:
        if test_build(exe):
            say("LaTeX is ready: it built a test page.")
            return 0
        say("It has every package, but the test page did not build: see above.")
        return 1
    if args.check:
        return 1
    if platform.system() == "Windows":
        say(WINDOWS)
        return 1

    root = latex.tinytex_root()
    tiny = tinytex_pdflatex(root)
    if not tiny:
        if os.path.exists(root):
            say(f"{root} is there but holds no pdflatex. Rename it (to keep it) or delete it, "
                f"then run this again.")
            return 1
        say(f"\nInstalling TinyTeX into {root}: about 64 MB, so a few minutes. "
            "It asks for no password.")
        if not install_tinytex():
            say("TinyTeX did not install: see above.")
            return 1
        tiny = tinytex_pdflatex(root)
        if not tiny:
            say(f"TinyTeX's installer finished, but {root} holds no pdflatex.")
            return 1

    tlmgr = latex.tool("tlmgr", tiny)
    if not tlmgr:
        say(f"TinyTeX at {root} has no tlmgr to add packages with.")
        return 1
    say(f"\nAdding the packages the templates use: {', '.join(latex.PACKAGES)}")
    if not tlmgr_install(tlmgr, latex.PACKAGES):
        say("tlmgr could not add them: see above.")
        return 1

    exe, missing = latex.find()
    say("\n" + describe(exe, missing))
    if not exe or missing:
        return 1
    if not test_build(exe):
        say("The packages are in, but the test page did not build: see above.")
        return 1
    say("LaTeX is ready: it built a test page. Resumes and letters can be built now, "
        "with nothing to restart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""What the tests share: the repo root, scripts/ on the import path, a way to
run a script the way a user would, and a mark for tests that need LaTeX.

No test reads a user's own profile or touches the network. Profiles come from
examples/ or are written to a temporary folder.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
EXAMPLES = os.path.join(ROOT, "examples")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import latex  # noqa: E402

needs_latex = pytest.mark.skipif(latex.find()[0] is None, reason="pdflatex is not installed")


def example(name: str, file: str) -> str:
    return os.path.join(EXAMPLES, name, file)


def run(script: str, *args: str, cwd: str = ROOT) -> tuple[int, str]:
    """Run scripts/<script>.py with this Python. Returns (exit code, output)."""
    r = subprocess.run([sys.executable, os.path.join(cwd, "scripts", f"{script}.py"), *args],
                       capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout + r.stderr

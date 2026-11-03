"""Copy the shareable part of this workflow into a new folder, and check that
nothing personal goes with it.

    python scripts/export_template.py ../job-search-template
    python scripts/export_template.py --check

What is shared is the engine: scripts, skills, presets, templates, examples,
tests, and docs -- ENGINE below. A profile never is: profile/, content/master.md
and story.md, contact details, API keys, digests, applications, and the company
lists in sources/. Only files git tracks are exported, and only once they are
committed, so the export is a commit and not whatever happens to be on disk.

Before anything is written, every file that would be shared is checked for
personal data:

  * email addresses, apart from example.com ones;
  * phone numbers, apart from the 555 numbers in the examples;
  * the name, email, phone, and links in content/contact.local.md, and the
    employers and schools in content/master.md, when those files exist.

A hit stops the export and names the file and line. `--check` runs the same
check on this copy without writing anything, untracked engine files included;
CI runs it on every push.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_resume import parse_master  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# What a copy of the workflow is made of. Everything else stays private.
ENGINE = [
    ".claude/settings.json", ".claude/skills/*", ".github/*",
    ".gitattributes", ".gitignore", ".python-version",
    "ARCHITECTURE.md", "CLAUDE.md", "LICENSE", "README.md",
    "pyproject.toml", "uv.lock", "scan.ps1", "sync.ps1",
    "content/contact.example.md", "content/story.example.md",
    "examples/*", "presets/*", "scripts/*", "tests/*", "ui/*",
    "sources/adzuna.example.yaml", "sources/usajobs.example.yaml",
    "Resume/LaTeX/template.tex", "Resume/LaTeX/letter.tex",
]

# A line that may name a person: the copyright holder.
ALLOWED_LINES = {"LICENSE": re.compile(r"^Copyright \(c\) ")}
# Machine-written files that hold only hashes and versions.
NOT_SCANNED = {"uv.lock"}

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SAFE_EMAIL = re.compile(r"@example\.(com|org|net)$|^git@github\.com$", re.I)
PHONE = re.compile(r"(?<![\d.])\(?(\d{3})\)?[ .-](\d{3})[ .-]\d{4}(?![\d.])")


def is_engine(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in ENGINE)


def git_files(*args: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", *args], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return [p for p in out.splitlines() if p and is_engine(p)
            and os.path.isfile(os.path.join(ROOT, p))]


def personal_terms() -> list[tuple[str, re.Pattern]]:
    """(what it is, pattern) for everything that would identify this copy's
    user, read from their own files."""
    found: list[tuple[str, str]] = []
    contact = os.path.join(ROOT, "content/contact.local.md")
    if os.path.exists(contact):
        front, _ = parse_master(contact)
        for key in ("name", "email", "phone", "linkedin", "github", "website", "portfolio"):
            value = str(front.get(key) or "").strip()
            if value:
                found.append((f"your {key}", value))
        for part in str(front.get("name") or "").split():
            if len(part) >= 3:
                found.append(("a part of your name", part))
    master = os.path.join(ROOT, "content/master.md")
    if os.path.exists(master):
        _, entries = parse_master(master)
        for e in entries:
            # Bare-bullet sections (Skills) have no heading to name anyone.
            if e.meta.get("list"):
                continue
            if e.employer and len(e.employer) >= 3:
                kind = e.section.lower()
                found.append((f"{'an' if kind[:1] in 'aeiou' else 'a'} {kind} entry in "
                              "master.md", e.employer))
    return [(label, re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.I))
            for label, term in found]


def scan(base: str, files: list[str],
         terms: list[tuple[str, re.Pattern]]) -> list[str]:
    """Every line in `files` that carries personal data, as 'path:line: what'."""
    hits = []
    for rel in files:
        for label, rx in terms:
            if rx.search(rel):
                hits.append(f"{rel}: the path holds {label}")
        if rel in NOT_SCANNED:
            continue
        try:
            with open(os.path.join(base, rel), encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except UnicodeDecodeError:
            continue                                # binary: nothing to read
        allowed = ALLOWED_LINES.get(rel)
        for n, line in enumerate(lines, 1):
            if allowed and allowed.search(line):
                continue
            for m in EMAIL.finditer(line):
                if not SAFE_EMAIL.search(m.group()):
                    hits.append(f"{rel}:{n}: an email address, {m.group()}")
            for m in PHONE.finditer(line):
                if "555" not in m.groups():
                    hits.append(f"{rel}:{n}: a phone number, {m.group()}")
            for label, rx in terms:
                if rx.search(line):
                    hits.append(f"{rel}:{n}: {label}")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dest", nargs="?", help="a new, empty folder to export into")
    ap.add_argument("--check", action="store_true",
                    help="check this copy's engine files and write nothing")
    args = ap.parse_args()
    if not args.check and not args.dest:
        ap.error("give a folder to export into, or --check")

    if args.check:
        files = git_files("--cached", "--others", "--exclude-standard")
    else:
        files = git_files()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", *files], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        if dirty:
            raise SystemExit("These engine files have uncommitted changes; commit them "
                             "first, so the export matches a commit:\n" + dirty)

    hits = scan(ROOT, files, personal_terms())
    if hits:
        print("Personal data in files that would be shared:", file=sys.stderr)
        for h in hits:
            print(f"  {h}", file=sys.stderr)
        return 1
    if args.check:
        print(f"{len(files)} engine files checked; nothing personal found.")
        return 0

    dest = os.path.abspath(args.dest)
    if os.path.exists(dest) and os.listdir(dest):
        raise SystemExit(f"{dest} is not empty; give a new folder.")
    for rel in files:
        target = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), target)
    print(f"Copied {len(files)} engine files to {dest}, checked for personal data.")
    print("To publish it as a new repository, with fresh history:")
    print(f"  cd {dest}")
    print("  git init -b main && git add -A && git commit -m 'Initial commit'")
    print("  gh repo create <name> --public --source . --push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

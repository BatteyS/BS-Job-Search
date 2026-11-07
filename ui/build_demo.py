"""Build the example demos: the local page, filled in for each example profile,
as static files any browser opens without a server.

    uv run python ui/build_demo.py OUT_DIR
    uv run python ui/build_demo.py OUT_DIR --no-pdf      # skip LaTeX

For each examples/<name>/ with a demo/ folder, it lays the example out the way
a copy of this repo is laid out (profile/, content/, digests/, Applications/,
and demo/applications.yaml as profile/applications.yaml) in a scratch folder,
builds the resumes, letters, and interview prep sheets demo/demo.json lists
into that folder's Applications/, and asks core.py what each of the page's
routes would answer there. The page reads those answers from demo.js instead of a server, so a demo
shows exactly what the page would show for that profile.

OUT_DIR gets index.html, which lists the examples, and a folder for each. The
demos are published at https://batteys.github.io/BS-Job-Search/ from the
public repo's gh-pages branch. The PDFs need LaTeX; without it, or with
--no-pdf, a demo still has its digest, postings, prep sheets, and profile, but
no PDFs.
"""

from __future__ import annotations

import argparse
import glob
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import claude_run  # noqa: E402
import core  # noqa: E402
import digest_applies  # noqa: E402  (core put scripts/ on the path)
import icon  # noqa: E402
import latex  # noqa: E402
import tracker  # noqa: E402

ROOT = core.ROOT
EXAMPLES = os.path.join(ROOT, "examples")
REPO_URL = "https://github.com/BatteyS/BS-Job-Search"

# Where each example file sits in a copy of this repo.
LAYOUT = {"profile.md": "profile/profile.md", "clusters.yaml": "profile/clusters.yaml",
          "filters.yaml": "profile/filters.yaml", "master.md": "content/master.md",
          "story.md": "content/story.md", "contact.md": "content/contact.local.md"}

# Runs a builder with its Applications/ pointed at the scratch copy, so nothing
# is filed in this repo's own.
RUNNER = ("import sys; sys.path.insert(0, sys.argv[1]); import {module} as m; "
          "m.APPS = sys.argv[2]; sys.argv = [m.__file__] + sys.argv[3:]; "
          "raise SystemExit(m.main())")

RUNS_NOTE = ("In this demo nothing runs. On your own copy, each of these starts the skill "
             "through your Claude Code, and anything it would ask you shows up here as a card.")
SETUP_NOTE = ("This profile is already set up, and in this demo nothing is checked or saved. "
              "On your own copy, this tab checks the machine, shows how far setup has got, "
              "and saves your API keys.")


def lay_out(name: str, repo: str) -> dict:
    """Copy an example into `repo` as a copy of this repo holds it. Returns its
    demo.json."""
    src = os.path.join(EXAMPLES, name)
    for file, dest in LAYOUT.items():
        if os.path.isfile(os.path.join(src, file)):
            os.makedirs(os.path.dirname(os.path.join(repo, dest)), exist_ok=True)
            shutil.copy(os.path.join(src, file), os.path.join(repo, dest))
    for folder in ("digests", "Applications"):
        if os.path.isdir(os.path.join(src, "demo", folder)):
            shutil.copytree(os.path.join(src, "demo", folder), os.path.join(repo, folder))
    os.makedirs(os.path.join(repo, "Applications"), exist_ok=True)
    statuses = os.path.join(src, "demo", "applications.yaml")
    if os.path.isfile(statuses):
        os.makedirs(os.path.join(repo, "profile"), exist_ok=True)
        shutil.copy(statuses, os.path.join(repo, tracker.TRACKER))
    with open(os.path.join(src, "demo", "demo.json"), encoding="utf-8") as fh:
        return json.load(fh)


def run_builder(module: str, apps: str, args: list[str], out: str | None = None) -> None:
    """Build one resume, letter, or prep sheet into `apps`. A LaTeX build names
    its working copies `out`, which are then cleared out of Resume/: the filed
    copies are what the demo keeps."""
    cmd = [sys.executable, "-c", RUNNER.format(module=module), core.SCRIPTS, apps,
           *args, *(["--out", out] if out else [])]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{module} failed for the demo:\n{r.stdout}{r.stderr}")
    if not out:
        return
    for pattern in (f"Resume/LaTeX/{out}.tex", f"Resume/pdf/{out}.pdf", f"Resume/build/{out}.*"):
        for path in glob.glob(os.path.join(ROOT, pattern)):
            os.remove(path)


def build_documents(name: str, meta: dict, repo: str) -> None:
    src = os.path.join(EXAMPLES, name)
    apps = os.path.join(repo, "Applications")
    common = ["--master", os.path.join(src, "master.md"),
              "--contact", os.path.join(src, "contact.md")]
    for i, r in enumerate(meta.get("resumes", [])):
        run_builder("build_resume", apps,
                    ["--manifest", os.path.join(src, "demo", r["manifest"]),
                     "--company", r["company"], "--title", r["title"], *common],
                    f"demo_{name}_resume_{i}")
    for i, letter in enumerate(meta.get("letters", [])):
        run_builder("build_letter", apps,
                    ["--letter", os.path.join(src, "demo", letter["letter"]),
                     "--company", letter["company"], "--title", letter["title"],
                     "--story", os.path.join(src, "story.md"), *common],
                    f"demo_{name}_letter_{i}")


def build_preps(name: str, meta: dict, repo: str) -> None:
    """The interview prep sheets demo.json lists. They are Markdown, so a demo
    has them even without LaTeX."""
    src = os.path.join(EXAMPLES, name)
    for prep in meta.get("preps", []):
        run_builder("build_prep", os.path.join(repo, "Applications"),
                    ["--prep", os.path.join(src, "demo", prep["prep"]),
                     "--company", prep["company"], "--title", prep["title"],
                     "--master", os.path.join(src, "master.md"),
                     "--story", os.path.join(src, "story.md")])


def answers(repo: str) -> dict:
    """What each GET route of the page answers for the copy at `repo`: the same
    core.py calls server.py makes, pointed there for the moment."""
    saved = [(m, k, getattr(m, k)) for m in (core, digest_applies)
             for k in ("ROOT", "DIGESTS", "APPS")] + [(tracker, "ROOT", tracker.ROOT)]
    try:
        tracker.ROOT = repo
        for m in (core, digest_applies):
            m.ROOT = repo
            m.DIGESTS = os.path.join(repo, "digests")
            m.APPS = os.path.join(repo, "Applications")
        # The digests, applications and profile files are what a phone keeps too.
        return {
            **core.snapshot()["answers"],
            "/api/setup": core.setup_state(),
            "/api/commands": core.Runs().commands(),
            # No plan usage: a demo's routes must not read this machine's.
            "/api/skills": claude_run.skills(limits={}),
            "/api/claude/status": {"available": True, "demo": True},
            "/api/runs": [],
            "/api/claude/runs": [],
        }
    finally:
        for m, k, v in saved:
            setattr(m, k, v)


def write_site(name: str, meta: dict, repo: str, get: dict, out: str) -> None:
    """The page as it ships, plus demo.js and the filed documents."""
    site = os.path.join(out, name)
    if os.path.isdir(site):
        shutil.rmtree(site)
    os.makedirs(site)
    for file in ("app.js", "style.css"):
        shutil.copy(os.path.join(HERE, file), site)
    with open(os.path.join(HERE, "index.html"), encoding="utf-8") as fh:
        page = fh.read()
    tag = '<script src="app.js"></script>'
    if tag not in page:
        raise SystemExit(f"ui/index.html has no {tag}; the demo cannot load its data")
    page = page.replace(tag, '<script src="demo.js"></script>\n' + tag)
    page = page.replace("<title>BS Job Search</title>",
                        f"<title>BS Job Search demo: {html.escape(meta['who'])}</title>")
    with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    # What makes a demo addable to a phone's home screen, as the page is.
    with open(os.path.join(site, "manifest.webmanifest"), "w", encoding="utf-8") as fh:
        json.dump(core.manifest(f"BS Job Search demo: {meta['who']}"), fh, indent=1)
    for file, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)):
        with open(os.path.join(site, file), "wb") as fh:
            fh.write(icon.png(size))
    shutil.copytree(os.path.join(repo, "Applications"), os.path.join(site, "files"))
    banner = (f"<b>Demo:</b> {html.escape(meta['who'])}, {html.escape(meta['about'])}. Every "
              "person, employer, and posting here is invented, and nothing you do here is "
              f'saved. <a href="../">All examples</a> · <a href="{REPO_URL}">Get your own copy</a>')
    data = {"banner": banner, "runsNote": RUNS_NOTE, "setupNote": SETUP_NOTE, "get": get}
    with open(os.path.join(site, "demo.js"), "w", encoding="utf-8") as fh:
        fh.write("window.DEMO = " + json.dumps(data, ensure_ascii=False) + ";\n")


LANDING = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BS Job Search: example demos</title>
<style>
/* seanbattey.com's design, as ui/style.css wears it. */
:root { --bg: #17120d; --surface: #211a14; --text: #f2e9d8; --muted: #b5a891; --border: #3b3128;
  --accent: #f2c14e; --accent-hover: #ffd36e; --on-accent: #1c1508; color-scheme: dark; }
body { margin: 0; background: var(--bg); color: var(--text); -webkit-font-smoothing: antialiased;
  font: 17px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
main { max-width: 720px; margin: 0 auto; padding: 56px 20px; }
.mark-link { display: inline-block; margin: 0 0 20px; border-radius: 4px; color: var(--accent); }
.mark-link:hover { color: var(--accent-hover); }
.mark-link:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
.mark { display: block; height: 72px; width: auto; }
h1 { font-size: clamp(32px, 6vw, 44px); line-height: 1.15; letter-spacing: -.02em; margin: 0 0 16px; }
p { color: var(--muted); }
a { color: var(--accent); text-underline-offset: .18em; }
a:hover { color: var(--accent-hover); }
.cards { display: grid; gap: 16px; margin: 32px 0; }
.card { display: block; padding: 20px; border: 1px solid var(--border); border-radius: 14px;
  background: var(--surface); color: var(--text); text-decoration: none;
  transition: border-color .15s, transform .15s; }
.card:hover { border-color: var(--accent); color: var(--text); transform: translateY(-2px); }
.card b { font-size: 18px; letter-spacing: -.01em; }
.card span { display: block; margin-top: 4px; color: var(--muted); font-size: 15px; }
.button { display: inline-flex; align-items: center; min-height: 46px; padding: 0 22px;
  border-radius: 999px; background: var(--accent); color: var(--on-accent); font-weight: 600;
  text-decoration: none; }
.button:hover { background: var(--accent-hover); color: var(--on-accent); }
</style>
</head>
<body>
<main>
<a class="mark-link" href="https://seanbattey.com" aria-label="seanbattey.com"><svg class="mark" viewBox="10 -12 86 208" aria-hidden="true" focusable="false"><g fill="none" stroke="currentColor" stroke-width="20"><path d="M22 28v156h28a34 34 0 0 0 0-68H22" stroke-linejoin="miter"/><path d="M76.3 18.4A28 28 0 1 0 50 56a30 30 0 0 1 0 60" stroke-linecap="round" stroke-linejoin="round"/></g></svg></a>
<h1>BS Job Search</h1>
<p>A job search workflow for Claude Code. It scans job boards, scores each role against
what you want, and builds a tailored resume and cover letter for the ones you mark. It
comes with a page that runs on your own computer, for reading and marking digests and
finding what was filed.</p>
<p>Below is that page, filled in for two fictional people. Click through a digest, open a
resume or a letter, and read the profile it was all scored against. Nothing you do here is
saved.</p>
<div class="cards">
@CARDS@
</div>
<p><a class="button" href="@REPO@">Get your own copy on GitHub</a></p>
</main>
</body>
</html>
"""


def write_landing(out: str, built: list[tuple[str, dict]]) -> None:
    cards = "\n".join(
        f'<a class="card" href="{name}/"><b>{html.escape(meta["who"])}</b>'
        f'<span>{html.escape(meta["about"][:1].upper() + meta["about"][1:])}</span></a>'
        for name, meta in built)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(LANDING.replace("@CARDS@", cards).replace("@REPO@", REPO_URL))
    # GitHub Pages runs Jekyll otherwise, which drops files whose names start with _.
    open(os.path.join(out, ".nojekyll"), "w", encoding="utf-8").close()


def build(out: str, pdf: bool = True) -> list[str]:
    """Build every example that has a demo/ folder into `out`. Returns their names."""
    os.makedirs(out, exist_ok=True)
    built = []
    for name in sorted(os.listdir(EXAMPLES)):
        if not os.path.isfile(os.path.join(EXAMPLES, name, "demo", "demo.json")):
            continue
        repo = tempfile.mkdtemp(prefix=f"demo-{name}-")
        try:
            meta = lay_out(name, repo)
            if pdf:
                build_documents(name, meta, repo)
            build_preps(name, meta, repo)
            write_site(name, meta, repo, answers(repo), out)
        finally:
            shutil.rmtree(repo, ignore_errors=True)
        built.append((name, meta))
    write_landing(out, built)
    return [name for name, _ in built]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", help="folder to write the demos into")
    ap.add_argument("--no-pdf", action="store_true", help="skip building resumes and letters")
    args = ap.parse_args()
    pdf = not args.no_pdf
    if pdf and not latex.find()[0]:
        print("pdflatex not found: building the demos without their PDFs")
        pdf = False
    names = build(args.out, pdf)
    print(f"Built {len(names)} demos into {args.out}: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

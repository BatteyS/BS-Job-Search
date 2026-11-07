"""The example demos (ui/build_demo.py): the page, filled in for each example
profile and built as static files. Built here without LaTeX; the resumes and
letters each demo carries are checked against the example's own files instead,
the way the builders check them."""

from __future__ import annotations

import json
import os
import sys

import pytest

from helpers import ROOT, run

sys.path.insert(0, os.path.join(ROOT, "ui"))
import build_demo  # noqa: E402
import build_resume  # noqa: E402  (core puts scripts/ on the path)
import tracker  # noqa: E402

EXAMPLES = os.path.join(ROOT, "examples")
DEMOS = sorted(n for n in os.listdir(EXAMPLES)
               if os.path.isfile(os.path.join(EXAMPLES, n, "demo", "demo.json")))


def bundled(site) -> dict:
    text = (site / "demo.js").read_text(encoding="utf-8")
    assert text.startswith("window.DEMO = ")
    return json.loads(text[len("window.DEMO = "):].rstrip().rstrip(";"))


def test_every_example_has_a_demo():
    assert DEMOS == sorted(n for n in os.listdir(EXAMPLES)
                           if os.path.isdir(os.path.join(EXAMPLES, n)))


def test_the_demos_build_without_latex(tmp_path):
    assert build_demo.build(str(tmp_path), pdf=False) == DEMOS
    landing = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert (tmp_path / ".nojekyll").exists()
    # The SB mark takes this tab to seanbattey.com, with no target to open another.
    assert '<a class="mark-link" href="https://seanbattey.com" aria-label="seanbattey.com">' in landing
    sheets = 0
    for name in DEMOS:
        assert f'href="{name}/"' in landing
        site = tmp_path / name
        page = (site / "index.html").read_text(encoding="utf-8")
        assert page.index('src="demo.js"') < page.index('src="app.js"')
        assert ('<a class="brand-mark-link" href="https://seanbattey.com" '
                'aria-label="seanbattey.com">') in page
        get = bundled(site)["get"]

        [row] = get["/api/digests"]
        digest = get[f"/api/digests/{row['date']}"]
        assert len(digest["entries"]) == row["entries"]
        assert row["apply"] >= 1 and row["conflicts"] == 0
        assert f"/api/digests/{row['date']}/verdicts" in get
        assert any(e["status"] for e in digest["entries"]), "the digest shows statuses"

        assert get["/api/setup"]["ready"], "a demo opens on Digests, not Setup"
        assert "content/contact.local.md" not in json.dumps(get["/api/profile"])

        written = [p["path"] for p in get["/api/profile"] if p["exists"]]
        assert {"profile/profile.md", "content/master.md", "content/story.md"} <= set(written)
        assert all(f"/api/profile/{p}" in get for p in written)

        listing = get["/api/applications"]
        for folder in listing["folders"]:
            for f in folder["files"]:
                assert (site / "files" / folder["company"] / f["name"]).is_file()
        rows = [r for f in listing["folders"] for r in f["roles"]]
        assert rows and all(r["status"] and r["digest"] for r in rows), \
            "every demo application has a status, and the digest entry it came from"

        # Prep sheets are Markdown, so they are built even without LaTeX.
        with open(os.path.join(EXAMPLES, name, "demo", "demo.json"), encoding="utf-8") as fh:
            preps = json.load(fh).get("preps", [])
        for prep in preps:
            sheet = site / "files" / prep["company"] / f"{prep['title']} - interview prep.md"
            assert "## Questions to expect" in sheet.read_text(encoding="utf-8")
            sheets += 1
    assert sheets, "a demo shows an interview prep sheet"


@pytest.mark.parametrize("name", DEMOS)
def test_each_demo_tracker_reads_and_is_in_the_pages_layout(name):
    path = os.path.join(EXAMPLES, name, "demo", "applications.yaml")
    t = tracker.load(path)
    assert not t.problem and t.entries and not any(e.problem for e in t.entries)
    with open(path, encoding="utf-8") as fh:
        assert tracker.render(t) == fh.read()


@pytest.mark.parametrize("name", DEMOS)
def test_what_the_demo_pdfs_are_built_from_holds_up(name):
    """Every resume selection resolves against the example's master.md, and
    every letter and prep sheet passes its builder's source and number checks."""
    src = os.path.join(EXAMPLES, name)
    with open(os.path.join(src, "demo", "demo.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    master = os.path.join(src, "master.md")
    front, entries = build_resume.parse_master(master)
    build_resume.normalize_sections(entries)
    mode = build_resume.master_format(master, front)[0]
    for r in meta["resumes"]:
        with open(os.path.join(src, "demo", r["manifest"]), encoding="utf-8") as fh:
            plan = build_resume.resolve_manifest(entries, json.load(fh), mode=mode)
        assert plan.experience
    for letter in meta["letters"]:
        posting = os.path.join(src, "demo", "Applications", letter["company"],
                               f"{letter['title']} - posting.txt")
        code, out = run("build_letter", "--letter", os.path.join(src, "demo", letter["letter"]),
                        "--check", "--master", master,
                        "--story", os.path.join(src, "story.md"),
                        "--contact", os.path.join(src, "contact.md"), "--posting", posting)
        assert code == 0, out
    for prep in meta.get("preps", []):
        posting = os.path.join(src, "demo", "Applications", prep["company"],
                               f"{prep['title']} - posting.txt")
        code, out = run("build_prep", "--prep", os.path.join(src, "demo", prep["prep"]),
                        "--check", "--master", master,
                        "--story", os.path.join(src, "story.md"), "--posting", posting)
        assert code == 0, out

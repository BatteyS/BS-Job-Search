"""The interview prep sheet: every answer, gap and question cites what it was
drawn from, with the letter's source and number checks."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

import pytest

from helpers import ROOT, SCRIPTS, example
import build_prep
from build_letter import Sources

NURSE_POSTING = os.path.join(
    ROOT, "examples", "nurse-sacramento", "demo", "Applications", "Sierra Crest Health",
    "Clinical Informatics Nurse, Inpatient Documentation - posting.txt")

PREP = {
    "date": "November 2, 2026",
    "questions": [
        {"question": "Tell me about a change to charting you led.",
         "from": [{"posting": "Track adoption after each change"}],
         "situation": "My unit piloted continuous capnography across 20 beds.",
         "action": "I wrote the charting checklist and trained 45 nurses on both shifts.",
         "result": "Charting compliance rose from 71% to 98% in four months.",
         "sources": [{"master": "Led a 4-month pilot of continuous capnography"}]},
        {"question": "Why informatics?",
         "from": [{"posting": "Clinical Informatics Nurse, Inpatient Documentation"}],
         "answer": "I want the charting work I have led on one unit to reach every unit.",
         "sources": [{"story": "I want to move from the bedside into clinical informatics"}]},
        {"question": "Tell me about a workflow you helped redesign.",
         "from": [{"master": "co-wrote the revised sepsis-screening workflow"}]},
    ],
    "gaps": [
        {"gap": "Testing changes before a release",
         "from": [{"posting": "Test new and changed flowsheets before each release"}],
         "address": "Say you have not tested a build; you logged 140 issues at go-live.",
         "sources": [{"master": "Epic super-user for the hospital's 2023 upgrade"}]},
    ],
    "ask": [
        {"question": "How do the six informatics nurses split the four hospitals?",
         "from": [{"posting": "You will join six informatics nurses"},
                  {"posting": "Our four hospitals share one Epic build"}]},
    ],
}


@pytest.fixture
def sources():
    return Sources(example("nurse-sacramento", "master.md"),
                   example("nurse-sacramento", "story.md"), NURSE_POSTING)


def edited(section: str, i: int, **changes) -> dict:
    prep = copy.deepcopy(PREP)
    prep[section][i].update(changes)
    for k in [k for k, v in changes.items() if v is None]:
        del prep[section][i][k]
    return prep


def errors_of(prep, sources) -> list[str]:
    return build_prep.check(prep, sources)[1]


def test_a_sourced_sheet_passes_and_notes_the_unanswered_question(sources):
    report, errors, warnings = build_prep.check(PREP, sources)
    assert errors == []
    assert any("question 3 has no answer yet" in w for w in warnings), warnings
    assert [len(report[s]) for s in build_prep.SECTIONS] == [3, 1, 1]


def test_a_number_its_sources_lack_is_refused_wherever_it_is(sources):
    prep = edited("questions", 0, result="Charting compliance rose from 71% to 99%.")
    assert any("question 1's answer: 99" in e for e in errors_of(prep, sources))
    prep = edited("gaps", 0, address="Say you logged 150 issues at go-live.")
    assert any("gap 1's answer: 150" in e for e in errors_of(prep, sources))
    prep = edited("ask", 0, question="How do the seven informatics nurses split the work?")
    assert any("question to ask 1: 7" in e for e in errors_of(prep, sources))


def test_an_answer_needs_a_source_about_the_user(sources):
    prep = edited("questions", 1, sources=[{"posting": "Train nurses and super-users"}])
    assert any("cites nothing the user did" in e for e in errors_of(prep, sources))
    prep = edited("questions", 1, sources=[{"user": "I want my charting work to reach "
                                                     "every unit"}])
    assert errors_of(prep, sources) == []


def test_an_answer_is_one_shape_or_the_other(sources):
    partial = edited("questions", 0, result=None)
    assert any("needs all three; it has no result" in e for e in errors_of(partial, sources))
    both = edited("questions", 0, answer="I led a pilot.")
    assert any("not both" in e for e in errors_of(both, sources))
    sourced = edited("questions", 2, sources=[{"master": "co-wrote the revised"}])
    assert any("sources but has no answer" in e for e in errors_of(sourced, sources))


def test_every_item_says_what_it_was_drawn_from(sources):
    for section, i in (("questions", 0), ("gaps", 0), ("ask", 0)):
        prep = edited(section, i, **{"from": []})
        assert any("does not say what it was drawn from" in e
                   for e in errors_of(prep, sources)), section


def test_a_gap_quotes_the_posting(sources):
    prep = edited("gaps", 0, **{"from": [{"master": "Epic super-user for the hospital"}]})
    assert any("quote the posting where it asks" in e for e in errors_of(prep, sources))
    prep = edited("gaps", 0, **{"from": [{"posting": "Five years of Epic build"}]})
    assert any("is not in the posting" in e for e in errors_of(prep, sources))


def test_a_keep_out_item_cannot_be_cited(sources):
    prep = edited("questions", 1, sources=[{"story": "Why I left Delta Ridge Hospital"}])
    assert any("Keep out of letters" in e for e in errors_of(prep, sources))


def test_a_mistyped_key_or_section_is_refused(sources):
    prep = edited("questions", 0, situtation="typo")
    assert any("keys the sheet does not use: situtation" in e for e in errors_of(prep, sources))
    prep = copy.deepcopy(PREP)
    prep["gap"] = prep.pop("gaps")
    assert any("keys the sheet does not use: gap" in e for e in errors_of(prep, sources))
    assert errors_of({"questions": []}, sources) == ["the sheet has no questions"]


def test_the_sheet_shows_every_answer_beside_its_sources(sources):
    report, errors, _ = build_prep.check(PREP, sources)
    assert errors == []
    md = build_prep.render(PREP, report, "Sierra Crest Health",
                           "Clinical Informatics Nurse, Inpatient Documentation")
    assert md.splitlines()[2] == ("# Interview prep: Clinical Informatics Nurse, "
                                  "Inpatient Documentation")
    assert "Sierra Crest Health · prepared November 2, 2026" in md
    for heading in ("## Questions to expect", "## Gaps to be ready for",
                    "## Questions to ask them"):
        assert heading in md
    assert "**Situation.** My unit piloted" in md and "**Result.** Charting" in md
    # A source is shown in full, not as the fragment that named it.
    assert "> - **master.md:** Led a 4-month pilot of continuous capnography for " \
           "post-operative cardiac patients across 20 beds" in md
    assert "*From the posting:* “Track adoption after each change”" in md
    assert "*No answer yet.*" in md


def test_a_latex_master_reads_as_plain_text_on_the_sheet():
    assert build_prep.plain(r"Cut CO$_2$ by 40\% with M\&V \textbf{contractors}",
                            "latex") == "Cut CO2 by 40% with M&V contractors"
    assert build_prep.plain("Raised $1.2M at 40%", "text") == "Raised $1.2M at 40%"


def test_the_other_example_cites_its_own_files(tmp_path):
    """Avery's facts back Avery's answers, and a number Avery never wrote fails."""
    posting = tmp_path / "posting.txt"
    posting.write_text("Director, Product Marketing. You will own positioning and pricing "
                       "for a B2B platform.\n", encoding="utf-8")
    src = Sources(example("product-marketer-chicago", "master.md"),
                  example("product-marketer-chicago", "story.md"), str(posting))
    prep = {"questions": [
        {"question": "Tell me about a positioning change you led.",
         "from": [{"posting": "own positioning"}],
         "situation": "Sales wanted a new tagline for the core platform.",
         "action": "I spent six weeks interviewing 38 customers and prospects.",
         "result": "Our win rate against the main competitor rose from 24% to 37%.",
         "sources": [{"story": "When we repositioned Brightline's core platform"}]}]}
    assert build_prep.check(prep, src)[1] == []
    prep["questions"][0]["result"] = "Our win rate rose from 24% to 40%."
    assert any("40" in e for e in build_prep.check(prep, src)[1])


# --------------------------------------------------------------- the command

# Runs build_prep with its Applications/ in a scratch folder, as ui/build_demo.py
# does, so a test never files anything in this repo's own.
RUNNER = ("import sys; sys.path.insert(0, sys.argv[1]); import build_prep as m; "
          "m.APPS = sys.argv[2]; sys.argv = [m.__file__] + sys.argv[3:]; "
          "raise SystemExit(m.main())")


def run_prep(apps, *args) -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-c", RUNNER, SCRIPTS, str(apps), *args,
                        "--master", example("nurse-sacramento", "master.md"),
                        "--story", example("nurse-sacramento", "story.md")],
                       capture_output=True, text=True, cwd=ROOT)
    return r.returncode, r.stdout + r.stderr


def test_it_files_the_sheet_beside_the_posting(tmp_path):
    company, title = "Sierra Crest Health", "Clinical Informatics Nurse, Inpatient Documentation"
    folder = tmp_path / "Applications" / company
    folder.mkdir(parents=True)
    (folder / f"{title} - posting.txt").write_text(open(NURSE_POSTING, encoding="utf-8").read(),
                                                   encoding="utf-8")
    prep = tmp_path / "prep.json"
    prep.write_text(json.dumps(PREP), encoding="utf-8")

    code, out = run_prep(tmp_path / "Applications", "--prep", str(prep), "--company", company,
                         "--title", title, "--check")
    assert code == 0 and "checks passed" in out and "(quotes checked)" in out, out
    assert not (folder / f"{title} - interview prep.md").exists()

    code, out = run_prep(tmp_path / "Applications", "--prep", str(prep), "--company", company,
                         "--title", title)
    sheet = folder / f"{title} - interview prep.md"
    assert code == 0 and sheet.is_file(), out
    assert "## Questions to ask them" in sheet.read_text(encoding="utf-8")

    bad = copy.deepcopy(PREP)
    bad["questions"][0]["action"] = "I trained 50 nurses."
    prep.write_text(json.dumps(bad), encoding="utf-8")
    code, out = run_prep(tmp_path / "Applications", "--prep", str(prep), "--company", company,
                         "--title", title)
    assert code == 1 and "NOT FILED" in out and "50" in out, out


def test_it_will_not_file_without_knowing_where(tmp_path):
    prep = tmp_path / "prep.json"
    prep.write_text(json.dumps(PREP), encoding="utf-8")
    code, out = run_prep(tmp_path, "--prep", str(prep))
    assert code == 2 and "only --check runs" in out
    code, out = run_prep(tmp_path, "--prep", str(prep), "--check")
    assert code == 1 and "no posting file" in out, out

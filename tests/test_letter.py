"""The cover-letter checks: every source resolves, and every number has one."""

from __future__ import annotations

import copy

import pytest

from helpers import example
from build_letter import Sources, check

POSTING = """Clinical Informatics Nurse — Valley Health Partners

Valley Health Partners is expanding remote cardiac monitoring across 12 hospitals in
Northern California. The Clinical Informatics Nurse will translate bedside workflows into
Epic build requirements, train unit staff, and track charting compliance.
"""

LETTER = {
    "greeting": "Dear Hiring Team,",
    "paragraphs": [
        {"text": "I'm applying for the Clinical Informatics Nurse role because I want the "
                 "monitoring and charting work I have led on one unit to reach every unit in "
                 "a hospital, and Valley Health Partners is expanding remote cardiac "
                 "monitoring across 12 hospitals.",
         "sources": [{"story": "so that the monitoring and charting work I have led on one "
                               "unit can reach every unit"},
                     {"posting": "expanding remote cardiac monitoring across 12 hospitals"}]},
        {"text": "I led a four-month pilot of continuous capnography across 20 beds, trained "
                 "45 nurses on both shifts, and charting compliance rose from 71% to 98%.",
         "sources": [{"master": "Led a 4-month pilot of continuous capnography"}]},
        {"text": "Thank you for considering my application.", "sources": []},
    ],
    "closing": "Sincerely,",
}


@pytest.fixture
def sources(tmp_path):
    posting = tmp_path / "posting.txt"
    posting.write_text(POSTING, encoding="utf-8")
    return Sources(example("nurse-sacramento", "master.md"),
                   example("nurse-sacramento", "story.md"), str(posting))


def edited(paragraph: int, **changes) -> dict:
    letter = copy.deepcopy(LETTER)
    letter["paragraphs"][paragraph].update(changes)
    return letter


def test_a_sourced_letter_passes(sources):
    _, errors, _ = check(LETTER, sources)
    assert errors == []


def test_a_number_no_source_holds_is_refused(sources):
    letter = edited(1, text=LETTER["paragraphs"][1]["text"].replace("45 nurses", "50 nurses"))
    _, errors, _ = check(letter, sources)
    assert any("50" in e and "none of its" in e for e in errors), errors


def test_a_source_must_match_something(sources):
    letter = edited(1, sources=[{"master": "Led a team of 200 surgeons"}])
    _, errors, _ = check(letter, sources)
    assert any("matches nothing in master" in e for e in errors), errors


def test_a_posting_quote_must_be_in_the_posting(sources):
    letter = edited(0, sources=[{"story": "so that the monitoring and charting work I have "
                                          "led on one unit can reach every unit"},
                                {"posting": "a fully remote role with travel"}])
    _, errors, _ = check(letter, sources)
    assert any("is not in the posting" in e for e in errors), errors


def test_stock_phrasing_is_flagged(sources):
    letter = edited(2, text="I am writing to express my interest. Thank you for your time.")
    _, errors, warnings = check(letter, sources)
    assert errors == []
    assert any("stock phrasing" in w for w in warnings), warnings

"""The resume builder: reading master.md, its dates, and fitting the page."""

from __future__ import annotations

import pytest

from helpers import example, needs_latex, run
from build_resume import (check_dates, creates_gap, find_entry, master_format,
                          normalize_sections, parse_master, parse_span)

EXAMPLES = {"nurse-sacramento": (2, 1), "product-marketer-chicago": (4, 2)}


def entries_of(path: str):
    front, entries = parse_master(path)
    normalize_sections(entries)
    return front, entries


@pytest.mark.parametrize("name", EXAMPLES)
def test_examples_parse_as_text_with_readable_dates(name):
    path = example(name, "master.md")
    front, entries = entries_of(path)
    roles = [e for e in entries if e.section == "Experience"]
    assert len(roles) == EXAMPLES[name][0]
    assert master_format(path, front)[0] == "text"
    check_dates(entries)


def test_an_exact_title_picks_the_role_a_promotion_contains():
    """"Product Marketing Manager" is inside "Senior Product Marketing Manager",
    so a substring match alone could never pick the earlier role."""
    _, entries = entries_of(example("product-marketer-chicago", "master.md"))
    junior = find_entry(entries, "Experience", "Brightline", "Product Marketing Manager")
    assert junior.role == "Product Marketing Manager" and "2019" in junior.dates
    senior = find_entry(entries, "Experience", "Brightline", "Senior Product")
    assert senior.role == "Senior Product Marketing Manager"
    with pytest.raises(SystemExit, match="matched 2 roles"):
        find_entry(entries, "Experience", "Brightline", "Marketing")


def test_date_spans():
    assert parse_span("May 2022 - May 2024") == (2022 * 12 + 5, 2024 * 12 + 5)
    assert parse_span("Jan 2023 – Present")[0] == 2023 * 12 + 1
    start, end = parse_span("Sept. 2019 - Dec 2022")
    assert end - start == 39
    assert parse_span("sometime in 2020") is None
    assert parse_span("") is None


def test_unreadable_dates_stop_the_build(tmp_path):
    p = tmp_path / "master.md"
    p.write_text("# Experience\n\n## Acme | Analyst | for a while\n\n- [P1] Did things.\n",
                 encoding="utf-8")
    _, entries = entries_of(str(p))
    with pytest.raises(SystemExit, match="cannot read"):
        check_dates(entries)


def test_dropping_a_middle_role_opens_a_gap(tmp_path):
    p = tmp_path / "master.md"
    p.write_text("# Experience\n\n"
                 "## A | Analyst | Jan 2024 – Present\n\n- [P1] One.\n\n"
                 "## B | Analyst | Jan 2022 – Dec 2023\n\n- [P1] Two.\n\n"
                 "## C | Analyst | Jan 2020 – Dec 2021\n\n- [P1] Three.\n", encoding="utf-8")
    _, entries = entries_of(str(p))
    roles = [e for e in entries if e.section == "Experience"]
    assert not creates_gap(roles)
    assert creates_gap([roles[0], roles[2]])


@needs_latex
@pytest.mark.parametrize("name", EXAMPLES)
def test_examples_build_to_their_page_limit(name):
    code, out = run("build_resume", "--all", "--master", example(name, "master.md"),
                    "--contact", example(name, "contact.md"), "--out", f"editing_test_{name}")
    assert code == 0, out
    pages = EXAMPLES[name][1]
    assert f"pages     : {pages} (limit {pages})" in out

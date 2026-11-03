"""Reading the digest's three boxes: apply, skip, and cover letter."""

from __future__ import annotations

import pytest

import digest_applies

DIGEST = """# Job digest — 2026-11-02

> Mark each entry `apply` or `skip — reason`.

---

### 1. Acme Energy — Project Engineer · **84** · Sacramento · $128,000
- [x] apply
- [ ] skip — reason:
- [x] cover letter

**Why:** Owns a storage deployment end to end.
**Resume:** chronological · **Effort:** low
**Gaps:** none
[View posting](https://example.com/1)

---

### 2. Birch Grid — Field Engineer · **80** · Sacramento
- [x] apply
- [ ] skip — reason:
- [ ] cover letter

### 3. Cedar Power — Analyst · **75** · Sacramento
- [ ] apply
- [x] skip — reason: wants 8+ years
- [x] cover letter

### 4. Dune Solar — Developer · **72** · Sacramento
- [ ] apply
- [ ] skip — reason:
- [x] cover letter

### 5. Elm Storage — Engineer · **70** · Sacramento
- [ ] apply
- [ ] skip — reason:
- [ ] cover letter

### 6. Fir Utilities — Engineer · **68** · Sacramento
- [x] apply
- [ ] skip — reason:
"""


@pytest.fixture
def result(tmp_path, monkeypatch):
    apps = tmp_path / "Applications"
    (apps / "Birch Grid").mkdir(parents=True)
    for ext in (".pdf", ".tex"):
        (apps / "Birch Grid" / f"Field Engineer{ext}").write_text("", encoding="utf-8")
    monkeypatch.setattr(digest_applies, "APPS", str(apps))
    path = tmp_path / "2026-11-02.md"
    path.write_text(DIGEST, encoding="utf-8")
    return digest_applies.parse(str(path))


def numbers(entries: list[dict]) -> list[int]:
    return [e["n"] for e in entries]


def test_a_letter_rides_on_apply(result):
    assert numbers(result["apply"]) == [1, 2, 6]
    assert numbers(result["letters"]) == [1]
    assert result["letters"][0]["letter_pdf"].endswith(
        "Acme Energy/Project Engineer - cover letter.pdf")


def test_a_letter_on_a_skipped_role_is_a_conflict(result):
    assert numbers(result["conflicts"]) == [3]


def test_a_letter_without_apply_is_reported_not_guessed(result):
    assert numbers(result["letter_only"]) == [4]
    assert numbers(result["unmarked"]) == [5]


def test_a_digest_from_before_the_box_reads_as_no_letter(result):
    fir = next(e for e in result["apply"] if e["n"] == 6)
    assert fir["marked_letter"] is False


def test_a_filed_resume_and_a_missing_letter_are_told_apart(result):
    birch = next(e for e in result["apply"] if e["n"] == 2)
    assert birch["already_built"] and not birch["letter_built"]


VERDICTS = """# Job digest — 2026-11-03

### 1. Acme Energy — Project Engineer · **84** · Sacramento
- [x] apply
- [ ] skip — reason:
- [ ] cover letter

### 2. Birch Grid — Field Engineer · **80** · Sacramento
- [ ] apply
- [x] skip — reason: wants 8+ years
- [ ] cover letter

### 3. Cedar Power — Analyst · **75** · Sacramento
- [ ] apply
- [x] skip — reason:
- [ ] cover letter

### 4. Dune Solar — Developer · **72** · Sacramento
- [ ] apply
- [ ] skip — reason:
- [ ] cover letter
"""


def test_verdicts_read_as_a_feedback_section(tmp_path, monkeypatch):
    apps = tmp_path / "Applications"
    (apps / "Dune Solar").mkdir(parents=True)
    for ext in (".pdf", ".tex"):
        (apps / "Dune Solar" / f"Developer{ext}").write_text("", encoding="utf-8")
    monkeypatch.setattr(digest_applies, "APPS", str(apps))
    path = tmp_path / "2026-11-03.md"
    path.write_text(VERDICTS, encoding="utf-8")
    text = digest_applies.verdicts(digest_applies.parse(str(path)))
    assert "4 scored, 1 apply, 2 skip" in text
    assert "| 2 | Birch Grid — Field Engineer | 80 | wants 8+ years |" in text
    assert "#3 Cedar Power — Analyst: skipped with no reason" in text
    assert "#4 Dune Solar — Developer: unmarked, but its resume is filed" in text


class Posting:
    def __init__(self, title, description=""):
        self.title, self.description, self.ats = title, description, "greenhouse"


BOARDS = [{"name": "Redwood Materials", "ats": "greenhouse", "token": "redwoodmaterials"}]


def board_listing(*titles):
    return lambda board: ([Posting(t) for t in titles], True, "")


def fill(job):
    job.description = "Own BESS projects end to end."


def test_a_failed_link_is_found_on_the_employers_board():
    listing = board_listing("Solar PV Project Engineer, Senior or Staff",
                            "BESS Project Engineer, Senior or Staff")
    job, why = digest_applies.find_on_board(
        "Redwood Materials", "BESS Project Engineer, Senior or Staff", BOARDS, listing, fill)
    assert job.title == "BESS Project Engineer, Senior or Staff" and job.description


def test_an_ambiguous_title_is_reported_not_guessed():
    listing = board_listing("Project Engineer, Solar", "Project Engineer, Storage")
    job, why = digest_applies.find_on_board("Redwood Materials", "Project Engineer", BOARDS,
                                            listing, fill)
    assert job is None and "several postings" in why


def test_an_employer_without_a_board_says_so():
    job, why = digest_applies.find_on_board("Climate People", "Senior Project Engineer",
                                            BOARDS, board_listing(), fill)
    assert job is None and "not in sources/companies.yaml" in why

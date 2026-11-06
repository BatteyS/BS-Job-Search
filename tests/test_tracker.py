"""The application tracker (scripts/tracker.py): profile/applications.yaml as
the page writes it, the rules every change follows, and what the scan learns
from each application, joined to its digest entry by digest_applies.py."""

from __future__ import annotations

import datetime as dt

import pytest
import yaml

import digest_applies
import tracker

TODAY = dt.date(2026, 11, 3)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "ROOT", str(tmp_path))
    return tmp_path


def text(root) -> str:
    return (root / "profile" / "applications.yaml").read_text(encoding="utf-8")


def write(root, body: str):
    path = root / "profile" / "applications.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def change(company="Acme Energy", role="Project Engineer", **kw):
    kw.setdefault("today", TODAY)
    return tracker.set_status(company, role, **kw)


# ----------------------------------------------------------------- writing

def test_each_change_is_one_dated_line(root):
    change(status="applied", date="2026-10-02", allow_new=True)
    before = text(root).splitlines()
    e = change(status="heard back")
    after = text(root)
    assert [line for line in after.splitlines() if line not in before] == [
        "  - 2026-11-03 heard back"]
    assert after.startswith(tracker.HEADER)
    assert (e.status, e.since, e.applied) == ("heard back", "2026-11-03", "2026-10-02")
    assert yaml.safe_load(after) == {"applications": [{
        "company": "Acme Energy", "role": "Project Engineer",
        "history": ["2026-10-02 applied", "2026-11-03 heard back"]}]}


def test_entries_are_sorted_and_an_employer_may_have_no_role(root):
    change("Cedar Power", "", status="rejected", allow_new=True)
    change("birch grid", "Analyst", status="applied", allow_new=True)
    change(status="applied", allow_new=True)
    assert [e.key for e in tracker.load().entries] == [
        ("Acme Energy", "Project Engineer"), ("birch grid", "Analyst"), ("Cedar Power", "")]
    assert "role" not in yaml.safe_load(text(root))["applications"][2]


def test_what_was_added_by_hand_is_kept_but_comments_are_not(root):
    write(root, "# my own comment\n"
                "applications:\n"
                "- company: Acme Energy\n"
                "  role: Project Engineer\n"
                "  history:\n"
                "  - {date: 2026-10-02, status: Applied}\n"
                "  referral: a former colleague\n"
                "- company: 'Birch: Grid'\n"
                "  role: Analyst\n"
                "  history: [2026-10-05 applied]\n"
                "settings: {remind_after: 21}\n")
    change(status="interviewing")
    t = tracker.load()
    acme, birch = t.entries
    assert acme.history == [("2026-10-02", "applied"), ("2026-11-03", "interviewing")]
    assert acme.extra == {"referral": "a former colleague"}
    assert t.extra == {"settings": {"remind_after": 21}}
    assert birch.key == ("Birch: Grid", "Analyst")
    written = text(root)
    assert "my own comment" not in written and "  - 2026-10-02 applied" in written


def test_only_the_page_starts_an_entry(root):
    with pytest.raises(ValueError, match="no application"):
        change(status="applied")
    assert not (root / "profile" / "applications.yaml").exists()


# ------------------------------------------------------------------- rules

def test_a_status_moves_forward_or_ends(root):
    change(status="applied", allow_new=True)
    e = change(status="interviewing")
    assert tracker.can_move_to(e) == ["offer", "accepted", "rejected", "withdrawn",
                                      "no response"]
    for back in ("applied", "heard back"):
        with pytest.raises(ValueError, match="undo the last change"):
            change(status=back)
    with pytest.raises(ValueError, match="already interviewing"):
        change(status="interviewing")
    with pytest.raises(ValueError, match="not a status"):
        change(status="ghosted")


def test_a_late_answer_can_follow_no_response(root):
    change(status="applied", date="2026-09-01", allow_new=True)
    change(status="no response", date="2026-10-15")
    assert change(status="heard back").status == "heard back"


def test_dates_stay_in_order_and_never_pass_today(root):
    change(status="applied", date="2026-10-02", allow_new=True)
    with pytest.raises(ValueError, match="after today"):
        change(status="heard back", date="2026-11-04")
    with pytest.raises(ValueError, match="before 2026-10-02"):
        change(status="heard back", date="2026-10-01")
    with pytest.raises(ValueError, match="not a date"):
        change(status="heard back", date="2026-02-30")
    change(status="heard back", date="2026-10-20")
    assert change(date="2026-10-10").history[-1] == ("2026-10-10", "heard back")
    with pytest.raises(ValueError, match="before 2026-10-02"):
        change(date="2026-09-30")


def test_undo_takes_off_the_last_line_then_the_entry(root):
    change(status="applied", allow_new=True)
    change(status="rejected")
    assert change(undo=True).status == "applied"
    assert change(undo=True) is None
    assert tracker.load().entries == []
    with pytest.raises(ValueError, match="no application"):
        change(undo=True)

    change(note="waiting on a referral", allow_new=True)   # a note alone keeps an entry
    e = tracker.load().entries[0]
    assert (e.status, e.note) == (None, "waiting on a referral")
    with pytest.raises(ValueError, match="no change to undo"):
        change(undo=True)
    with pytest.raises(ValueError, match="undo goes alone"):
        change(undo=True, status="applied")
    with pytest.raises(ValueError, match="give it a status"):
        change(date="2026-10-01")


def test_a_note_is_one_line_with_no_contact_details(root):
    change(status="applied", allow_new=True)
    assert change(note="  asked about\n  storage   ").note == "asked about storage"
    # Assembled here, so this file does not trip the export's own check.
    email, phone = "pat" + "@" + "acme-energy.com", "(415) 867" + "-5309"
    for bad in (f"write to {email}", f"call {phone}", "x" * 501, "a\x00b"):
        with pytest.raises(ValueError):
            change(note=bad)
    assert tracker.load().entries[0].note == "asked about storage"
    assert change(note="").note == ""
    assert "note" not in text(root)


def test_a_file_that_does_not_load_is_never_written(root):
    path = write(root, "applications:\n- company: [unclosed\n")
    t = tracker.load()
    assert "does not load" in t.problem and t.entries == []
    with pytest.raises(ValueError, match="does not load"):
        change(status="applied", allow_new=True)
    assert path.read_text(encoding="utf-8") == "applications:\n- company: [unclosed\n"
    write(root, "- a list, not under applications\n")
    assert "under `applications:`" in tracker.load().problem


def test_an_entry_that_does_not_read_is_kept_and_locked(root):
    write(root, "applications:\n"
                "- company: Acme Energy\n  role: Project Engineer\n"
                "  history: [2026-10-02 applied]\n"
                "- company: Birch Grid\n  role: Analyst\n  history: [2026-10-02 ghosted]\n"
                "- company: Cedar Power\n"
                "  history: [2026-10-09 applied, 2026-10-02 rejected]\n")
    t = tracker.load()
    assert [bool(e.problem) for e in t.entries] == [False, True, True]
    assert "'ghosted' is not a status" in t.entries[1].problem
    assert "out of date order" in t.entries[2].problem
    change(status="heard back")
    with pytest.raises(ValueError, match="fixed by hand"):
        change("Birch Grid", "Analyst", status="rejected")
    kept = yaml.safe_load(text(root))["applications"]
    assert kept[1] == {"company": "Birch Grid", "role": "Analyst",
                       "history": ["2026-10-02 ghosted"]}
    assert kept[2]["history"] == ["2026-10-09 applied", "2026-10-02 rejected"]


# --------------------------------------------------------------- outcomes

def entry(*history):
    return tracker.Entry("Acme Energy", "Analyst", history=list(history))


@pytest.mark.parametrize("history,expected", [
    ([], None),
    ([("2026-10-05", "applied")], "waiting"),                  # 29 days
    ([("2026-10-04", "applied")], "screened out"),             # 30 days, no word
    ([("2026-10-01", "applied"), ("2026-10-08", "rejected")], "screened out"),
    ([("2026-10-01", "applied"), ("2026-10-30", "no response")], "screened out"),
    ([("2026-10-01", "applied"), ("2026-10-08", "heard back"), ("2026-10-20", "rejected")],
     "forward"),
    ([("2026-10-01", "applied"), ("2026-10-08", "offer"), ("2026-10-10", "accepted")],
     "forward"),
    ([("2026-10-01", "applied"), ("2026-10-08", "interviewing"), ("2026-10-20", "withdrawn")],
     "withdrawn"),
    ([("2026-10-01", "withdrawn")], "withdrawn"),
])
def test_what_the_scan_learns_from_each(history, expected):
    assert tracker.outcome(entry(*history), TODAY) == expected


def test_a_summary_says_how_far_it_got():
    assert tracker.summary(entry(("2026-08-14", "applied"), ("2026-08-28", "interviewing"),
                                 ("2026-09-20", "rejected")), TODAY) == \
        "rejected 2026-09-20, after interviewing, applied 2026-08-14"
    assert tracker.summary(entry(("2026-09-01", "applied")), TODAY) == \
        "applied 2026-09-01, no word in 63 days"
    assert tracker.summary(entry(), TODAY) == "no status yet"


def test_the_roles_filed_in_a_folder(tmp_path):
    for name in ("Project Engineer.pdf", "Project Engineer.tex",
                 "Project Engineer - cover letter.pdf", "Project Engineer - cover letter.tex",
                 "Analyst - posting.txt", "Old Resume.pdf", "Transcript.pdf",
                 "Advisor - Cover Letter.pdf", "Advisor - Cover Letter.tex",
                 ".hidden - posting.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert tracker.roles_on_disk(str(tmp_path)) == ["Analyst", "Project Engineer"]
    assert tracker.roles_on_disk(str(tmp_path / "missing")) == []


# ------------------------------------------------- joined to the digests

DIGEST = """# Job digest — 2026-10-01

### 1. Black & Veatch — Staff Engineer, BESS · **82** · Chicago · $150,000
- [x] apply
- [ ] skip — reason:
- [ ] cover letter

**Why:** Owns storage interconnection studies.
**Gaps:** wants a PE license

### 2. Birch Grid — Field Engineer · **80** · Sacramento
- [ ] apply
- [ ] skip — reason:
- [ ] cover letter

### 3. Cedar Power — Analyst · **75** · Sacramento
- [ ] apply
- [x] skip — reason: too junior
- [ ] cover letter

### 4. Dune Solar — Developer · **72** · Sacramento
- [ ] apply
- [x] skip — reason: posting closed
- [ ] cover letter
"""


@pytest.fixture
def copy(root, monkeypatch):
    """A digest, an Applications/ folder that spells one employer its own way, a
    role filed with no status, and four tracked applications."""
    (root / "digests").mkdir()
    (root / "digests" / "2026-10-01.md").write_text(DIGEST, encoding="utf-8")
    apps = root / "Applications"
    (apps / "Black and Veatch").mkdir(parents=True)
    for ext in (".pdf", ".tex"):
        (apps / "Black and Veatch" / f"Staff Engineer, BESS{ext}").write_text("x", encoding="utf-8")
    (apps / "Elm Storage").mkdir()
    (apps / "Elm Storage" / "Engineer - posting.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(digest_applies, "ROOT", str(root))
    monkeypatch.setattr(digest_applies, "DIGESTS", str(root / "digests"))
    monkeypatch.setattr(digest_applies, "APPS", str(apps))
    bv = ("Black and Veatch", "Staff Engineer, BESS")
    change(*bv, status="applied", date="2026-10-02", allow_new=True)
    change(*bv, status="interviewing", date="2026-10-20")
    change("Birch Grid", "Field Engineer", status="applied", date="2026-10-03", allow_new=True)
    change("Cedar Power", "Analyst", status="applied", date="2026-10-03", allow_new=True)
    change("Dune Solar", "Developer", status="withdrawn", date="2026-10-03", allow_new=True)
    return root


def test_a_digest_entry_carries_its_applications_status(copy):
    entries = {e["n"]: e for e in digest_applies.read_entries(
        str(copy / "digests" / "2026-10-01.md"))}
    assert (entries[1]["status"], entries[1]["status_since"]) == ("interviewing", "2026-10-20")
    assert entries[2]["status"] == "applied"


def test_the_verdicts_settle_what_the_tracker_contradicts(copy):
    text_ = digest_applies.verdicts(digest_applies.parse(str(copy / "digests" / "2026-10-01.md")))
    settle = text_.split("Settle before appending:")[1]
    assert ("#2 Birch Grid — Field Engineer: unmarked, but profile/applications.yaml has it "
            "as applied -- tick apply") in settle
    assert ("#3 Cedar Power — Analyst: skipped, but profile/applications.yaml has it as "
            "applied") in settle
    assert "Dune Solar" not in settle      # a withdrawal agrees with a skip


def test_outcomes_sit_beside_their_digest_entries(copy, capsys):
    o = digest_applies.outcomes(TODAY)
    by = {r["company"]: r for r in o["applications"]}
    assert by["Black and Veatch"]["outcome"] == "forward"
    assert by["Black and Veatch"]["digest"]["score"] == 82
    assert by["Black and Veatch"]["digest"]["gaps"] == "wants a PE license"
    assert [by[c]["outcome"] for c in ("Birch Grid", "Cedar Power", "Dune Solar")] == [
        "screened out", "screened out", "withdrawn"]
    assert o["filed_no_status"] == [{"company": "Elm Storage", "role": "Engineer"}]

    assert digest_applies.print_outcomes(o) == 0
    out = capsys.readouterr().out
    assert "outcomes  : 4 tracked, 1 went forward, 2 screened out, 0 waiting, 1 withdrawn" in out
    assert "digest 2026-10-01 #1, scored 82, Chicago, $150,000" in out
    assert "applied 2026-10-03, no word in 31 days" in out
    assert "NO STATUS YET (1)" in out and "  Elm Storage - Engineer" in out


def test_outcomes_wait_for_a_file_that_does_not_load(copy, capsys):
    write(copy, "applications: [\n")
    o = digest_applies.outcomes(TODAY)
    assert o["problem"] and o["applications"] == []
    assert digest_applies.print_outcomes(o) == 1
    assert "without outcomes" in capsys.readouterr().out


# ------------------------------------------------- changes made against a view

def seen(**kw):
    """A change as the page makes one, for a role the Applications tab lists."""
    return change(allow_new=True, **kw)


def test_a_change_against_the_last_line_seen_is_written(root):
    seen(status="applied", date="2026-11-01")
    seen(status="heard back", expect_last="2026-11-01 applied")
    assert tracker.last_line(tracker.load().entries[0]) == f"{TODAY} heard back"


def test_a_change_against_an_out_of_date_view_is_refused_and_writes_nothing(root):
    seen(status="applied", date="2026-11-01")
    seen(status="heard back", date="2026-11-02")          # elsewhere, since
    before = text(root)
    for kw in ({"status": "rejected"}, {"undo": True}, {"date": "2026-11-03"}):
        with pytest.raises(tracker.Conflict) as refused:
            seen(expect_last="2026-11-01 applied", **kw)
        assert refused.value.current == {"last": "2026-11-02 heard back", "note": ""}
        assert "now 2026-11-02 heard back" in str(refused.value)
        assert isinstance(refused.value, ValueError)            # old callers still refuse
    assert text(root) == before


def test_a_new_application_expects_no_line(root):
    seen(status="applied", expect_last="")
    with pytest.raises(tracker.Conflict, match="now .* applied"):
        seen(status="heard back", expect_last="")


def test_the_same_change_sent_twice_is_done_not_refused(root):
    seen(status="applied", date="2026-11-01")
    seen(status="heard back", date="2026-11-02", expect_last="2026-11-01 applied")
    before = text(root)
    again = seen(status="heard back", date="2026-11-02", expect_last="2026-11-01 applied")
    assert again.status == "heard back" and text(root) == before


def test_a_note_changed_since_is_refused_unless_it_already_says_the_same(root):
    seen(status="applied", note="sent by email")
    seen(note="a recruiter called")                          # elsewhere, since
    with pytest.raises(tracker.Conflict) as refused:
        seen(note="follow up Friday", expect_note="sent by email")
    assert refused.value.current["note"] == "a recruiter called"
    assert seen(note="a recruiter called", expect_note="sent by email").note == "a recruiter called"
    assert seen(note="follow up Friday", expect_note="a recruiter called").note == "follow up Friday"


def test_without_what_was_seen_a_change_works_as_before(root):
    seen(status="applied")
    seen(status="heard back")
    assert tracker.load().entries[0].status == "heard back"

"""The application tracker: where each application stands, kept in
profile/applications.yaml.

An application is one role at one employer, named the way its files are: the
employer's folder under Applications/ and the stem the role's resume and posting
share (Applications/<Company>/<Title>.pdf, <Title> - posting.txt). An older
folder with no such files is tracked as the employer as a whole, with no role.
Its history is one line per change, oldest first: the date and the status the
application reached that day. The last line is where it stands.

    applications:

    - company: Acme Energy
      role: Project Engineer
      history:
      - 2026-10-02 applied
      - 2026-10-16 heard back
      note: the recruiter asked about storage commissioning

The file is tracked, unlike Applications/, so a copy pushed to a private
repository carries it to a second machine; it is not part of the template
export. The page's Applications tab writes it (ui/core.py), and job-scan reads
what came of each application through `digest_applies.py --outcomes`. No skill
writes it: only the user knows what was sent and what came back.

A write rewrites the whole file in one layout, sorted by employer and role, so a
change shows as one line in the diff. Keys added by hand are kept; comments are
not, apart from the header written here. An entry that does not read is kept as
it is and refused for writes until it is fixed by hand, and nothing is written
while the file as a whole does not load.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import stat
import sys
import tempfile
import threading
from dataclasses import dataclass, field

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_template import EMAIL, PHONE  # noqa: E402  -- the export's own check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKER = "profile/applications.yaml"

# In the order an application moves through them; ENDED are the ones that
# close it.
STATUSES = ("applied", "heard back", "interviewing", "offer", "accepted",
            "rejected", "withdrawn", "no response")
ENDED = ("accepted", "rejected", "withdrawn", "no response")
MEANING = {
    "applied": "it went out",
    "heard back": "a person answered with interest, before any interview",
    "interviewing": "a screen or an interview has happened or is booked",
    "offer": "an offer came",
    "accepted": "you took it",
    "rejected": "they said no, at any stage",
    "withdrawn": "you stopped it: did not send it, pulled out, or turned down an offer",
    "no response": "no word, and you have stopped expecting any",
}
# How far an application got. A person answering with interest is the step the
# scan learns from: the resume cleared the screen.
STAGE = {"applied": 1, "heard back": 2, "interviewing": 3, "offer": 4, "accepted": 5}
FORWARD = STAGE["heard back"]
# An application at `applied` this long with no change counts as no word.
STALE_DAYS = 30
NOTE_MAX = 500

KNOWN = ("company", "role", "history", "note")

HEADER = """\
# Where each application stands, written by the page's Applications tab. Each
# history line is a date and the status the application reached that day,
# oldest first, so the last line is where it stands. The statuses: applied,
# heard back, interviewing, offer, accepted, rejected, withdrawn, no response.
# A write rewrites this file in this layout: keys you add by hand are kept,
# comments are not. The file is tracked, so it holds no phone numbers or email
# addresses.
"""

RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(\S.*?)\s*$")

POSTING = " - posting.txt"
LETTER = " - cover letter"


@dataclass
class Entry:
    company: str
    role: str = ""
    history: list = field(default_factory=list)   # [(date, status)], oldest first
    note: str = ""
    extra: dict = field(default_factory=dict)     # keys this module does not know
    problem: str = ""                             # why it cannot be written to
    raw: object = None                            # the entry as read, when it has a problem

    @property
    def key(self) -> tuple[str, str]:
        return self.company, self.role

    @property
    def status(self) -> str | None:
        return self.history[-1][1] if self.history else None

    @property
    def since(self) -> str | None:
        return self.history[-1][0] if self.history else None

    @property
    def applied(self) -> str | None:
        return next((d for d, s in self.history if s == "applied"), None)

    @property
    def reached(self) -> str | None:
        """The furthest step it got to, of applied through accepted."""
        steps = [s for _, s in self.history if s in STAGE]
        return max(steps, key=STAGE.get) if steps else None


@dataclass
class Tracker:
    entries: list = field(default_factory=list)
    problem: str = ""                              # why nothing can be written, or ""
    extra: dict = field(default_factory=dict)      # top-level keys besides `applications`


def label(company: str, role: str) -> str:
    return f"{company} - {role}" if role else f"{company} (the employer as a whole)"


def tracker_path() -> str:
    return os.path.join(ROOT, TRACKER)


# ------------------------------------------------------------------ reading

def _is_date(s: str) -> bool:
    if not RE_DATE.match(s):
        return False
    try:
        dt.date.fromisoformat(s)
    except ValueError:
        return False
    return True


def _line(line) -> tuple[str, str] | str:
    """(date, status) from one history line, or why it does not read. A
    `{date: ..., status: ...}` mapping reads too, as someone might write it."""
    if isinstance(line, dict) and set(line) == {"date", "status"}:
        date, status = str(line["date"]), str(line["status"])
    elif isinstance(line, str) and RE_LINE.match(line):
        date, status = RE_LINE.match(line).groups()
    else:
        return f"history line {line!r} is not a date and a status, like `2026-10-02 applied`"
    status = " ".join(status.lower().split())
    if status not in STATUSES:
        return f"{status!r} is not a status; they are {', '.join(STATUSES)}"
    if not _is_date(date):
        return f"{date} is not a date"
    return date, status


def _entry(item, seen: set) -> Entry:
    def bad(why: str) -> Entry:
        named = item if isinstance(item, dict) else {}
        return Entry(company=str(named.get("company") or ""), role=str(named.get("role") or ""),
                     problem=why, raw=item)

    if not isinstance(item, dict):
        return bad("an entry is a company, a role, a history, and a note")
    company, role, note = item.get("company"), item.get("role"), item.get("note")
    if not isinstance(company, str) or not company.strip():
        return bad("its company is missing, or not text")
    for name, value in (("role", role), ("note", note)):
        if value is not None and not isinstance(value, str):
            return bad(f"its {name} is not text; put it in quotes")
    history = item.get("history")
    if history is not None and not isinstance(history, list):
        return bad("its history is not a list of lines like `2026-10-02 applied`")
    lines = []
    for line in history or []:
        got = _line(line)
        if isinstance(got, str):
            return bad(got)
        lines.append(got)
    if any(b[0] < a[0] for a, b in zip(lines, lines[1:])):
        return bad("its history is out of date order")
    e = Entry(company=company.strip(), role=(role or "").strip(), history=lines,
              note=(note or "").strip(), extra={k: v for k, v in item.items() if k not in KNOWN})
    if e.key in seen:
        return bad("a second entry for the same application")
    seen.add(e.key)
    return e


def load(path: str | None = None) -> Tracker:
    """Every entry in the file (this copy's, unless `path` names another). A
    missing file is an empty tracker; one that does not load comes back with
    `problem` set, and nothing can be written."""
    path = path or tracker_path()
    if not os.path.isfile(path):
        return Tracker()
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return Tracker(problem=f"{TRACKER} does not load ({first}). Fix it by hand: "
                               "nothing is written to it until then.")
    if data is None:
        return Tracker()
    items = data.get("applications") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(items, (list, type(None))):
        return Tracker(problem=f"{TRACKER} should hold one list, under `applications:`. "
                               "Fix it by hand: nothing is written to it until then.")
    seen: set = set()
    return Tracker(entries=[_entry(item, seen) for item in items or []],
                   extra={k: v for k, v in data.items() if k != "applications"})


# ------------------------------------------------------------------ writing

def _item(e: Entry):
    if e.problem:
        return e.raw
    item = {"company": e.company}
    if e.role:
        item["role"] = e.role
    if e.history:
        item["history"] = [f"{d} {s}" for d, s in e.history]
    if e.note:
        item["note"] = e.note
    item.update(e.extra)
    return item


def render(t: Tracker) -> str:
    """The file's text: the header, then the entries sorted by employer and role,
    a blank line between them."""
    entries = sorted(t.entries, key=lambda e: (e.company.casefold(), e.role.casefold()))
    data = {"applications": [_item(e) for e in entries], **t.extra}
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True,
                          default_flow_style=False, width=1 << 30)
    body = re.sub(r"\n(?=- )", "\n\n", body)
    text = HEADER + "\n" + body
    if yaml.safe_load(text) != data:
        raise ValueError(f"{TRACKER} would not read back as written, so nothing was saved")
    return text


def save(t: Tracker) -> None:
    """Write the file whole, through a temporary file beside it, so a failed
    write leaves the old one as it was."""
    if t.problem:
        raise ValueError(t.problem)
    text = render(t)
    path = tracker_path()
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    mode = stat.S_IMODE(os.stat(path).st_mode) if os.path.exists(path) else 0o644
    fd, tmp = tempfile.mkstemp(prefix=".applications-", suffix=".yaml", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def clean_note(text: str) -> str:
    """A note as it is kept: one line, without contact details, since the file
    is tracked (CLAUDE.md keeps them in contact.local.md alone)."""
    note = " ".join(text.split())
    if len(note) > NOTE_MAX:
        raise ValueError(f"a note holds up to {NOTE_MAX} characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in note):
        raise ValueError("a note cannot hold control characters")
    if EMAIL.search(note) or PHONE.search(note):
        raise ValueError(f"{TRACKER} is tracked in git, so a note cannot hold an email "
                         "address or a phone number")
    return note


def can_move_to(e: Entry) -> list[str]:
    """The statuses one change can give it: a step further than it has been, or
    one of the endings. A step it already got past would be a mistake, which
    undoing the last change fixes without losing the dates in between."""
    furthest = STAGE.get(e.reached, 0)
    return [s for s in STATUSES if s != e.status and (s not in STAGE or STAGE[s] > furthest)]


def _date(value: str, after: str | None, today: dt.date) -> str:
    if not isinstance(value, str) or not _is_date(value):
        raise ValueError(f"{value!r} is not a date, YYYY-MM-DD")
    if value > today.isoformat():
        raise ValueError(f"{value} is after today")
    if after and value < after:
        raise ValueError(f"{value} is before {after}, the change it follows")
    return value


_lock = threading.Lock()


class Conflict(ValueError):
    """A change made against a view of the file that is out of date: what it
    expected is no longer there. `current` holds what is, for the page to show.
    A ValueError still, so a caller that knows nothing of it refuses as before."""

    def __init__(self, message: str, current: dict):
        super().__init__(message)
        self.current = current


def last_line(e: Entry) -> str:
    """An entry's last history line as one string, "YYYY-MM-DD status", or ""
    with none: what a change sends as `expect_last`."""
    return f"{e.history[-1][0]} {e.history[-1][1]}" if e.history else ""


def _already(e: Entry, status: str | None, date: str | None, note: str | None,
             undo: bool) -> bool:
    """Whether the change asked for already holds, so sending it again is done."""
    if undo:
        return False
    if status is not None:
        wanted = " ".join(str(status).lower().split())
        if e.status != wanted or (date is not None and e.since != date):
            return False
    elif date is not None and e.since != date:
        return False
    return note is None or e.note == clean_note(note)


def set_status(company: str, role: str = "", *, status: str | None = None,
               date: str | None = None, note: str | None = None, undo: bool = False,
               allow_new: bool = False, today: dt.date | None = None,
               expect_last: str | None = None, expect_note: str | None = None) -> Entry | None:
    """Change one application and save the file. Returns its entry as it now
    stands, or None once undo has left nothing in it.

    `status` adds a line, dated `date` or today. `date` alone re-dates the last
    line, `note` replaces the note ("" clears it), and `undo` removes the last
    line. No date may be after today or before the line it follows.
    `allow_new` lets the call start an entry the file does not hold yet: the
    page passes it for the roles it found under Applications/.

    `expect_last` is the last history line the caller saw (last_line(), ""
    for none), and `expect_note` the note it saw. When either no longer holds,
    the change raises Conflict and nothing is written, unless what it asks for
    already holds, which is then done: the same change sent twice."""
    today = today or dt.date.today()
    if undo and (status is not None or date is not None or note is not None):
        raise ValueError("undo goes alone")
    if not undo and status is None and date is None and note is None:
        raise ValueError("nothing to change")
    with _lock:
        t = load()
        if t.problem:
            raise ValueError(t.problem)
        e = next((x for x in t.entries if x.key == (company, role)), None)
        if e is None:
            if not allow_new:
                raise ValueError(f"{TRACKER} has no application for {label(company, role)}")
            e = Entry(company=company, role=role)
            t.entries.append(e)
        if e.problem:
            raise ValueError(f"{label(company, role)} cannot change until its entry in "
                             f"{TRACKER} is fixed by hand: {e.problem}")
        moved = expect_last is not None and last_line(e) != expect_last.strip()
        renoted = expect_note is not None and e.note != clean_note(expect_note)
        if moved or renoted:
            if _already(e, status, date, note, undo):
                return e if (e.history or e.note or e.extra) else None
            was = ((f"its last change is now {last_line(e)}" if e.history else "it has no status now")
                   if moved else "its note was changed")
            raise Conflict(f"{label(company, role)} changed since this was shown: {was}. "
                           "Look again, then make the change.",
                           {"last": last_line(e), "note": e.note})
        if undo:
            if not e.history:
                raise ValueError("there is no change to undo")
            e.history.pop()
        if status is not None:
            status = " ".join(str(status).lower().split())
            if status not in STATUSES:
                raise ValueError(f"{status!r} is not a status; they are {', '.join(STATUSES)}")
            if status == e.status:
                raise ValueError(f"it is already {status}")
            if status not in can_move_to(e):
                raise ValueError(f"it already got to {e.reached}, so it cannot go back to "
                                 f"{status}; to fix a mistake, undo the last change")
            when = _date(today.isoformat() if date is None else date, e.since, today)
            e.history.append((when, status))
        elif date is not None:
            if not e.history:
                raise ValueError("give it a status before a date")
            before = e.history[-2][0] if len(e.history) > 1 else None
            e.history[-1] = (_date(date, before, today), e.history[-1][1])
        if note is not None:
            e.note = clean_note(note)
        kept = e if (e.history or e.note or e.extra) else None
        if kept is None:
            t.entries.remove(e)
        save(t)
        return kept


# --------------------------------------------------------------- reporting

def days_at(e: Entry, today: dt.date) -> int | None:
    """Days since the last change."""
    return (today - dt.date.fromisoformat(e.since)).days if e.history else None


def waiting_days(e: Entry, today: dt.date) -> int | None:
    """How long an application has sat at `applied`, once that is STALE_DAYS or more."""
    days = days_at(e, today)
    return days if e.status == "applied" and days is not None and days >= STALE_DAYS else None


def outcome(e: Entry, today: dt.date | None = None) -> str | None:
    """What the scan learns from one application:

    forward       a person answered with interest, at any point: the resume
                  cleared the screen, whatever came after;
    screened out  rejected before that, marked no response, or at applied for
                  STALE_DAYS with no word;
    waiting       at applied for less than that;
    withdrawn     the user stopped it, whatever stage it had reached;
    None          no status yet, or an entry that does not read."""
    if e.problem or not e.history:
        return None
    if e.status == "withdrawn":
        return "withdrawn"
    if STAGE.get(e.reached, 0) >= FORWARD:
        return "forward"
    if e.status == "applied":
        return "screened out" if waiting_days(e, today or dt.date.today()) else "waiting"
    return "screened out"   # rejected or no response, before anyone answered


def summary(e: Entry, today: dt.date | None = None) -> str:
    """One line on where it stands: "rejected 2026-09-20, after interviewing,
    applied 2026-08-14"."""
    today = today or dt.date.today()
    if e.problem:
        return f"cannot read: {e.problem}"
    if not e.history:
        return "no status yet"
    parts = [f"{e.status} {e.since}"]
    if e.status not in STAGE and STAGE.get(e.reached, 0) >= FORWARD:
        parts.append(f"after {e.reached}")
    if e.applied and e.applied != e.since:
        parts.append(f"applied {e.applied}")
    waiting = waiting_days(e, today)
    if waiting:
        parts.append(f"no word in {waiting} days")
    return ", ".join(parts)


def as_dict(e: Entry, today: dt.date | None = None) -> dict:
    """An entry as the page and `--outcomes --json` show it."""
    today = today or dt.date.today()
    return {
        "company": e.company, "role": e.role, "status": e.status, "since": e.since,
        "applied": e.applied, "history": [{"date": d, "status": s} for d, s in e.history],
        "note": e.note, "problem": e.problem, "outcome": outcome(e, today),
        "waiting": waiting_days(e, today), "summary": summary(e, today),
        "ended": e.status in ENDED, "moves": [] if e.problem else can_move_to(e),
    }


def roles_on_disk(folder: str) -> list[str]:
    """The roles filed in one employer's folder: each stem with a saved posting,
    or with a resume's .pdf and .tex both. A cover letter shares its role's stem,
    so it adds none, and hand-named files such as a transcript add none either."""
    try:
        files = {n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))}
    except OSError:
        return []
    roles = set()
    for name in files:
        if name.lower().endswith(POSTING):
            roles.add(name[:-len(POSTING)])
        stem, ext = os.path.splitext(name)
        if ext.lower() == ".tex" and (stem + ".pdf" in files or stem + ".PDF" in files):
            roles.add(stem)
    return sorted((r for r in roles if r.strip() and not r.startswith(".")
                   and not r.lower().endswith(LETTER)), key=str.casefold)

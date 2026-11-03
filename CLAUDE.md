# Working agreements for this project

These apply to anyone running this workflow. Rules that belong to one person live in
`CLAUDE.local.md`, which Claude Code loads alongside this file when it exists.

## Commits

Write the message describing what changed and why, nothing else.

## Ground truth — do not edit from a skill

| File | Role |
|---|---|
| `profile/profile.md` | Career profile, constraints, scoring rubric. Human-maintained. |
| `content/master.md` | Every resume fact. Facts come from the user: added by hand, or through the two interviews below. |
| `content/story.md` | Motivations and stories for cover letters, in the user's words. Human-maintained, plus the two interviews below. |

Skills and scripts **select** from these; they never invent, embellish, or infer a claim.
If a posting wants something the user genuinely lacks, that is a gap to report, not
something to write around. A cover letter says only what these files, the posting, or
the user in chat said first, and every number in it must come from one of them.

There are two exceptions, and both write only what the user said, in their words, after
the user approves it:

- **`/setup`** writes the first version of each file from the user's own resume and what
  they say in its interview. Each is a draft until the user has read all of it and
  approved it, and `/setup` never rewrites a file that exists unless the user asks it to.
- **The cover-letter interview** (`/cover-letter`, and `/tailor-digest` for roles ticked
  `cover letter`; added 2026-11-02) asks for what a letter needs that these files lack.
  It then adds the answers to `story.md`, and any new resume fact to `master.md`. It shows
  the exact text first and writes only what the user approves. It adds without rewriting
  or removing what is there, and it never touches `profile.md`.

## Things already decided — don't silently reverse them

- **Scraped job boards are opt-in, at the user's own risk.** LinkedIn, Indeed, and other
  boards whose terms prohibit scraping may be built as sources, but each one stays off by
  default, runs only when the user turns it on, and comes with a clear warning about the
  risk. Decided 2026-10-29, replacing an outright LinkedIn exclusion. The switches are
  `sources` in `profile/filters.yaml`. Only the user turns one on: `/setup` shows the
  warning, asks about each board separately, and turns on only the boards the user says
  yes to. Scrapers never log in, never use proxies, and keep the fixed pace in
  `scripts/jobspy_source.py`.
- **US only.** Sources, location matching, and pay parsing assume US postings
  (decided 2026-10-29).
- **iCIMS was attempted and abandoned.** Its WAF returns HTTP 405 to Python clients.
- **Scoring follows the rubric in `profile/profile.md`, not keyword overlap.** A role that
  fits what the profile says the user wants beats a keyword-perfect role that does not.
- **Resumes target a 30-second recruiter scan.** One page unless the user's `master.md`
  sets `max_pages`, no unexplained gaps, fewer strong entries over more thin ones.
- **Never widen scan filters to produce more results.** A thin digest is information.

## Personal data

`content/contact.local.md` is the only file holding contact details, and it is gitignored
so this repo stays scrubbed. Never write a phone number or email into a tracked file.

## Per-machine setup

Git config does not sync. On each machine, once:

```bash
git config pull.rebase true
cp content/contact.example.md content/contact.local.md   # then edit
```

Skills write commands as `python scripts/<name>.py`. Where uv is installed (there is a
`pyproject.toml`), run them as `uv run python scripts/<name>.py`; otherwise use the Python
that has the dependencies, such as `.venv/bin/python`. `python scripts/doctor.py` says
what is missing.

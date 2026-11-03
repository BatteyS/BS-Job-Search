# BS-Job-Search

A job scan that ranks postings against your own written profile, a resume builder that
selects from one file of your facts, and a cover-letter writer that cites a source for
every claim. All three run from [Claude Code](https://claude.com/claude-code). To see
what a filled-in profile looks like, start with [`examples/`](examples/README.md).

For how the pieces work and why, read [`ARCHITECTURE.md`](ARCHITECTURE.md), and
`CLAUDE.md` for the working agreements every skill follows.

## Setup

Four steps, then a check that tells you what is left.

**1. Get your own copy.** On [BS-Job-Search's GitHub page](https://github.com/BatteyS/BS-Job-Search),
choose **Use this template** and create a **private** repository. Private, because your profile and resume facts will
be tracked in it, and a fork of a public repository has to stay public. Then clone yours:

```bash
git clone <your-repo-url> job-search
cd job-search
git config pull.rebase true
```

**2. Python, with [uv](https://docs.astral.sh/uv/).** uv installs the Python this
workflow is pinned to (`.python-version`) and its packages, without touching any other
Python on the machine:

```bash
uv sync
```

```bash
uv sync --extra pdf --extra scraped
```

Add `--extra pdf` to read a PDF resume when building your profile, and `--extra scraped`
for the scraped job boards (below). Name every extra you want each time, as in
`uv sync --extra pdf --extra scraped`: a sync uninstalls any extra it is not given. Then
run every script as `uv run python scripts/<name>.py`, which keeps what is installed.

Without uv, any Python 3.10 or newer works: `python -m pip install pyyaml requests`, plus
`pypdf` for PDF resumes.

**3. LaTeX, which typesets resumes and letters.** Install a distribution that provides
`pdflatex`:

| System | Install |
|---|---|
| macOS | [BasicTeX](https://tug.org/mactex/morepackages.html) (`brew install --cask basictex`), then open a new terminal and add the packages the templates use: `sudo tlmgr install enumitem titlesec newtx fontaxes xstring kastrup tex-gyre` |
| Windows | [MiKTeX](https://miktex.org/download). It fetches missing packages the first time a resume builds. |
| Linux | `sudo apt install texlive-latex-recommended texlive-latex-extra texlive-fonts-extra`, or your distribution's equivalent |

On macOS, `/Library/TeX/texbin` must be on `PATH`. The installer adds it for new login
shells, so a terminal or app opened before the install will not find `pdflatex`.

**4. Check.**

```bash
uv run python scripts/doctor.py
```

Each line is `ok`, `MISSING` with the fix for your system, `DRAFT` for a file `/setup`
wrote that you have not finished reviewing, or `optional` for something only some
features need. It reads files and runs local tools only, and changes nothing.
Run it again whenever something stops working.

### Your profile

Open this folder in Claude Code and run **`/setup`**. It checks the machine, then
interviews you and writes six files, each described in
[`examples/README.md`](examples/README.md). Most of the time goes on your resume: it asks,
role by role, for the detail a resume leaves out, because every tailored resume is
selected from what you give it here. You can stop after any step; running `/setup` again
picks up where you left off.

| File | Holds |
|---|---|
| `content/contact.local.md` | Name, email, links. Start from `content/contact.example.md`. |
| `content/master.md` | Every resume fact you have. |
| `content/story.md` | What a cover letter needs that a resume does not. Start from `content/story.example.md`. |
| `profile/profile.md` | How a scan should judge a role for you. |
| `profile/clusters.yaml` | The kinds of role to look for. |
| `profile/filters.yaml` | Where to look, how much, and which sources. Metros to copy come from `presets/metros.yaml`. |

`/setup` also adds your API keys, the employers you most want to work for, and any scraped
boards you choose, then tunes the role clusters against real postings. You can write the
files by hand instead, starting from an example.

**`contact.local.md` is the one file that never syncs.** It is the only file holding
personal contact details, which is what lets the repository stay scrubbed, so it is
gitignored and has to be created once on each machine. `build_resume.py` stops with an
explicit message if it is missing rather than emitting a resume addressed from
`you@example.com`.

`content/master.md` can be plain text or LaTeX source; the builder detects which and
prints it on every build. Plain text is escaped for you, so write "R&D", "40%", "$1.2M"
as you would anywhere. Its front matter can set `format: text|latex`, `max_pages`, and
`section_order`, and any `# Section` (Certifications, Volunteer, ...) can appear on a
resume — see `.claude/skills/tailor-resume/SKILL.md`.

`content/story.md` is yours to write: why your field, what you want next, career moves
in your words, the stories behind your bullets. A letter can only say what that file,
`master.md`, the posting, or you in chat said first, and `scripts/build_letter.py`
refuses any number in a letter that none of its cited sources contains.

## Using it

Everything runs from Claude Code, in this folder:

1. **`/job-scan`** asks which kinds of role to look for, then fetches postings, filters
   them, scores what is left against `profile/profile.md`, and writes
   `digests/YYYY-MM-DD.md`.
2. **Mark the digest.** Tick `apply`, or `skip` with a reason, on each entry, and tick
   `cover letter` too on any apply that should get one. The reasons go into
   `profile/feedback.md`, and every later scan reads them. "skip — wants 8+ years"
   teaches the scorer something; "skip" alone does not.
3. **`/tailor-digest`** builds a tailored resume for every `apply`, and a cover letter
   for every `cover letter`. **`/tailor-resume`** builds one resume for a single posting.
   Each reads the posting in full, picks from `master.md`, and files the PDF under
   `Applications/<Company>/`.
4. **`/cover-letter`** writes a letter whose every claim cites `master.md`, `story.md`,
   the posting, or something you said, and refuses any number none of those holds. When
   a letter needs a story your files do not have, it asks you for it first.

Nothing edits your profile or resume facts behind your back. Skills select from them;
when a posting wants something you do not have, that is reported as a gap. The only
additions come from interviews you take part in: `/setup`, and a cover letter that asks
for a story. Each shows you the exact text and writes only what you approve.

### A page for the digest

Marking a digest means editing checkboxes in a `.md` file. If you would rather click:

```bash
uv sync --extra ui
```

```bash
uv run python ui/server.py
```

That opens a page at `http://127.0.0.1:8765`, on this machine only (run it again while it
is up and it opens the running page), where you can read
each digest and tick `apply`, `skip` with a reason, and `cover letter` (it writes the
boxes back into the file), turn the marks into a `feedback.md` section and append it once
nothing is left to settle, see what was filed under `Applications/` with each PDF beside
its posting, run `doctor.py` and the posting fetch with their output live, and read your
profile files. Name every extra on each `uv sync`, as above.

The page can also run the skills. Its Runs tab has a button for each of `/job-scan`,
`/tailor-digest`, `/tailor-resume`, `/cover-letter` and `/setup`; each starts the real
skill through your own Claude Code, in this folder, with your own login, and shows the
conversation as it goes. Everything Claude Code would stop and ask you in a terminal
becomes a card in the page: a command no rule allows, a question with options, and every
write to `master.md`, `story.md` or `profile.md`, which shows the exact text and waits for
your approval. A question asked in plain words gets a reply box. One skill runs at a time.
This needs Claude Code installed and logged in on the machine. The page finds the
binary on PATH, in the usual install places, or inside the Claude desktop app
(`BS_CLAUDE_BIN` points it somewhere else), and `doctor.py` says which one it found. The
desktop app's own login does not carry over to that binary; if it is not logged in,
doctor and the page print the one command to run, which opens your browser to sign in.

### API keys

Two free sources need a key, each kept in a gitignored file. `doctor.py` says which are
missing and where to register:

| Source | Register | Key file |
|---|---|---|
| Adzuna, a job aggregator | [developer.adzuna.com](https://developer.adzuna.com/signup) | copy `sources/adzuna.example.yaml` to `sources/adzuna.local.yaml` |
| USAJOBS, federal jobs | [developer.usajobs.gov](https://developer.usajobs.gov/APIRequest) | copy `sources/usajobs.example.yaml` to `sources/usajobs.local.yaml` |

A source you do not want can be turned off under `sources` in `profile/filters.yaml`
instead.

### What a scan costs

The scan's scoring step is Claude reading every candidate posting, so its cost is
roughly the number of candidates times how much of each it reads. `max_candidates` and
`max_description_chars` in `profile/filters.yaml` set both. The examples use 150 and
3,000, a small first scan; raise them once the digests look right.

### Scraped job boards: Indeed, LinkedIn, Glassdoor, ZipRecruiter

**Use at your own risk.** All four boards' terms prohibit scraping, and these sources
scrape them. Each is off until you turn it on under `sources` in `profile/filters.yaml`,
and every scan prints a warning for each one it runs. Two things limit the risk and are
not settings: nothing logs in, so no account of yours is involved, and each board runs at
a fixed, polite pace, stopping for the rest of the run if the board starts refusing
requests or two queries in a row fail. LinkedIn is the touchiest: it fetches each posting's page and is capped at 40
queries a run. There is no proxy support, on purpose. Google Jobs is not offered: JobSpy
lists it as currently unavailable.

All four go through [JobSpy](https://github.com/speedyapply/JobSpy). With uv, install it
with `uv sync --extra scraped`, adding `--extra pdf` if you use that one. `uv.lock` pins
JobSpy 1.4.1, the release this workflow is written against. Verified 2026-11-02 on
macOS: six live Bay Area queries per board returned postings with full descriptions
from Indeed (140), Glassdoor (103), and ZipRecruiter (35). The 1.1 release it replaced
returned nothing from Glassdoor or ZipRecruiter.

Without uv, JobSpy needs **Python 3.10 or newer**. Name the version: an unpinned
install can resolve to an old release whose `scrape_jobs()` takes different arguments.
1.4.1 installs from prebuilt wheels on Python 3.10 through 3.14:

```bash
python -m pip install python-jobspy==1.4.1
```

Either way, check it took with a five-result search for one of your clusters and
metros:

```bash
python scripts/jobspy_source.py --clusters <cluster> --metros <metro> --sites indeed --limit 5
```

`--sites` takes any of `indeed,linkedin,glassdoor,ziprecruiter`, which is also the way to
try one board before turning it on for every scan.

## Working across machines

Plain git, pushed manually. There is no daemon and no scheduled commit — the point of
tracking `content/master.md` and `profile/profile.md` is a readable history of what
changed and why, and automatic commits would bury that. Helper: `.\sync.ps1 start|done|status`.

```bash
git pull        # before you start
# ...work...
git add -A && git commit -m "..." && git push
```

Deliberately **not** synced, and per-machine by design:

| Path | Why |
|---|---|
| `content/contact.local.md` | Keeps personal details out of the repo. Recreate per machine. |
| `sources/adzuna.local.yaml`, `sources/usajobs.local.yaml` | API credentials. |
| `data/seen.sqlite`, `data/last-run.json` | Local scan cache and state. A fresh machine re-surfaces old postings once, which is harmless; tracking it would conflict on every pull. |
| `Applications/` | Submitted resumes and the posting text each was written against. Sensitive even in a private repo, and binaries bloat history permanently. |
| `Previous Employment Records/` | Same reasoning, higher sensitivity. |
| `Resume/pdf/`, `Resume/build/`, `Resume/LaTeX/editing_*.tex` | Build outputs. The content is in `master.md`; the copy that matters is filed beside each application. |

Because `Applications/` is not in the repo, **it is not backed up by pushing.** If that
folder matters to you — and it doubles as the application tracker — back it up another way.

## Updating from the template

Improvements to the template reach your copy when you ask for them. Add the template as
a remote once, then check out its engine files whenever you want an update. Your own
profile, resume facts, and digests are not among them, so nothing of yours is touched:

```bash
git remote add template https://github.com/BatteyS/BS-Job-Search.git
git fetch template
git checkout template/main -- .claude .github scripts presets tests examples Resume/LaTeX \
    content/contact.example.md content/story.example.md pyproject.toml uv.lock \
    .python-version .gitattributes .gitignore CLAUDE.md README.md ARCHITECTURE.md \
    LICENSE scan.ps1 sync.ps1
```

That is every file the template ships, the list `scripts/export_template.py` exports. Read
the diff, run `uv sync` again with your extras if `uv.lock` changed, run the tests, and
commit.

## Tests

```bash
uv run --group test pytest
```

They use the example profiles and temporary files only, never your own profile or the
network. The two that build a resume PDF are skipped where `pdflatex` is missing.

## License

MIT. See [`LICENSE`](LICENSE).

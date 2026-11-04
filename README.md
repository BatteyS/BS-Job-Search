# BS-Job-Search

A job scan that ranks postings against your own written profile, a resume builder that
selects from one file of your facts, and a cover-letter writer and interview prep sheet
that cite a source for every claim. All of it runs from
[Claude Code](https://claude.com/claude-code), and you can drive it from a web page on
your own machine. To see that page before
installing anything, open the [example demos](https://batteys.github.io/BS-Job-Search/);
for what a filled-in profile looks like, see [`examples/`](examples/README.md).

For how the pieces work and why, read [`ARCHITECTURE.md`](ARCHITECTURE.md), and
`CLAUDE.md` for the working agreements every skill follows.

## Get started

The page is the main way to use this. One command starts it, and from there it walks
you through the rest: its **Setup** tab says what this machine still needs, and its
**Set up** button interviews you and writes your profile, with a card to approve every
write to your resume facts.

**1. Install uv**, which runs the Python this workflow is pinned to and installs its
packages, without touching any other Python on the machine:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows, run `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
instead. Either way, open a new terminal afterwards, so it finds uv.

**2. Get a copy and start the page:**

```bash
git clone https://github.com/BatteyS/BS-Job-Search.git job-search
cd job-search
uv run ui/server.py
```

The first start takes a minute or two while uv fetches Python and the packages; then
`http://127.0.0.1:8765` opens in your browser. The page runs on this machine only and
has no login, so leave it that way. Keep the terminal open while you use it, and stop it
with Ctrl+C. From then on, double-click `start.command` in the `job-search` folder
(`start.cmd` on Windows) to open it, or run `uv run ui/server.py` there.

macOS offers to install `git` the first time you run it. On Windows, install
[Git for Windows](https://git-scm.com/downloads/win) first.

**3. Follow the Setup tab.** The page opens on it until your profile is written.

- **Claude Code** comes first. The page runs your own copy, with your own login, to do
  the interviewing, scoring and writing; it needs a paid Claude plan or an Anthropic
  Console account. If it is not installed or not logged in, the tab shows the one command
  to run for your system. Run it in a new terminal window, since the first one is running
  the page, then press **Check again**.
- Then press **Set up**. It interviews you and writes six files, each described in
  [`examples/README.md`](examples/README.md). Most of the time goes on your resume: it
  asks, role by role, for the detail a resume leaves out, because every tailored resume
  is selected from what you give it here.
- Everything Claude would ask in a terminal appears as a card in the page, and each write
  to `master.md`, `story.md` or `profile.md` shows the exact text and waits for your
  approval. You can stop after any step; press **Set up** again and it picks up where you
  left off.
- The same tab saves the two API keys a scan needs, and says what to install before your
  first resume: LaTeX, which typesets resumes and letters (see [LaTeX](#latex) below). It
  can install while you go; afterwards, start the page again, so it finds LaTeX.

Your copy stays on this machine: nothing in it is pushed anywhere unless you set that up.
To back it up or use a second machine, see
[Backing up, and a second machine](#backing-up-and-a-second-machine).

When setup finishes, go to [Using it](#using-it): **Job scan**, then mark the digest in
the **Digests** tab.

## Setup without the page

Everything the page does also runs from Claude Code in a terminal, and these are the
details behind the steps above.

**Python.** `uv run` sets up Python and every package the first time, so there is
nothing to install but uv: run every script as `uv run python scripts/<name>.py`. The one
optional extra is `scraped`, for the scraped job boards (below), which setup installs if
you turn a board on. A plain `uv sync` uninstalls an extra it is not given, so name it
there: `uv sync --extra scraped`.

Without uv, any Python 3.10 or newer works: `python -m pip install pyyaml requests pypdf`,
plus `fastapi uvicorn claude-agent-sdk` for the page.

### LaTeX

LaTeX typesets resumes and letters. Install a distribution that provides `pdflatex`:

| System | Install |
|---|---|
| macOS | [BasicTeX](https://tug.org/mactex/morepackages.html) (`brew install --cask basictex`), then open a new terminal and add the packages the templates use: `sudo tlmgr update --self && sudo tlmgr install enumitem titlesec newtx fontaxes xstring kastrup tex-gyre`. The first half updates tlmgr itself, which refuses to install anything while it is out of date. If it reports that cross-release updates are not supported, your BasicTeX is from an earlier year's TeX Live: reinstall it (`brew reinstall --cask basictex`) and run the line again. |
| Windows | [MiKTeX](https://miktex.org/download). When its installer asks, let it install missing packages on the fly (MiKTeX Console's Settings change it later): the first resume build then fetches them without stopping to ask. |
| Linux | `sudo apt install texlive-latex-recommended texlive-latex-extra texlive-fonts-extra`, or your distribution's equivalent |

On macOS, `/Library/TeX/texbin` must be on `PATH`. The installer adds it for new login
shells, so a terminal or app opened before the install will not find `pdflatex`. Restart
the page's server after installing.

### Check

```bash
uv run python scripts/doctor.py
```

Each line is `ok`, `MISSING` with the fix for your system, `DRAFT` for a file `/setup`
wrote that you have not finished reviewing, or `optional` for something only some
features need. It reads files and runs local tools only, and changes nothing. The page's
Setup tab shows the same checks. Run it again whenever something stops working.

### Setup from the terminal

Open this folder in Claude Code and run **`/setup`**. It does what the page's **Set up**
button does, as a conversation in the terminal.

### Your profile

Setup writes these six files. You can stop after any step, and you can write the files
by hand instead, starting from an example.

| File | Holds |
|---|---|
| `content/contact.local.md` | Name, email, links. Start from `content/contact.example.md`. |
| `content/master.md` | Every resume fact you have. |
| `content/story.md` | What a cover letter or an interview needs that a resume does not. Start from `content/story.example.md`. |
| `profile/profile.md` | How a scan should judge a role for you. |
| `profile/clusters.yaml` | The kinds of role to look for. |
| `profile/filters.yaml` | Where to look, how much, and which sources. Metros to copy come from `presets/metros.yaml`. |

Setup also adds your API keys, the employers you most want to work for, and any scraped
boards you choose, then tunes the role clusters against real postings.

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

Each step below is a button in the page's **Runs** tab and a slash command in Claude Code
in a terminal, in this folder:

1. **Job scan** (`/job-scan`) asks which kinds of role to look for, then fetches postings,
   filters them, scores what is left against `profile/profile.md`, and writes
   `digests/YYYY-MM-DD.md`.
2. **Mark the digest.** In the **Digests** tab, tick `apply`, or `skip` with a reason, on
   each entry, and tick `cover letter` too on any apply that should get one. (In a file,
   these are checkboxes in the `.md`.) The reasons go into `profile/feedback.md`, and
   every later scan reads them. "skip — wants 8+ years" teaches the scorer something;
   "skip" alone does not.
3. **Tailor digest** (`/tailor-digest`) builds a tailored resume for every `apply`, and a
   cover letter for every `cover letter`. **Tailor resume** (`/tailor-resume`) builds one
   resume for a single posting. Each reads the posting in full, picks from `master.md`,
   and files the PDF under `Applications/<Company>/`, which the **Applications** tab shows
   with each PDF beside its posting.
4. **Cover letter** (`/cover-letter`) writes a letter whose every claim cites `master.md`,
   `story.md`, the posting, or something you said, and refuses any number none of those
   holds. When a letter needs a story your files do not have, it asks you for it first.
5. **Interview prep** (`/interview-prep`), once you have an interview, writes a prep
   sheet for one application: the questions its posting makes likely, each answered from
   your files as situation, action, and result; the gaps it exposes, each with an honest
   way to answer it; and questions to ask them. Every answer lists its sources, under the
   cover letter's checks, and a question your files cannot answer stays on the sheet as
   one to prepare. In the page, pick the application from the postings filed under
   `Applications/`; the sheet is filed beside its resume as
   `<Job Title> - interview prep.md`, and the Applications tab shows it.
6. **Track what you send.** In the **Applications** tab, mark each application `applied`
   when it goes out, then `heard back`, `interviewing`, `offer` and `accepted`, or
   `rejected`, `withdrawn` or `no response`, as it moves. Each change is dated, today
   unless you set it back, and saved to `profile/applications.yaml`. Every later scan
   reads what came of each: roles like the ones that got an answer score up, and a trait
   shared by several that got none scores down.

Nothing edits your profile or resume facts behind your back. Skills select from them;
when a posting wants something you do not have, that is reported as a gap. The only
additions come from interviews you take part in: setup, and a cover letter or interview
prep sheet that asks for a story. Each shows you the exact text and writes only what you
approve.

### About the page

Start it with `start.command` (`start.cmd` on Windows) or `uv run ui/server.py`; starting
it again while it is up opens the running page. Besides running the skills, it lets you
read each digest and mark it (it writes the boxes back into the file), turn the marks
into a `feedback.md` section and append it once nothing is left to settle, record where
each application stands, run `doctor.py` and the posting fetch with their output live,
and read your profile files. Its Setup tab shows how far setup has got and everything
`doctor.py` checks, and saves your API keys. It also keeps your copy current, and backed
up once you have somewhere to back it up to: see
[Updating from the template](#updating-from-the-template) and
[Backing up, and a second machine](#backing-up-and-a-second-machine).

The **Applications** tab opens on a table of every application: each role filed under
`Applications/`, and each one `profile/applications.yaml` holds, even when its files are
on another machine. A status moves forward or ends, and **Undo** removes the last change
if you picked the wrong one. A note can hold what they said or why it ended, which the
scan reads too, but not an email address or a phone number, since the file is tracked.

It answers only requests addressed to `127.0.0.1` or `localhost`, and none from a page
on another site, so a website open in the same browser can neither read it nor start a
skill or answer a card.

Each skill runs on a model and effort level picked for it, shown on its button and at
the top of its run with the reason:

- Interviews and scans go to Sonnet, which uses less of a Claude plan.
- Tailored resumes, cover letters, and interview prep go to Opus at high effort, where
  the judgment is the point.
- Tailoring a digest follows what is marked in it: Sonnet for many resumes without
  letters, Opus once letters are involved.
- When your plan's 5-hour session or week is 80% used, a run headed for Opus goes to
  Sonnet instead.

A run keeps its model and effort for all its replies: switching mid-conversation throws
away Claude Code's cache and costs more than it saves. To choose yourself, set **Model**
and **Effort** at the top of the Runs tab; **Auto** leaves it to the page.

The header shows how much of your Claude plan's 5-hour session and week is used, as
Claude Code reports it on every request a run makes. Between runs the page asks Claude
Code's `/usage`, which calls no model, so a check costs nothing; click the header to
check again. Each turn of a run shows its tokens, and the run's cost so far at API
prices, which on a subscription measures size and is not a charge.

Each skill the **Runs** tab starts is the real skill, through your own Claude Code, in
this folder, with your own login, and the page shows the conversation as it goes.
Everything Claude Code would stop and ask you in a terminal becomes a card in the page: a
command no rule allows, a question with options, and every write to `master.md`,
`story.md` or `profile.md`, which shows the exact text and waits for your approval. A
question asked in plain words gets a reply box. One skill runs at a time.

This needs Claude Code installed and logged in on the machine. The page finds the binary
on PATH, in the usual install places, or inside the Claude desktop app (`BS_CLAUDE_BIN`
points it somewhere else), and `doctor.py` says which one it found. The desktop app's own
login does not carry over to that binary; if it is not logged in, doctor and the Setup
tab print the one command to run, which opens your browser to sign in.

### API keys

Two free sources need a key, each kept in a gitignored file. The page's Setup tab has a
form for each that saves the key there; from a terminal, copy the example to the key
file and paste the key in. `doctor.py` says which are missing and where to register:

| Source | Register | Key file |
|---|---|---|
| Adzuna, a job aggregator | [developer.adzuna.com](https://developer.adzuna.com/signup) | `sources/adzuna.local.yaml`, from `sources/adzuna.example.yaml` |
| USAJOBS, federal jobs | [developer.usajobs.gov](https://developer.usajobs.gov/APIRequest) | `sources/usajobs.local.yaml`, from `sources/usajobs.example.yaml` |

A source you do not want can be turned off under `sources` in `profile/filters.yaml`
instead.

### What a scan costs

The scan's scoring step is Claude reading every candidate posting, so its cost is
roughly the number of candidates times how much of each it reads. From the page it runs
on Sonnet at medium effort unless you pick otherwise. `max_candidates` and
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
with `uv sync --extra scraped`. `uv.lock` pins
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

## Backing up, and a second machine

Your copy is a clone of the public template, so nothing in it leaves this machine until
you push it somewhere. To back it up, or to work on a second machine, push it to a
**private** repository of your own: private, because your profile and resume facts are
tracked in it. Not a fork of the template, because a fork of a public repository has to
stay public.

Once, create an empty private repository on GitHub, with no README, then in this folder:

```bash
git remote rename origin template
git remote add origin <your-private-repo-url>
git push -u origin main
git config pull.rebase true
```

Pushing needs you signed in to GitHub on this machine, for example with GitHub's CLI
(`gh auth login`). On a second machine, clone your private repository rather than the
template, run `git config pull.rebase true` there too (git config does not sync), and
start the page the same way.

From then on, the page's Setup tab backs it up. It lists the files of yours that changed
since the last backup, and **Back up now** commits them, with a message you type saying
what changed, then pushes them. It commits only your own files, the ones in `profile/`,
`content/`, `digests/` and `sources/`, never your contact details or keys, and it never
pushes to a repository anyone can read: it checks first, and refuses one that is public.
When your other machine has backed up something this one lacks, the page says so, and
**Update**, or the next backup, brings it in first. If both machines changed the same
lines of a file, it stops, undoes the merge, and names the file, and both versions are
kept: this machine's here, the other's in the backup.

Nothing commits or pushes on its own. There is no daemon and no scheduled commit — the
point of tracking `content/master.md` and `profile/profile.md` is a readable history of
what changed and why, and automatic commits would bury that. From a terminal, it is plain
git:

```bash
git pull        # before you start
# ...work...
git add -A && git commit -m "..." && git push
```

Deliberately **not** synced, and per-machine by design:

| Path | Why |
|---|---|
| `content/contact.local.md` | Keeps personal details out of the repo. Recreate per machine: Set up writes it. |
| `sources/adzuna.local.yaml`, `sources/usajobs.local.yaml` | API credentials. Save them again from the Setup tab. |
| `data/seen.sqlite`, `data/last-run.json` | Local scan cache and state. A fresh machine re-surfaces old postings once, which is harmless; tracking it would conflict on every pull. |
| `Applications/` | Submitted resumes and the posting text each was written against. Sensitive even in a private repo, and binaries bloat history permanently. |
| `Previous Employment Records/` | Same reasoning, higher sensitivity. |
| `Resume/pdf/`, `Resume/build/`, `Resume/LaTeX/editing_*.tex` | Build outputs. The content is in `master.md`; the copy that matters is filed beside each application. |

Because `Applications/` is not in the repo, **it is not backed up by pushing**: if its
files matter to you, back it up another way. Where each application stands is kept
apart, in `profile/applications.yaml`, which is tracked, so the statuses and their dates
reach your other machine even though the files do not.

## Updating from the template

Improvements to the template reach your copy when you ask for them. The page checks
quietly when it opens, and every hour while it stays open; when the template has updates,
a notice beside the tabs says how many, and the Setup tab shows what each one changed.
**Update** brings them in. The template holds none of your files, so an update never
touches your profile, resume facts, or digests. When one changes the page's own code or
packages, the page says to start it again, which installs anything new.

An update never forces anything and never rebases. If it would write over a change of
yours that is not committed, or a change of yours conflicts with one of the template's,
it stops, changes nothing, and names the files.

What **Update** does depends on how your copy was made:

| Your copy | Update | From a terminal |
|---|---|---|
| A clone of the template ([Get started](#get-started)) | Brings in the template's new commits | `git pull --rebase` |
| Backed up to a private repository ([above](#backing-up-and-a-second-machine)) | Brings in what your other machine backed up, merges the template's updates, and pushes, so the backup has them too | `git pull --no-rebase template main`, then `git push` |
| Made with GitHub's **Use this template** | Takes the template's new files one by one, keeping any file only you changed, and joins the two histories, so later updates are ordinary merges | below |

A copy made with **Use this template** shares no history with the template. The page
links it to the template with **Link to the template**. From a terminal, add the
template as a remote once, then check its files out whenever you want an update:

```bash
git remote add template https://github.com/BatteyS/BS-Job-Search.git
git fetch template
git checkout template/main -- .claude .github scripts presets tests examples ui Resume/LaTeX \
    content/contact.example.md content/story.example.md sources/adzuna.example.yaml \
    sources/usajobs.example.yaml pyproject.toml uv.lock .python-version .gitattributes \
    .gitignore CLAUDE.md README.md ARCHITECTURE.md LICENSE start.command start.cmd
```

That is every file the template ships, the list `scripts/export_template.py` exports. It
overwrites any change of yours to those files, and keeps a file the template has dropped,
which the page's **Update** does neither of. Read the diff, run the tests, and commit.

## Tests

```bash
uv run --group test pytest
```

They use the example profiles and temporary files only, never your own profile or the
network. The two that build a resume PDF are skipped where `pdflatex` is missing.

## License

MIT. See [`LICENSE`](LICENSE).

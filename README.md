# BS-Job-Search

A job scan that ranks postings against your own written profile, a resume builder that
selects from one file of your facts, and a cover-letter writer and interview prep sheet
that cite a source for every claim. All of it runs from
[Claude Code](https://claude.com/claude-code), driven from a web page on your own
machine. To see that page before installing anything, open the
[example demos](https://batteys.github.io/BS-Job-Search/).

## Get started

You need a paid Claude plan (any of them, including one from your employer) or an
Anthropic Console account, since the page runs your own Claude Code and the free plan
does not include it. Installing takes about fifteen minutes. The setup interview that
follows takes an hour or more, most of it on your resume, and you can stop and pick it up
again at any point.

Pick your system, then go on to [The Setup tab](#the-setup-tab).

### On a Mac

Open Terminal (in Applications, then Utilities), paste this line, and press Return:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/BatteyS/BS-Job-Search/main/install.sh)"
```

It installs what is missing, all of it into your own home folder: Apple's Command Line
Tools, uv, Claude Code and its sign-in, your copy of this template in `~/job-search`,
LaTeX for the resumes, and **Job Search** on your Desktop. It says what it is doing as it
goes, asks for no password itself (Apple's window for the Command Line Tools may), and
asks whether you want Job Search on your phone too. When it finishes, the page is open in
your browser, and the Terminal window can be closed.

From then on, double-click **Job Search** on your Desktop whenever you want the page. It
opens in your browser with no Terminal window, and stops by itself ten minutes after you
close the page's last tab.

If the installer stops, it says why, and running the same line again picks up where it
stopped: see [If the Mac installer stops](#if-the-mac-installer-stops). It needs macOS 13
(Ventura) or newer. Do not download this repository as a ZIP instead: macOS quarantines
what a browser downloads and refuses to open `start.command` from it.

### On Windows

1. Install [Git for Windows](https://git-scm.com/downloads/win).
2. Install [uv](https://docs.astral.sh/uv/), which runs the Python this workflow is
   pinned to without touching any other Python on the machine. In PowerShell:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Then open a new terminal, so it finds uv.
3. Get a copy and start the page:

   ```powershell
   git clone https://github.com/BatteyS/BS-Job-Search.git job-search
   cd job-search
   uv run ui/server.py
   ```

   The first start takes a minute or two while uv fetches Python and the packages; then
   `http://127.0.0.1:8765` opens in your browser. The page runs on this machine only and
   has no login, so leave it that way. Keep the terminal open while you use the page, and
   stop it with Ctrl+C.
4. Install Claude Code, if the Setup tab says it is missing, in PowerShell:

   ```powershell
   irm https://claude.ai/install.ps1 | iex
   ```

   Then sign in with `claude auth login` (`claude auth login --console` for a Console
   account), which opens your browser, and press **Check again** on the Setup tab.
5. Before your first resume, install [MiKTeX](https://miktex.org/download), which
   typesets resumes and letters. When its installer asks, let it install missing packages
   on the fly. This can wait until you need it.

From then on, double-click `start.cmd` in the `job-search` folder to open the page. Keep
its window open while you use the page; closing it stops the page.

### On Linux

1. Install git if it is missing (`sudo apt install git`, or your distribution's
   equivalent), then [uv](https://docs.astral.sh/uv/), which runs the Python this
   workflow is pinned to without touching any other Python on the machine:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   Then open a new terminal, so it finds uv.
2. Get a copy and start the page:

   ```bash
   git clone https://github.com/BatteyS/BS-Job-Search.git job-search
   cd job-search
   uv run ui/server.py
   ```

   The first start takes a minute or two while uv fetches Python and the packages; then
   `http://127.0.0.1:8765` opens in your browser. The page runs on this machine only and
   has no login, so leave it that way. Keep the terminal open while you use the page, and
   stop it with Ctrl+C.
3. Install Claude Code, if the Setup tab says it is missing:

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   ```

   Then sign in with `claude auth login` (`claude auth login --console` for a Console
   account), which opens your browser, and press **Check again** on the Setup tab.
4. Before your first resume, install LaTeX, which typesets resumes and letters:

   ```bash
   sudo apt install texlive-latex-recommended texlive-latex-extra texlive-fonts-extra
   ```

   or your distribution's equivalent. This can wait until you need it.

From then on, run `uv run ui/server.py` in the `job-search` folder to open the page, or
double-click `start.command` there.

### The Setup tab

The page opens on it until your profile is written, and it says what this machine still
needs.

- **Claude Code** comes first. If it is not installed or not signed in, the tab shows the
  one command to run for your system. Run it in a terminal (a new one, if the page runs
  in one), then press **Check again**.
- Press **Set up**. It interviews you and writes your profile: your contact details,
  every resume fact you have, the stories a cover letter needs, how a scan should judge a
  role for you, the kinds of role to look for, and where to look. Most of the time goes
  on your resume, role by role, because every tailored resume is selected from what you
  give it here.
- Everything Claude would ask in a terminal appears as a card in the page, and every
  write to your resume facts, stories or profile shows the exact text and waits for your
  approval. Stop after any step; press **Set up** again and it picks up where you left
  off.
- The same tab saves the two free API keys a scan needs, with a link to register for
  each, and says when LaTeX is still missing ([LaTeX](#latex) lists the installs). On a
  Mac, **Install LaTeX** installs it while you go.

When it says you are set up, run **Job scan**, then mark the digest in the **Digests**
tab: [Using it](#using-it) has the whole loop. Your copy stays on this machine, and
nothing in it is sent anywhere unless you set that up: see
[Backing up, and a second machine](#backing-up-and-a-second-machine).

## Using it

Each step is a button in the page's **Runs** tab, and a slash command in Claude Code in
this folder:

1. **Job scan** (`/job-scan`) asks which kinds of role to look for, then fetches postings,
   filters them, scores what is left against your profile, and writes
   `digests/YYYY-MM-DD.md`.
2. **Mark the digest.** In the **Digests** tab, tick `apply`, or `skip` with a reason, on
   each entry, and tick `cover letter` too on any apply that should get one. (In a file,
   these are checkboxes in the `.md`.) The reasons go into `profile/feedback.md`, and
   every later scan reads them. "skip — wants 8+ years"
   teaches the scorer something; "skip" alone does not.
3. **Tailor digest** (`/tailor-digest`) builds a tailored resume for every `apply`, and a
   cover letter for every `cover letter`. **Tailor resume** (`/tailor-resume`) builds one
   resume for a single posting. Each reads the posting in full, picks from your resume
   facts, and files the PDF under `Applications/<Company>/`, which the **Applications**
   tab shows with each PDF beside its posting.
4. **Cover letter** (`/cover-letter`) writes a letter whose every claim cites your resume
   facts, your stories, the posting, or something you said, and refuses any number none
   of those holds. When a letter needs a story your files do not have, it asks you for it
   first.
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
   unless you set it back, and saved to `profile/applications.yaml`, and every later scan
   reads what came of each: roles
   like the ones that got an answer score up, and a trait shared by several that got none
   scores down.

Nothing edits your profile or resume facts behind your back. Skills select from them;
when a posting wants something you do not have, that is reported as a gap. The only
additions come from interviews you take part in: setup, and a cover letter or interview
prep sheet that asks for a story. Each shows you the exact text and writes only what you
approve.

## On your phone

On a Mac, Job Search can be an icon on your phone's home screen too, opening the same
page from anywhere, while the page and everything in it stay on your Mac. It takes the
free [Tailscale](https://tailscale.com/download) app on the Mac and on the phone, signed
in to the same account. Say yes when the Mac installer asks about your phone, or run this
in Terminal:

```bash
cd ~/job-search && sh install.sh --phone
```

It says when to install or sign in to Tailscale, and may print a `login.tailscale.com`
link to turn HTTPS on for your tailnet: open it (hold Command and double-click it) and
click **Enable**. Then it prints your Mac's address,
`https://<your-mac>.<your-tailnet>.ts.net`, which the Setup tab shows too. On the phone,
sign in to the Tailscale app,
open that address in Safari (Chrome on Android), and choose **Share**, then **Add to Home
Screen**. The icon opens the page full screen, like an app, laid out for a phone.

Three things to know:

- **The Mac has to be awake for anything to change.** A Mac sleeps on its own once its
  display turns off, even plugged in, and a laptop also sleeps with its lid closed; then
  the phone cannot reach it. Keep it plugged in and turn on **Prevent automatic sleeping
  on power adapter when the display is off**, in System Settings, Battery, Options (on a
  desktop Mac, **Prevent automatic sleeping when the display is off**). After a restart,
  someone has to log in on the Mac first. Nothing here changes these settings for you.
- **While the Mac is away, the icon still opens.** The phone keeps a copy of the page
  from its last visit: the digests, the applications and the profile files are there to
  read, and a banner says when the copy is from. A tick or a status change waits on the
  phone, counted in the header, and goes to the Mac once it answers; if the Mac's file
  changed meanwhile (a box ticked there, a scan), the page shows both and asks which to
  keep. Keep the app open for that: on an iPhone nothing is sent while it is closed, and
  removing the icon from the home screen loses what has not been sent. Scans, resumes,
  letters and the Runs and Setup tabs need the Mac. Under **This phone** in the Setup tab,
  opened on the phone, you choose what the copy holds: your profile files (kept unless
  you turn them off) and documents filed in the last 30 days (kept only if you turn them
  on, since resumes and letters carry your contact details). It never holds your keys.
  **Forget this phone's copy** there deletes it all and stops keeping one. A filed PDF
  has a **Share** button on the phone, for the whole PDF: Quick Look, Files, Print.
- **If the icon opens to an error**, the phone has no copy yet and could not reach the
  Mac: the first open needs the Mac. Wake it, check that Tailscale is on, on the phone,
  then swipe Job Search away in the phone's app switcher and open it again.

[How phone access works](#how-phone-access-works) has the rest, including how to turn it
off.

## If something stops

The Setup tab's **Check again** says what is missing and how to fix it. From a terminal,
the same checks are:

```bash
uv run python scripts/doctor.py
```

### If the Mac installer stops

It says why, and running the same line again picks up where it stopped. Everything it ran
is in `~/Library/Logs/BS Job Search install.log`, and everything the page prints, in
`~/Library/Logs/BS Job Search.log`.

| What happens | What to do |
|---|---|
| It needs macOS 13 or newer | Claude Code does not run on older macOS. System Settings, General, Software Update says whether this Mac can take a newer one. |
| Apple's window for the Command Line Tools closed, or shows an error | Press Return when the installer asks, to open it again. Failing that, download Command Line Tools for Xcode from [developer.apple.com/download/all](https://developer.apple.com/download/all/) (it needs an Apple ID, and installing it needs an administrator of the Mac), then run the line again. |
| The Command Line Tools are installed, but macOS looks in the wrong place | The installer says so. `sudo xcode-select --reset` points macOS at them. |
| Xcode's license has not been accepted | Xcode is installed but has never been opened: run `sudo xcodebuild -license accept` once. |
| `~/.local` belongs to another user | An earlier install run with `sudo` made it root's. The installer prints the `sudo chown` command that gives it back, with your name and folder filled in. Never run the installer itself with `sudo`. |
| A fix above starts with `sudo` | It needs an administrator of this Mac. If you are not one, ask whoever is: they can run it from their own account, or in your Terminal window after `su` and their account name. |
| On a company network | One that inspects HTTPS breaks uv's downloads; the installer notices, and switches uv to the Mac's own certificates (`native-tls = true` in `~/.config/uv/uv.toml`). |
| macOS asks whether Terminal may use the Desktop | Click Allow. If you did not, Job Search is in the Applications folder in your home folder, to drag where you like. |
| Terminal runs under Rosetta | It works, but slowly. Untick Open using Rosetta in Terminal's Get Info, in Finder. |
| macOS asks whether Job Search may use a folder | Setup is reading your resume from Downloads, Documents or the Desktop, through the page Job Search started. Click Allow. If you did not, System Settings, Privacy & Security, Files and Folders turns it on for Job Search. |
| Job Search cannot find its folder | The copy was moved or renamed: run `sh install.sh` in its folder. |
| Job Search says the page did not start | Its dialog shows the last of what the page printed, and the page's log has all of it. |
| The browser cannot reach 127.0.0.1 | The page stopped, as it does ten minutes after its last tab closes; a browser can also pause a tab it has hidden that long. Double-click Job Search again. |
| Job Search on the phone opens to an error | Wake the Mac and check that Tailscale is on, on the phone, then swipe Job Search away in the phone's app switcher and open it again. [On your phone](#on-your-phone) has the rest. |

Keep the copy out of a Documents or Desktop folder that iCloud Drive syncs: iCloud can move
its Python packages and git files to the cloud to save space, which breaks them.
`~/job-search` is not synced.

## The details

Nothing below is needed to get going. It is the reference for how each piece works,
what it costs, and how to run it from a terminal instead of the page. For how the pieces
fit together and why, read [`ARCHITECTURE.md`](ARCHITECTURE.md); for the working
agreements every skill follows, `CLAUDE.md`; for what a filled-in profile looks like,
[`examples/`](examples/README.md).

### What the Mac installer does

In order:

1. Apple's Command Line Tools, which bring git. A window from Apple asks you to click
   Install. They take 5 to 20 minutes to download, and the steps that do not need them go
   on meanwhile.
2. [uv](https://docs.astral.sh/uv/), which runs the Python this workflow is pinned to and
   installs its packages, without touching any other Python on the Mac.
3. Claude Code, then its sign-in, in your browser. The installer asks which kind of
   account you have. Signed in to the Claude desktop app already? Claude Code still signs
   in once, on its own.
4. Your copy of this template, in `~/job-search`, and its Python packages.
5. LaTeX, which typesets resumes and letters: [TinyTeX](https://yihui.org/tinytex/), about
   64 MB, in `~/Library/TinyTeX`.
6. Job Search, on your Desktop.
7. If you want it, Job Search on your phone too ([On your phone](#on-your-phone)).

It runs on Apple silicon or Intel. Run the same line again whenever you like: what is
done is skipped, and Job Search is made again, which is how to bring it back. In a copy
you moved, run `sh install.sh` in its folder instead, which points Job Search at it.

### Setup without the page

Everything the page does also runs from Claude Code in a terminal.

**Python.** `uv run` sets up Python and every package the first time, so there is
nothing to install but uv: run every script as `uv run python scripts/<name>.py`. The one
optional extra is `scraped`, for the scraped job boards (below), which setup installs if
you turn a board on. A plain `uv sync` uninstalls an extra it is not given, so name it
there: `uv sync --extra scraped`.

Without uv, any Python 3.10 or newer works: `python -m pip install pyyaml requests pypdf`,
plus `fastapi uvicorn claude-agent-sdk` for the page.

**Setup from the terminal.** Open this folder in Claude Code and run **`/setup`**. It does
what the page's **Set up** button does, as a conversation in the terminal.

**Check.** `uv run python scripts/doctor.py` prints each check as `ok`, `MISSING` with
the fix for your system, `DRAFT` for a file `/setup` wrote that you have not finished
reviewing, or `optional` for something only some features need. It reads files and runs
local tools only, and changes nothing. The page's Setup tab shows the same checks.

#### LaTeX

LaTeX typesets resumes and letters. Install a distribution that provides `pdflatex`:

| System | Install |
|---|---|
| macOS | **Install LaTeX** on the page's Setup tab, or `uv run python scripts/install_latex.py`. It installs [TinyTeX](https://yihui.org/tinytex/) into `~/Library/TinyTeX` with the packages the templates use, asking for no password, and builds a test page to prove the fonts work. A MacTeX or BasicTeX that already has those packages is used as it is, and one that lacks them is left alone. To add them to it instead, which needs an administrator's password: `sudo tlmgr update --self && sudo tlmgr install carlisle enumitem etoolbox fontaxes geometry hyperref iftex kastrup newtx tex-gyre titlesec xcolor xkeyval xpatch xstring`. `doctor.py` prints the same command. |
| Windows | [MiKTeX](https://miktex.org/download). When its installer asks, let it install missing packages on the fly (MiKTeX Console's Settings change it later): the first resume build then fetches them without stopping to ask. |
| Linux | `sudo apt install texlive-latex-recommended texlive-latex-extra texlive-fonts-extra`, or your distribution's equivalent |

The builders and `doctor.py` find LaTeX wherever it is (on `PATH`, in TinyTeX, in
`/Library/TeX/texbin` or MiKTeX's own folder) and prefer a TeX that has every package the
templates use (`scripts/latex.py`). So a page or terminal started before LaTeX was
installed finds it, and nothing needs restarting.

#### Your profile

Setup writes these six files, each described in [`examples/README.md`](examples/README.md).
You can write them by hand instead, starting from an example.

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
resume: see `.claude/skills/tailor-resume/SKILL.md`.

`content/story.md` is yours to write: why your field, what you want next, career moves
in your words, the stories behind your bullets. A letter can only say what that file,
`master.md`, the posting, or you in chat said first, and `scripts/build_letter.py`
refuses any number in a letter that none of its cited sources contains.

### About the page

Start it with Job Search on your Desktop, which the Mac installer makes, or on your phone
([On your phone](#on-your-phone)), or with
`start.command` (`start.cmd` on Windows) or `uv run ui/server.py`; starting it again while
it is up opens the running page. Job Search runs it in the background through
`ui/launch.sh`, on the first free port from 8765 (always 8765 once phone access is on,
since launchd starts it there), and it stops by itself ten minutes after its last tab
closes. When an update changes the page's own code, a page Job Search started
has a **Restart now** button; one started in a terminal is stopped there with Ctrl+C and
started again. If the page stops while a tab is open, the tab says so, and picks up by
itself once the page is running again. Besides running the skills, it lets you
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

It answers only requests addressed to `127.0.0.1` or `localhost` or, with phone access on,
requests Tailscale forwards from your own account at your Mac's tailnet address; and none
from a page on another site, so a website open in the same browser can neither read it nor
start a skill or answer a card.

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
question asked in plain words gets a reply box. What a run files under `Applications/`,
a resume, a letter or a prep sheet, is listed at the end of its turn, to open in place.

One skill works at a time. Once a skill's turn is over it waits for your reply, holding
nothing: the Digests and Applications tabs show what it wrote, starting another skill
ends it, and **Past runs** picks its conversation up again whenever you like. If a run
stops because your plan's usage limit is reached, it says which limit and when it resets.

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
requests or two queries in a row fail. LinkedIn is the touchiest: it fetches each
posting's page and is capped at 40 queries a run. There is no proxy support, on purpose.
Google Jobs is not offered: JobSpy lists it as currently unavailable.

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

### How phone access works

Phone access is set up on a Mac for now. The copy has to be in a folder of its own, such
as `~/job-search`, where the installer puts it: macOS does not let anything started in
the background open Documents, Desktop, Downloads, or iCloud Drive, so phone access
refuses a copy there and says how to move it. A copy kept somewhere else: `cd` to that
folder before `sh install.sh --phone`.

The `login.tailscale.com` link that turns HTTPS on for your tailnet can only be used by
the tailnet's owner or an admin of it, so on a tailnet someone else runs, such as an
employer's, ask them. On the Mac, Tailscale comes from the Mac App Store, or from
[tailscale.com/download](https://tailscale.com/download) if you are an administrator of
the Mac, since that installer asks for one; its command-line tool is not needed.

The Setup tab, and the installer each time it runs, check that phone access still works,
and say why when it does not: Tailscale off on the Mac, the Mac renamed, a setup that did
not finish, or Job Search switched off in System Settings, General, Login Items &
Extensions. Each comes with what to do, usually the `--phone` command.

Why it is safe to leave on:

- **The page starts when it is asked for.** macOS's launchd holds the page's port and
  starts the page at the first request, from the phone or from Job Search on the
  Desktop. It still stops ten minutes after its last tab closes, and nothing runs between
  uses.
- **Only your own devices reach it.** Tailscale gives your Mac an address that only
  devices signed in to your Tailscale account can open, over HTTPS, and passes each
  request to the page, which still listens on the Mac alone. Tailscale says which
  account is asking, and the page answers only the one set up on this Mac
  (`data/ui-remote.json`, which never leaves it).
- **Once the page is open on the phone**, it says when it cannot reach the Mac, and picks
  up by itself when it can.
- **On a Mac shared by several accounts**, phone access lets the others open your page
  too, at `127.0.0.1:8765`, whenever they like, since it starts when asked for. Turn it
  off if that matters.

To turn it off, which puts the page back to answering the Mac alone (the Setup tab shows
this with your copy's folder in it):

```bash
cd ~/job-search && uv run python ui/phone.py disable
```

It will not while a run is working in the page, since turning it off stops the page.

### Backing up, and a second machine

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

Nothing commits or pushes on its own. There is no daemon and no scheduled commit: the
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

### Updating from the template

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
    .gitignore CLAUDE.md README.md ARCHITECTURE.md LICENSE start.command start.cmd install.sh
```

That is every file the template ships, the list `scripts/export_template.py` exports. It
overwrites any change of yours to those files, and keeps a file the template has dropped,
which the page's **Update** does neither of. Read the diff, run the tests, and commit.

### Tests

```bash
uv run --group test pytest
```

They use the example profiles and temporary files only, never your own profile or the
network. The two that build a resume PDF are skipped where `pdflatex` is missing.

## License

MIT. See [`LICENSE`](LICENSE).

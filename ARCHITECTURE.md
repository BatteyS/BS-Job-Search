# How it works

The workflow splits every job between two kinds of worker. **Claude does the
judgment**: scoring a posting against your profile, choosing which of your bullets a
resume needs, writing a letter. **Scripts do everything that can be checked**: fetching,
filtering, fitting a page, confirming that a letter's every claim has a source. A script
never decides what is good for you, and Claude never skips a check a script can make.

## The parts

| Part | Where | What it is |
|---|---|---|
| Skills | `.claude/skills/` | The workflows Claude follows: `setup`, `job-scan`, `tailor-resume`, `tailor-digest`, `cover-letter`, `interview-prep`. |
| Scripts | `scripts/` | Python with no LLM inside. Each one starts with a docstring saying what it does and why. |
| Presets | `presets/` | Knowledge every profile shares: title exclusions by career stage and job type, US metros, and place names. |
| Your profile | `profile/` | How to judge a role for you (`profile.md`), what to look for (`clusters.yaml`), where and how much (`filters.yaml`), your verdicts (`feedback.md`), and where each application stands (`applications.yaml`). |
| Your facts | `content/` | Every resume fact (`master.md`), the stories behind them (`story.md`), and contact details (`contact.local.md`, never committed). |
| Sources | `sources/` | API keys (never committed) and the employers whose boards you read (`companies.yaml`). |
| Examples and tests | `examples/`, `tests/` | Two complete fictional profiles, and the tests that run against them. |

`profile/profile.md`, `content/master.md`, and `content/story.md` are **ground truth**:
you write them, and the skills only select from them. `/setup` writes the first version
of each from your own answers, as a draft you approve. `CLAUDE.md` holds the rules every
skill follows.

## A scan

**Stage 1, `scripts/fetch_jobs.py`, is mechanical.** It reads from the sources
`filters.yaml` turns on:

- **Company boards** listed in `sources/companies.yaml`, read through adapters in
  `ats_adapters.py` for Greenhouse, Lever, Ashby, Workday, and SuccessFactors.
- **Adzuna** and **USAJOBS**, free APIs.
- **Indeed, LinkedIn, Glassdoor, and ZipRecruiter**, scraped through JobSpy, each off
  until you turn it on.

`scan_config.py` plans the aggregator queries: each cluster's `search_terms` in each
metro's `search_as`, 40 miles around, plus a nationwide remote search where the profile
asks for one. The sources are fetched side by side, and each reports how long it took.
Every posting that comes back then has to clear each filter in turn:

1. **Title.** A cluster's `include` patterns must match, and nothing in its `exclude`,
   the global excludes, or the presets may. A posting from an aggregator or a scraped
   board must also pass the cluster's `aggregator_gate`, where it has one, because no
   one chose that employer.
2. **Location.** Each place a posting lists is judged on its own. Non-US places go; a
   city counts only if nothing contradicts it: a name that needs a state must have one
   its metro covers, a state written after a city must fit its metro, and a city inside
   a longer known name ("Mesa" in "Costa Mesa") does not count. Remote roles follow
   `remote.mode`.
3. **Age, pay, and employer.** Postings older than `max_age_days`, ones whose
   *disclosed* maximum pay is below the floor, and blocklisted employers and staffing
   agencies are dropped. Undisclosed pay passes.
4. **Experience.** A posting whose lowest stated minimum is at or above
   `hard_max_years` is dropped.
5. **Duplicates.** The same requisition from several sources is kept once.

Survivors get their full descriptions. If more remain than `max_candidates`, the cut is
spread across metros and ordered by how well each can be scored, never by guessed fit.
A posting that reads as a recruiter's, for an employer it does not name, is kept and
flagged `recruiter`. The result is `data/candidates-YYYY-MM-DD.json`, and
`data/seen.sqlite` remembers what was seen so the next scan shows only what is new. It
also tracks each company board, so one that fails, or reads empty, three runs in a row
is named in the digest's warnings: an empty board has usually moved.

**Stage 2 is the `job-scan` skill.** Claude reads every candidate against the rubric in
`profile.md`, the corrections in `feedback.md`, what came of past applications, and each
cluster's notes, subtracts the location penalty, and writes the digest. Your `apply` and
`skip — reason` marks go back into `feedback.md`, which is how scoring learns what you
want. A third box, `cover letter`, asks for a letter beside an apply's resume. The
outcomes teach it what employers answer: roles like those that went forward score up, and
a trait shared by several that were screened out scores down, while one outcome alone
moves nothing.

## A resume

`master.md` holds more than any resume will. `/tailor-resume` reads the whole posting and
the whole file, then writes a manifest naming the entries and bullets this posting needs.
It may reword a bullet into the posting's vocabulary, but never adds a claim.
`build_resume.py` renders the manifest through `Resume/LaTeX/template.tex` and compiles
it. To fit the page limit, it tightens spacing before it cuts anything. It never drops a
role whose absence would leave a gap in the dates, and it reports every cut. The PDF and
its `.tex` are filed under `Applications/<Company>/`. `ats_check.py` reports which of a
posting's keywords a resume is missing, and whether `master.md` already has the evidence.

## A cover letter

`/cover-letter` writes the letter as paragraphs, each listing what backs it: a
`master.md` bullet, a `story.md` passage, a quote from the posting, or something you
said. `build_letter.py --check` refuses the letter until three things hold:

- every source resolves to exactly one passage;
- every number in a paragraph appears in that paragraph's sources, in digits or words;
- every posting quote really is in the posting.

It also flags stock phrases. A letter longer than a page is refused rather than trimmed,
because cutting changes what it says.

Before writing, `/cover-letter` looks for the story behind each piece of evidence it
means to use. When `story.md` lacks one, it asks you, a few questions at a time. Your
answers go into `story.md`, and any new resume fact into `master.md`, once you approve the
exact text, so the letter cites a file and the next letter finds the story there.
`/tailor-digest` asks these questions for every role ticked `cover letter` before it
builds any resume, so a fact you add reaches every resume in the batch.

## What came of it

An application is one role at one employer, named the way its files are under
`Applications/<Company>/`. Where each stands is kept in `profile/applications.yaml`
(`scripts/tracker.py`): applied, heard back, interviewing, offer, accepted, rejected,
withdrawn, or no response, one dated line per change, so the file holds every date and
its last line is the current status. A status moves only forward or to an ending; undoing
the last change fixes a mistake without losing the dates before it. The file is tracked,
unlike `Applications/`, so the record reaches every machine, and it is never exported
with the template.

Only the page writes it, since only you know what was sent and what came back. Each write
rewrites the file in one layout, so a change is one line in the diff. It refuses a note
that holds an email address or a phone number, and writes nothing while the file does
not load. `digest_applies.py --outcomes` joins each application to the digest entry it
came from and sorts it: went forward (a person answered with interest), screened out
(rejected before that, no response, or 30 days with no word), waiting, or withdrawn. That
is what a scan reads.

## An interview prep sheet

`/interview-prep` works from one application's folder: the posting saved there, the
resume and any letter filed beside it, and `master.md` and `story.md`. It writes three
lists. The questions the posting makes likely, each answered as situation, action, and
result, or, for a question about motivation, as one answer. The gaps the posting exposes:
`ats_check.py` names the words the posting leans on that `master.md` never uses, Claude
sorts real gaps from noise and from work done under another name, and each gap gets an
honest way to answer it. And questions to ask the employer, from the posting and from what
`story.md` says you want next.

Every item lists what it was drawn from, and every answer what backs it, in the letter's
four kinds of source. `build_prep.py --check` runs the letter's own checks on each
passage, from the same code in `build_letter.py`, and adds the sheet's: every question and
gap says where it came from, a gap quotes the posting where it asks for that thing, and an
answer cites something you did or said, since a posting quote cannot. A question your
files cannot answer stays on the sheet unanswered, as one to prepare. When `story.md`
lacks the story an answer needs, it runs the cover letter's interview first, under the
same rules. The sheet is Markdown, `Applications/<Company>/<Job Title> - interview
prep.md`, with each answer's sources quoted in full beneath it.

## Setup and upkeep

| Tool | Does |
|---|---|
| `install.sh` | Sets up a Mac in one step: Apple's Command Line Tools (for git), uv, Claude Code and its sign-in, a clone of the template in `~/job-search` and its packages, LaTeX, and Job Search on the Desktop. Only what is missing, with no password, and safe to run again. |
| `/setup` | Interviews a new user and writes their profile, starting with the resume facts. |
| `doctor.py` | Checks the machine, the profile, and the keys, and says what to fix. |
| `install_latex.py` | Installs LaTeX without a password: TinyTeX in the user's own folder, with the packages the templates load, unless a TeX that has them is already there. `latex.py` finds that TeX wherever it is, for the builders and `doctor.py`. |
| `extract_text.py` | Pulls the text out of a .docx, PDF, or text resume. |
| `try_titles.py` | Checks job titles against the clusters, offline. |
| `digest_applies.py` | Reads a marked digest: the roles to apply to and letters to write, the verdicts as a `feedback.md` section (`--verdicts`), and every apply's posting (`--fetch`). `--outcomes` lists what came of each application, beside its digest entry. |
| `fetch_posting.py` | Saves one posting's full text, or reports it dead or too thin to tailor from. |
| `detect_ats.py` | Finds an employer's job board from its domain. |
| `probe_workday.py` | Finds a Workday board that a careers page hides behind JavaScript. |
| `resolve_ats.py` | Rebuilds `sources/companies.yaml` from a list of employer names, skipping the tokens in `known_bad.txt`. |
| `export_template.py` | Copies the shareable files to a new folder, refusing if any carries personal data. |

## The page

`ui/server.py` serves a page on this machine only (`uv run ui/server.py`, or the
`start.command` and `start.cmd` files that run it in a terminal, or Job Search on a Mac's
Desktop) for setup and the work between skills.
Its Setup tab shows `doctor.py`'s checks, how far `/setup` has got, and a form that saves
the API keys to their gitignored files; the page opens on it until the profile is written
and reviewed. The rest is reading a digest and ticking its boxes, which it writes back
into the `.md` in place; finding what was filed under `Applications/` and recording where
each application stands; running `doctor.py` and `digest_applies.py` with the output
streamed; and reading the profile files. It also runs the skills: `ui/claude_run.py` starts one
through the Agent SDK driving the user's own Claude Code in this folder, so the skill,
`CLAUDE.md` and `.claude/settings.json` are the same ones a terminal would load. Every
prompt Claude Code would show a person, including the `ask` rule on `master.md`,
`story.md` and `profile.md`, reaches one callback, becomes a card in the page, and waits.
The rule that those files are written only after the user sees the exact text is therefore
enforced by permissions, not by the prompt. `ui/core.py` holds the rest and has no web
framework in it; neither needs the SDK installed, so the tests cover both without it.

The Setup tab also keeps the copy current and backed up, so nobody has to run git.
`core.copy_status()` tells the copy's layout from its remotes and history: a clone of the
template; a copy pushed to a private repository of its own, with the template as a second
remote; or one made with GitHub's Use this template, which shares no history with it. The
page fetches the template quietly when it opens, and hourly while it stays open, and shows
how many updates there are, with each export's notes. Update brings them in, as a
fast-forward or a merge and never a rebase, then pushes to the user's own repository. A
copy with no shared history takes the template's files one by one, as a merge would, and
that first update joins the two histories. Back up commits the user's own files (profile,
content, digests, sources) with their message, brings in what another machine backed up,
and pushes, never to a repository anyone can read. Each of them stops, changing nothing,
rather than write over uncommitted work or settle a conflict itself, and the page says
when an update needs it restarted. git runs with no terminal to prompt in, so a missing
sign-in is an error to report, not a prompt hidden in the page's own window.

`ui/router.py` picks each run's model and effort from the skill, what the run is given
(how much is marked in a digest), and how full the plan's usage windows are, and says
why. Its rules are plain code, so routing uses none of the plan, and a run keeps its
route for every reply, since Claude Code caches a conversation per model and effort.
`ui/usage.py` keeps those windows, which Claude Code reports with every request a run
makes, and between runs reads its `/usage`, which answers without calling a model.

Nothing guards the page but where it listens, so one check runs before every route
(`core.refusal`): a request must be addressed to `127.0.0.1` or `localhost`, which stops a
site that points its own name at this machine (DNS rebinding), and one that carries an
Origin must carry the page's own, which stops another site's form or script from starting
a run or answering a card.

On a Mac, `install.sh` puts Job Search on the Desktop: an AppleScript applet, built on the
machine by `osacompile` and so never quarantined, whose only content is the path of the
copy, in `Contents/Resources/open.sh`. It runs `ui/launch.sh` there, which keeps everything
that may change in the copy, where updates reach it. The launcher builds the PATH a Finder
launch lacks, opens the page if this copy's is already up, and otherwise starts it in the
background on the first free port from 8765, with `--idle-exit 10`: the page asks
`/api/health` once a minute while any tab has it open, so the server stops ten minutes
after the last tab closes, though never while a run is working (starting, running, or
waiting on a card). A skill whose turn is over waits for a reply but holds nothing: it
does not keep the page up or stop a restart, the next skill started ends it, and Past
runs resumes its conversation from Claude Code's own record. A page the launcher started knows
it (`BS_LAUNCHER`), so after an update to its own code it can restart itself: it starts
`launch.sh --restart` on its own, stops, and the launcher starts it again through
`uv run`, which installs what the update added. The tab reloads itself once `/api/health`
reports a new start time. A tab whose server does not answer says so, and picks up again
once it does: it reloads only when the answer comes from a new server, so a blip, such as
a phone waking the page, loses nothing typed. A run's live output reconnects in place on
its own, from the last line or event it had.

Phone access (`ui/phone.py`, `sh install.sh --phone`) adds two things on the Mac, and
leaves the page listening there alone. A LaunchAgent holds `127.0.0.1:8765` with launchd's
`Sockets` and runs `launch.sh --launchd` at the first connection, which syncs the packages
and then `exec`s the page in the same process, since launchd hands its socket
(`launch_activate_socket`) only to the process it started; the page serves on it, stops
when idle as before, and the next connection starts it again, so a restart there is only
stopping. Job Search on the Desktop sees the agent and lets that same request start the
page; when the agent does not answer as this copy, it starts the page on the next free
port as before, for the Mac alone, and says phone access needs setting up again. The Setup
tab and the installer share one diagnosis of a setup that has stopped working
(`phone.diagnose`). And `tailscale serve` gives the Mac an HTTPS address on the user's
tailnet that forwards to the page, naming the account asking in `Tailscale-User-Login`,
which serve sets and strips from what it forwards. `core.refusal` answers a forwarded
request only once `data/ui-remote.json` records phone access, only for that account, and
only at the Mac's tailnet name, whose own pages are the one other origin it allows. The
page carries a web app manifest and an icon drawn in code (`ui/icon.py`), so a phone adds
it to its home screen as an app; Job Search on the Desktop has the same icon, as a Mac
tile. On a phone the page lays itself out as one (`ui/style.css`, the narrow breakpoint):
the tabs sit in a bar along the bottom, each tab's sidebar folds into a bar that names
what is open and unfolds to the list on a tap (`setSide` in `app.js`), the status line is
a toast, a run's reply box stays at the bottom while the run waits, and everything tapped
is at least 40px tall. Wider than a phone, nothing changes.

`ui/build_demo.py` builds the same page as static files for each example profile, from
its `examples/<name>/demo/` folder: it lays the example out like a copy of this repo,
builds its resumes, letters and prep sheets, and saves what each route would answer there into
`demo.js`, which the page reads instead of a server. The demos are published on the
public repo's GitHub Pages.

The tests run on every push (`.github/workflows/tests.yml`), along with the
personal-data check.

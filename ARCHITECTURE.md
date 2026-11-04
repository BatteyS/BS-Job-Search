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
| `/setup` | Interviews a new user and writes their profile, starting with the resume facts. |
| `doctor.py` | Checks the machine, the profile, and the keys, and says what to fix. |
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
`start.command` and `start.cmd` files that run it) for setup and the work between skills.
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

`ui/build_demo.py` builds the same page as static files for each example profile, from
its `examples/<name>/demo/` folder: it lays the example out like a copy of this repo,
builds its resumes, letters and prep sheets, and saves what each route would answer there into
`demo.js`, which the page reads instead of a server. The demos are published on the
public repo's GitHub Pages.

The tests run on every push (`.github/workflows/tests.yml`), along with the
personal-data check.

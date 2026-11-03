# How it works

The workflow splits every job between two kinds of worker. **Claude does the
judgment**: scoring a posting against your profile, choosing which of your bullets a
resume needs, writing a letter. **Scripts do everything that can be checked**: fetching,
filtering, fitting a page, confirming that a letter's every claim has a source. A script
never decides what is good for you, and Claude never skips a check a script can make.

## The parts

| Part | Where | What it is |
|---|---|---|
| Skills | `.claude/skills/` | The workflows Claude follows: `setup`, `job-scan`, `tailor-resume`, `tailor-digest`, `cover-letter`. |
| Scripts | `scripts/` | Python with no LLM inside. Each one starts with a docstring saying what it does and why. |
| Presets | `presets/` | Knowledge every profile shares: title exclusions by career stage and job type, US metros, and place names. |
| Your profile | `profile/` | How to judge a role for you (`profile.md`), what to look for (`clusters.yaml`), where and how much (`filters.yaml`), and your verdicts (`feedback.md`). |
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
`profile.md`, the corrections in `feedback.md`, and each cluster's notes, subtracts the
location penalty, and writes the digest. Your `apply` and `skip — reason` marks go back
into `feedback.md`, which is how scoring improves. A third box, `cover letter`, asks for a
letter beside an apply's resume.

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

## Setup and upkeep

| Tool | Does |
|---|---|
| `/setup` | Interviews a new user and writes their profile, starting with the resume facts. |
| `doctor.py` | Checks the machine, the profile, and the keys, and says what to fix. |
| `extract_text.py` | Pulls the text out of a .docx, PDF, or text resume. |
| `try_titles.py` | Checks job titles against the clusters, offline. |
| `digest_applies.py` | Reads a marked digest: the roles to apply to and letters to write, the verdicts as a `feedback.md` section (`--verdicts`), and every apply's posting (`--fetch`). |
| `fetch_posting.py` | Saves one posting's full text, or reports it dead or too thin to tailor from. |
| `detect_ats.py` | Finds an employer's job board from its domain. |
| `probe_workday.py` | Finds a Workday board that a careers page hides behind JavaScript. |
| `resolve_ats.py` | Rebuilds `sources/companies.yaml` from a list of employer names, skipping the tokens in `known_bad.txt`. |
| `export_template.py` | Copies the shareable files to a new folder, refusing if any carries personal data. |

The tests run on every push (`.github/workflows/tests.yml`), along with the
personal-data check.

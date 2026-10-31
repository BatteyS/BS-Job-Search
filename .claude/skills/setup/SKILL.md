---
name: setup
description: Set up this workflow for a new user. Checks the machine, then interviews them and writes content/contact.local.md, content/master.md (with a deep interview for resume detail), content/story.md, profile/profile.md, profile/clusters.yaml, and profile/filters.yaml; adds API keys, target employers, and any scraped boards they choose; and tunes the clusters on real postings. Use when the user says "set up", "get started", "set me up", or invokes /setup, or when doctor.py reports profile files missing. Also resumes a setup left unfinished.
---

# Setup

The interview that turns a fresh copy of this workflow into one person's job search. It
writes six files, in this order, each building on the ones before:

| Step | Writes |
|---|---|
| 2 Contact | `content/contact.local.md` |
| 3 Resume | `content/master.md` |
| 4 Story | `content/story.md` |
| 5 Profile | `profile/profile.md` |
| 6 Clusters | `profile/clusters.yaml` |
| 7 Filters | `profile/filters.yaml` |

After that come API keys, scraped boards, target employers, a preview that tunes the
clusters on real postings, and `profile/feedback.md`.

Tell the user up front that doing it properly takes an hour or more, most of it on their
resume, and that they can stop after any step: running /setup again picks up where they
left off. The two profiles in `examples/` show what finished files look like.

## Ground rules

- **Never overwrite a file that exists.** Step 1 finds which exist. For each one, ask
  whether to keep it, add to it, or start over, and do only what the user says.
- **Every fact comes from the user**: their resume, or what they say in this conversation.
  Never invent, round up, or infer a claim, a number, a date, or a feeling. That is
  CLAUDE.md's ground-truth rule, and it holds here more than anywhere. A gap you notice
  is a question to ask, not something to fill in.
- **The user approves master.md, story.md, and profile.md.** They are ground truth
  (CLAUDE.md). Write each as a draft with this line right after any front matter:
  `<!-- /setup draft: not yet reviewed -->`. Have the user read all of it, correct it with
  them, and remove the line only when they approve. A later /setup run that finds the
  line resumes that review. Once setup is done, no skill edits these files on its own.
- **Never ask for an API key or password in chat.** Keys go into gitignored files the
  user edits themselves (Step 8).
- **Scraped boards are the user's decision, one board at a time** (Step 9).
- **A few questions at a time.** Three to six per turn, one role or topic at a time,
  not a questionnaire.

## Step 1 — check the machine, and what exists

```bash
python scripts/doctor.py
```

It checks Python, LaTeX, every profile file, the API keys and the sources, and prints the
fix for anything missing on this operating system. Fix Python first if it is broken,
since every later step runs a script. The README's setup section covers it: `uv sync`.
LaTeX is needed only to build resumes and letters, so if it is missing, give the user the
install step doctor prints and carry on while it installs.

Then tell the user which of the six files already exist, and agree which steps to do. A
file doctor reports as a `/setup` draft comes first: finish its review before starting
anything new. A copy that has all six needs only the steps the user wants to redo. That
is often just Step 4, since `story.md` is the file people skip.

## Step 2 — contact details

Ask for their name as it should read on a resume, email, phone (optional), location as
"City, ST", and any of LinkedIn, GitHub, website, and portfolio. Write
`content/contact.local.md` in the format of `content/contact.example.md`, leaving
optional fields blank rather than guessing. It is the only file that holds contact
details, and it is gitignored, so it never reaches the repository.

## Step 3 — the resume database, content/master.md

`master.md` holds every resume fact the user has, more than any one resume will. Each
tailored resume is selected from it, and nothing on a resume can come from anywhere
else, so whatever is missing here is missing from every application. **This step decides
how good everything after it is.** Say so, and take the time.

### 3a — gather what they have

Ask for their current resume as a .docx, PDF, or text file, by path. Ask too for anything
else that holds career detail: an older or longer resume, their LinkedIn profile saved as
a PDF (on their profile page: More, then Save to PDF), a self-review, a portfolio page.
Pull out the text:

```bash
python scripts/extract_text.py "<path>"
```

Also read the original (the Read tool opens PDFs and images), because layout does not
survive extraction and columns or tables can come out jumbled. A PDF needs the `pdf`
extra, and doctor prints its install command. No resume at all is fine: build it from
the interview.

### 3b — transcribe

Draft the file in the format of `examples/*/master.md`:

```
---
section_order: Experience, Education, Skills     <- only when not the default
max_pages: 2                                      <- only if they want two pages
---

# Experience

## Employer | Title | Mon YYYY – Mon YYYY       <- or "– Present"

- [S]  one line for the whole role
- [P1] a detail bullet
```

- One `## Employer | Title | Dates` entry per title held. A promotion is two entries, so
  it shows.
- Dates as month and year. A missing month is a question for the user, not a guess.
- Education entries take a `location:` line under the heading. Skills are bare bullets
  with a bold label: `- [P1] **Tools:** ...`.
- Any other `# Section` works: Licenses & Certifications, Projects, Publications, Awards,
  Volunteer, Speaking.
- Plain text throughout. Write "R&D", "40%", and "$1.2M" as they are; the builder escapes
  them.
- One page unless they ask for two. Resumes aim at a 30-second scan.

### 3c — interview for detail, one role at a time

Resumes undersell. Take each role, most recent first, and draw out what the page left
out, a few questions per round:

- **Scope.** What did the team or company do? What were they responsible for: people,
  budget, customers, products, sites, systems? How big, in headcount, dollars, volume, or
  users?
- **Each bullet they already have.** What did *they* do, what changed because of it, how
  do they know, and over what time? Turn "improved efficiency" into the before and after.
- **What is missing.** What they are proudest of from that job. Something they built or
  started. A problem they fixed that others had not. Recognition: a promotion, an award,
  praise from leadership. People they trained or mentored. Work with other teams. Tools
  they used or brought in.
- **What else.** Ask every role: "What did you do in this job that isn't on your resume?"
  It finds more than any other question.

After the roles, cover the rest of a career: degrees (honors, a thesis or capstone, and
relevant coursework early in a career), licenses and certifications (issuer, and whether
active), projects, publications, talks, patents, awards, volunteer work, leadership,
languages, freelance or side work, military service. Then ask once more what is not
written down anywhere yet.

Keep every claim exactly as the user gives it:

- **Numbers only as stated.** An estimate stays an estimate: "about 40%", never "40%".
  If they are unsure, leave it out, or mark it for them to check.
- **The same verb of ownership.** Helped is not led, and supported is not managed.
- **Their scope, not a bigger one.** A team's result is the team's.

### 3d — priorities

Give each role one `[S]` line: one sentence condensing the role from its own bullets,
for resumes where the role must appear but has little to say. Mark detail bullets `[P1]`
(strongest), `[P2]`, or `[P3]`. Priority is the user's own view of which bullets are
strongest, so ask: "Which two or three from this role would you most want a recruiter to
see?" Propose an order, then let them rearrange it.

### 3e — review, check, and show

Write the draft and have the user read all of it, then correct it with them until they
approve it. Then check that it parses and that its dates hold together, and build a
resume from every bullet, fitted to the page limit:

```bash
python scripts/doctor.py
python scripts/build_resume.py --all --out editing_cv
```

Show them `Resume/pdf/editing_cv.pdf`. It is the first thing setup produces that looks
like progress. Real resumes are tailored to each posting by /tailor-resume, so the page
limit trimming this one is not losing anything. If doctor reports a date problem, fix it
with the user.

## Step 4 — the story, content/story.md

A cover letter needs what a resume cannot hold: why this field, what they want next, and
the stories behind their best bullets. Follow the headings of
`content/story.example.md`, asking about each in turn:

- **Why this field**: the moment, project, or problem that drew them in.
- **What I'm looking for next**: what they want to own or learn, and why now.
- **Career moves, in my words**: each move, what they went looking for and what they
  found.
- **Stories worth telling**: two or three, each expanding a strong master.md bullet with
  the situation, what they did, and what changed.
- **How I write**: optional, a short paragraph they wrote themselves, so letters can sound
  like them.
- **Keep out of letters**: anything a letter must never mention, such as why they left a
  job, or pay.

Write it in their words. Tidy the grammar but keep their phrasing, and make each
paragraph a whole thought that stands alone, since each is a passage a letter will cite.
Numbers must match master.md or be ones they gave you. Review it with them as in Step 3.
A user who will not write cover letters can skip this step.

## Step 5 — the profile, profile/profile.md

What /job-scan scores every posting against. It is written for the scorer, not an
employer, so it can be candid, and it is never sent to anyone. Follow the structure of
`examples/*/profile.md`:

1. **Identity and hard constraints**: current role and years; where they live, how far
   they will commute, and whether and where they would relocate; remote preference; pay
   floor (base salary, and whether hourly pay is fine); and schedule, travel, licenses,
   clearance, or anything else that rules a role out.
2. **Evidence bank**: their strongest evidence, summarized from master.md, for the
   scorer's reference.
3. **Role clusters**: filled in at Step 6.
4. **Scoring rubric**, the heart of the file:
   - *What makes a role worth applying to*, in their own words, quoted. Ask "What would
     make you say yes to a role straight away?" and "What makes a role a waste of an
     application, even when the title fits?"
   - Where they want to be in three to five years, and which roles move them toward it.
     Direction usually matters more than match.
   - *Score up* and *score down*: specific signals, drawn from their answers.
   - *Location*: how much a farther metro or a remote role is worth to them.
   - *Hard passes*: industries, company types, and kinds of role they will not take.
5. **Resume**: one page or two, and what to lead with.
6. **Calibration**: empty for now. It fills from their verdicts in `profile/feedback.md`.

Review it with them as in Step 3.

## Step 6 — role clusters, profile/clusters.yaml

A cluster is one kind of role to look for. Propose two to four from the profile's
targets and agree them with the user. Follow `examples/*/clusters.yaml`. For each
cluster, write an `id` (short, kebab-case), a `label`, a `rationale` drawn from the
profile, and:

- `search_terms`: three to six phrases a recruiter would title the job. Each one is a
  query to every aggregator in every metro, so these set what a scan costs.
- `include`: Python regexes, matched case-insensitively against the posting **title**.
  Match how employers actually title the role, variants included.
- `exclude`: near misses this cluster should drop.
- `usajobs_terms`: broad single words, and only if federal jobs suit them. USAJOBS titles
  postings by occupational series, so compound phrases find nothing.
- `min_score` or `scoring_note`, when a cluster needs its own bar or extra judgment.

Under `global`, pick **one** seniority preset from `presets/title_excludes.yaml`:
`early_career` (about 0–4 years), `mid_career` (4–10), `senior` (10+), or `leadership`
(director and above). Add the job-type presets for tracks they rule out. **Never use a
preset that excludes their own field**: a marketer cannot use `no_marketing`, nor a
recruiter `no_recruiting_hr`. When a preset goes too far, leave it out and write the
parts they do want under `global.exclude`, as the product-marketer example does.

Test the patterns offline before anything is fetched. Write fifteen or more realistic
titles: ones each cluster should keep, and near misses it should drop. Then run:

```bash
python scripts/try_titles.py "First title" "Second title" ...
```

Fix the patterns until every title lands where it should, then fill in profile.md's
cluster table.

## Step 7 — where and how much, profile/filters.yaml

Start from `examples/*/filters.yaml`.

- **Metros.** Ask where they want to work, then match each place to a metro in
  `presets/metros.yaml` and confirm. Copy each chosen metro's whole entry under `metros:`
  and set its `penalty`: 0 where they most want to be, and small negatives for the rest
  in order of preference. Keep penalties within about −8 so role fit still decides. An
  area the library lacks gets a metro built the same way: `search_as` ("City, ST", the
  point each aggregator searches 40 miles around), `states`, and the `cities` within
  commuting range.
- **Remote.** `mode` (`include`, `exclude`, or `only`), its `penalty`, and
  `search_nationwide`. That last one adds a nationwide remote query per search term: worth
  it when remote is a real option, but it raises what each scan costs.
- **Pay.** `comp.floor_usd`: a posting whose disclosed maximum is below it is dropped. For
  fields paid by the hour, set `min_plausible_hourly`.
- **Experience.** `years` of relevant experience, and `hard_max_years`: a posting whose
  stated minimum is at or above it is dropped. A few years above their own is typical.
- **Cost.** `max_candidates: 150` and `max_description_chars: 3000` keep the first scans
  small. Explain what they do; the user can raise them once digests look right.
- **Sources.**
  - `boards`: true if they will add employers in Step 10.
  - `adzuna`: true, with its free key from Step 8.
  - `usajobs`: true only if federal roles fit them, with `usajobs_agencies` naming the
    agencies in scope (an empty list keeps every agency).
  - The four scraped boards start false. Step 9 asks about each.
- **Blocklists.** `blocklist_companies` for employers they never want to see.
  `blocklist_staffing` gets the example's agency patterns, and they can add agencies that
  keep turning up.

Write it, and check it with doctor.

## Step 8 — API keys

Adzuna, a job aggregator, reaches employers whose own job boards cannot be read
directly. USAJOBS is federal hiring. Both are free, and both need a key:

| Source | Register | Key file |
|---|---|---|
| Adzuna | https://developer.adzuna.com/signup | `sources/adzuna.local.yaml` |
| USAJOBS | https://developer.usajobs.gov/APIRequest | `sources/usajobs.local.yaml` |

For each source that is on, copy its `sources/*.example.yaml` to the `.local.yaml` name,
and tell the user to open that file and paste their key in themselves. **Do not ask for
the key in chat**: anything pasted here stays in the conversation. USAJOBS also needs
the email the key was registered under. Doctor checks the keys without printing them. A
user without a key yet can turn that source off for now.

## Step 9 — scraped boards, one decision each

Indeed, LinkedIn, Glassdoor, and ZipRecruiter add breadth: on one profile, Indeed alone
reached 161 employers no other source did. But all four boards' terms prohibit scraping,
and these sources scrape them. Before asking, explain that, and what limits the risk:

- Nothing logs in, so no account of the user's is involved.
- Each board runs at a fixed, polite pace, and stops for the rest of the run if it
  starts refusing requests.
- There are no proxies.
- LinkedIn fetches each posting's page, and is capped at 40 queries a run.

The README's section on scraped boards has the full account. Then ask about each board
separately: one AskUserQuestion call with a question per board, "Leave it off" as the
first option of each. Set a board to `true` under `sources` only on a yes for that board.

If any board is on, the `scraped` extra must be installed. Doctor prints the command,
which keeps the `pdf` extra too if it is installed. Say that it installs about 180 MB,
and run it once the user agrees.

## Step 10 — target employers, sources/companies.yaml

The scan also reads employers' own job boards directly. That catches roles before an
aggregator does, and staffing agencies cannot crowd them out. Ask for the organizations
they would most like to work for, as many as they like: companies, hospitals, school
districts, agencies, nonprofits. For each, find its website domain, confirming with the
user when unsure, and detect its board:

```bash
python scripts/detect_ats.py example.com other.org="Display Name"
```

Every entry it prints has been checked against the live board. Add them under `manual:`
in `sources/companies.yaml`, creating the file if it does not exist with `version: 1`,
`companies: []`, and a `manual:` list. Report the ones it could not read, which have an
unsupported platform or a careers page that hides its platform; their roles still arrive
through the aggregators.

A careers page that hides its platform is often Workday behind JavaScript. Guess the
employer's Workday tenant name, usually its short name in lowercase, and probe for it:

```bash
python scripts/probe_workday.py <guess> <another-guess>
```

A hit is that employer's board, because Workday tenants are company-specific.

Set expectations first: the boards it can read are Greenhouse, Lever, Ashby, Workday,
and SuccessFactors, which are common at tech companies and some large employers. Many
hospitals, universities, and government employers use platforms it cannot read, such as
iCIMS, Taleo, Phenom, or Oracle. Of nine large California health systems tried on
2026-10-30, two were readable. For a user in such a field, the aggregators carry most of
the search, and this step adds what it can.

A job board specific to the user's field, such as a nursing or nonprofit job board, is
not a source the scan can read. The employers that post there have their own boards, so
add those here instead.

## Step 11 — tune the clusters on real postings

```bash
python scripts/fetch_jobs.py --all-clusters --preview
```

This runs the searches the profile now sets up and prints, for each cluster, the titles
that get through in the user's metros and the near misses an exclude dropped. Nothing is
written. Read it with the user:

- Wrong titles getting through mean an include pattern to tighten.
- Good roles under "just missed" mean an exclude that goes too far.
- An empty cluster means its patterns or search terms miss how employers title the role.

Adjust the patterns with `try_titles.py`, then preview again. Each preview reruns every
search, so two or three rounds is plenty.

## Step 12 — finish

Write `profile/feedback.md` with this starter:

```markdown
# Scoring calibration — verdicts on past digests

The scanner reads this file on every run and treats the entries as examples.

Mark the entries in `digests/YYYY-MM-DD.md` with `apply` or `skip — reason`, then ask
for this file to be updated. The reason is what carries signal: "skip" alone teaches
nothing, while "skip — wants 8+ years" teaches a lot.

---

## Standing corrections

None yet.
```

Run doctor once more and resolve whatever it reports. Then explain how the pieces fit:

1. `/job-scan` asks which clusters to target, then fetches, scores against profile.md,
   and writes `digests/YYYY-MM-DD.md`.
2. The user marks digest entries `apply` or `skip — reason`. The reasons go into
   feedback.md and recalibrate every later scan.
3. `/tailor-digest` builds a resume for every `apply`. `/tailor-resume` builds one for a
   single posting.
4. `/cover-letter` writes a letter whose every claim cites master.md, story.md, the
   posting, or something the user said.

If this copy is a git repository, offer to commit the new files. `contact.local.md` and
the key files are gitignored and stay out. If the repository is on GitHub, it should be
private, because profile.md is candid.

Then offer to run the first `/job-scan`.

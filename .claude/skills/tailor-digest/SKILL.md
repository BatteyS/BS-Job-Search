---
name: tailor-digest
description: Build a tailored resume for every role marked `apply` on a digest, and a cover letter for every role also marked `cover letter`, interviewing the user first for anything a letter needs that their files lack. Files the .tex and .pdf into Applications/<Company>/<Job Title>.*. Use when the user says "tailor the digest", "build resumes for what I marked", "run the applies", or asks for resumes for everything they marked apply.
---

# Tailor every role marked `apply`

This is `tailor-resume` run across a whole digest. The per-role discipline lives there and
is not repeated here — **read `.claude/skills/tailor-resume/SKILL.md` before starting**,
because depth, variant choice, and the rule against inventing bullets all still apply.
When any role has `cover letter` ticked, read `.claude/skills/cover-letter/SKILL.md` too.
What this skill adds is the loop, and the ways a loop goes wrong that a single build
never does.

## Step 1 — read the marks

```bash
python scripts/digest_applies.py
```

Defaults to the newest `digests/*.md`. Add `--date YYYY-MM-DD` for an older one, or
`--pending` to skip roles whose `.tex` and `.pdf` are both already filed.

Each digest entry has three boxes: `apply`, `skip — reason:`, and `cover letter`, which
asks for a letter beside that role's resume. The parser is mechanical — it reports what
the user ticked and where each file would land, letters included. Four things in its
output need a decision before any building starts:

- **`CONFLICT`** — `skip` is ticked with `apply` or `cover letter`. Ask which they meant.
  Never guess.
- **`LETTER ONLY`** — `cover letter` is ticked but `apply` is not. Ask whether they mean
  to apply; a letter goes with a resume.
- **`unmarked`** — entries with no box ticked. Usually the digest isn't fully
  triaged yet. Say how many and let them decide whether to keep going.
- **`!!` folder note** — an existing `Applications/` folder reads as the same employer
  under a different spelling. The real case: the digest writes *Black & Veatch* and the
  folder is *Black and Veatch*. The parser reuses the existing folder and flags it;
  confirm that's right rather than letting one employer split across two folders.

Show them the parsed list and get a go-ahead before building. A mis-parsed heading is much
cheaper to catch here than after seven PDFs are filed. Read the counts back, letters
included: `cover letter` is the easiest box to miss. On 2026-11-02 a user asked for three
letters with none of the boxes ticked.

## Step 2 — fetch every posting first, before tailoring any of them

Do this for the whole list up front, not lazily per role, in one command:

```bash
python scripts/digest_applies.py --fetch
```

It saves each apply's posting as `<folder>/<Job Title> - posting.txt`. When the digest's
link fails or comes back thin, it looks the role up on the employer's own board in
`sources/companies.yaml`: that is how Redwood's posting was found on 2026-11-02, when
LinkedIn refused it. Each role comes back saved, DEAD, or NEEDS A BROWSER OR A PASTE.

Two reasons it goes first. Dead postings drop out before you spend effort on them — on the
first batch run, one marked role was already a 404. And the fetch failures are the roles
that need the user, so you want them identified in one batch rather than interrupting them
seven times.

**A DEAD role means stop on that role** — report it and move on. For a role that needs a
browser or a paste, try the employer's board first if `companies.yaml` does not list it
(`tailor-resume` Step 1 says how), then a browser fetch, or ask the user to paste it.
Never fall back to the digest snippet: tailoring against eighty words produces a resume
that looks tailored and isn't.

Report the fetch results as a group before building anything: which came back full, which
are dead, which need a paste.

## Step 2a — gather what the letters need, before building anything

Skip this step when no live role has `cover letter` ticked. Otherwise, for those roles,
follow `cover-letter` Steps 2–3c now, before any resume is built:

1. **Why this company, asked once.** List every letter role and ask why they want each,
   rather than interrupting them per letter. A role they pass on gets a letter that opens
   on fit instead.
2. **The interview, one role at a time.** For each role, pick the two or three strongest
   matches between its posting and `master.md`, and look in `story.md` for the story
   behind each. Ask only for what is missing, a few questions per turn, as
   `cover-letter` Step 3b says. A story told for one role often serves the next; ask
   nothing twice.
3. **Save what they said.** Add the answers to `story.md`, and any new resume fact to
   `master.md`, with the user's approval of the exact text, as `cover-letter` Step 3c
   says.

It comes first for a reason: a fact added to `master.md` now reaches every resume in the
batch. Added after some are built, it would split the batch across two versions of the
truth (hazard two, below).

## Step 2b — one manifest per role, from that role's posting

Follow `tailor-resume` Steps 2 and 3 for each role: read `master.md` in full, then write a
manifest naming what goes on that page. **Do not reuse one manifest across roles.** Two
postings that look similar from the digest ask for different evidence — one commissioning
role wants loop checks and system turnover, another wants site assessments and M&V plans —
and the same role on the resume should lead with different bullets for each.

The digest's `**Resume:**` line suggests a *variant*, which is worth reading but not
binding — you choose the variant explicitly in the manifest, having read the posting the
digest only summarized.

**Every manifest needs a `fill` list**, per `tailor-resume`. In a batch this is the step
most likely to be skipped, and skipping it is invisible: the build succeeds, the page
count holds, and it goes out with an inch of white space at the bottom. That is exactly how
five of these shipped short. A manifest without `fill` is not finished.

## Step 3 — reword per posting, and mind the two batch hazards

Follow `tailor-resume` Step 3 for each role: having selected the bullets, reword them into
that posting's vocabulary via `text` in the manifest. Rewrites are transient, so each role
gets its own manifest and nothing leaks between them.

**Hazard one: volume erodes the line against fabrication.** Seven roles in one sitting is
exactly when a plausible-sounding bullet slips through, because by role five you are
pattern-matching rather than checking. Verify every rewrite against the original bullet —
same scope, same numbers, same verbs of ownership — and surface all of them to the user
together at the end, old → new. If a posting wants something they genuinely lack, that is
a **gap to report**, not something to word around.

**Hazard two: editing `master.md` mid-batch changes resumes already built.** A bullet
added for role 5 was not available to roles 1–4. Rewrites don't have this problem
because they never touch `master.md` — but a durable phrasing does. If you add one partway
through, **rebuild the roles already built in this run.** One command each, and the
alternative is a folder of resumes built from different versions of the truth with nothing
on disk saying which is which.

## Step 4 — build

Per role:

```bash
python scripts/build_resume.py --manifest <role.json> \
    --company "<Company>" --title "<Title>"
```

Pass `--company` and `--title` **exactly as the parser reported them** — it already applied
the same filename sanitizing the builder uses, so the paths it printed are the paths you
get. The builder files both artifacts:

```
Applications/<Company>/<Job Title>.pdf
Applications/<Company>/<Job Title>.tex
```

Those, plus the `- posting.txt` saved in Step 2. Keep the rewrite specs in scratch — they
are inputs to one build, not deliverables, and the filed `.tex` already records the result. `pdflatex` runs with `-output-directory Resume/build`, so
`.aux`, `.log`, `.out`, and `.synctex.gz` stay in `Resume/build/` and never reach an
application folder.

The filed `.tex` matters more than it looks: every build overwrites
`Resume/LaTeX/editing_<variant>.tex`, so without the copy a batch of seven would leave
only the seventh on disk. The copy is standalone — CTAN packages, no local includes — so
it recompiles anywhere if one posting ever needs a hand tweak.

**Never hand-edit a filed `.tex`.** It is a snapshot of what was sent. Change the manifest
and rebuild.

## Step 5 — verify each one by looking at it

Read each PDF. Do not batch-build seven and check only the last — each was built from a
different manifest, so a mistake in one says nothing about the others. The builder trims
from the end of a manifest when a page overflows, and what it dropped is per-role.

Per `tailor-resume` Step 5, check each for: within the page limit, no unexplained date gap,
current role present, most relevant evidence in the top third, and the company and title
spelled the way the employer spells them.

**Check the bottom of every page, not just the top.** Holding the page limit is necessary,
not sufficient — a half-empty page holds it too. If any build still reports slack, that
role is not done: add `fill` candidates and rebuild it before reporting the batch
complete.

## Step 5b — cover letters, for every role ticked `cover letter`

Follow `cover-letter` Steps 4–6 per role, after that role's resume is built, so each
letter can complement its resume. Step 2a has already asked why each company and filled
the files with what the letters need. A user who asks for a letter on a role without the
box gets one too: run Step 2a for it first. Every letter gets its own `--check` and its
own report of paragraphs beside sources.

## Step 6 — report once, as a table

| # | Company | Title | Cluster | Variant | Pages | Letter | Filed |
|---|---|---|---|---|---|---|---|

The Letter column is "—" for roles without one.

Then, below it, only the things that need the user's attention:

- **every reworded bullet, old → new**, grouped by role. This is the part they most need
  to check, because it is the only place a claim could have drifted. Flag any the builder
  marked as cut before reaching the page.
- **roles not built** — dead postings, failed fetches — and which is which
- **anything cut to hold the page limit** — the builder prints this; it is the most
  important line in its output
- roles where the builder's variant differed from the digest's suggestion, and why
- gaps found against postings, gathered from Step 3
- anything added to `master.md` or `story.md`, stated explicitly — those files are their
  ground truth and they should know when they change

End with one line: as each one is sent, mark it `applied` in the page's Applications tab,
so later scans learn what came of it. Do not mark them yourself; only the user knows what
went out.

## Notes

- Re-running is safe. Builds are deterministic from `master.md` and overwrite in place, so
  a second run refreshes rather than duplicating. Use `--pending` to build only what's new.
- `Applications/` is gitignored, so nothing filed here shows up in `git status`. Don't
  expect a diff to confirm the work — check the paths.
- Only the `.pdf` and `.tex` are filed. Notes, email chains, and `.url` files already in
  those folders are the user's and are left alone.

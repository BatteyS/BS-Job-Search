---
name: tailor-resume
description: Build a tailored resume for a specific job posting by reading the posting in full, then selecting from content/master.md, then filing the PDF and .tex into Applications/<Company>/<Job Title>.*. Use when the user says "tailor my resume", "make a resume for this job", "apply to <company>", or references a digest entry.
---

# Tailor resume

Three steps, in this order, and the order is the whole method:

1. **Read the job description in full.**
2. **Read `content/master.md` in full** — all of it, so you know the whole scope of what could go on the page.
3. **Write a manifest** naming what goes on the page, and let the builder fit it.

`master.md` is a database of true things about the user's experience. It is small enough
to hold in mind at once, which is why nothing pre-sorts it for you. It once carried
cluster tags meant to pre-select bullets per posting; they picked the wrong evidence and
were removed. Judge each bullet against the posting in front of you.

How `master.md` is written matters for one thing below, rewrites:

- **Plain text** is the default. The builder escapes it, so "R&D", "40%", and "$1.2M"
  print as written, and Unicode like CO₂ or ≥ works.
- **LaTeX source** — a file that already escapes its specials (`\$11M`, `M\&V`, `10\%`) —
  is detected and passed through as is.

The builder prints which it found on every build (`master : ... as text`). The file's
front matter can force either with `format: text` or `format: latex`, and can also set
`max_pages` and `section_order`.

## Step 1 — read the posting in full

**Never tailor from a digest entry.** Most are aggregator snippets: on 2026-08-12, six of
the seven roles marked apply carried 539-character descriptions — about eighty words.
Enough to score a role, nowhere near enough to tailor one.

```bash
python scripts/fetch_posting.py --url "<url>" --out "Applications/<Company>/<Job Title> - posting.txt"
```

It saves the text beside the resume — postings vanish once filled, and this is the copy
worth having for interview prep. Exit codes:

| Code | Meaning | What to do |
|---|---|---|
| 0 | full description | read it, then continue |
| 2 | too short — JS-rendered page or a board root URL | fetch it in a browser, or ask for a paste |
| 3 | closed, expired, or 404 | **stop.** Report it and skip the role |
| 4 | network or HTTP failure | retry once, then ask |

**Before a browser or a paste, try the employer's own board.** A LinkedIn or aggregator
link that fails or comes back thin is usually also on the employer's Greenhouse, Lever,
Ashby, or Workday board: `detect_ats.py` finds the board, and `probe_workday.py` finds a
Workday one. On 2026-11-02 LinkedIn refused Redwood's posting, and Redwood's Greenhouse
board had it. Check the location there as well, since the listing and the board can
disagree: one LinkedIn listing said Walnut Creek, and the employer's board said remote.

Then actually read it. What the first qualification demands, what the responsibilities
emphasize, and the vocabulary the employer uses for the work.

## Step 2 — read master.md in full

Read the whole file. Then decide, per role and per bullet, what this posting makes
relevant. You are looking for evidence that answers the posting's asks — not for keyword
overlap.

## Step 3 — write the manifest

The manifest is the resume: it names roles in page order, bullets within each role in
order, the layout variant, and which optional sections appear.

```json
{
  "variant": "split",
  "experience": [
    {
      "employer": "Acme Energy",
      "role": "Project Engineer",
      "bullets": [
        "Managed execution and grant compliance",
        {"match": "Provided owner's-side commissioning oversight",
         "text": "Provided owner's-side technical oversight for the site integration and ..."}
      ]
    },
    {"employer": "Globex", "role": "Reviewer", "additional": true,
     "bullets": ["Promoted to senior reviewer"]}
  ],
  "projects": [],
  "skills": ["Software & Data"],
  "sections": {
    "Licenses & Certifications": ["Registered Nurse"],
    "Volunteer": [{"employer": "Free Clinic", "bullets": ["Triaged walk-in patients"]}]
  }
}
```

- A bullet is either a **match string** (any unique fragment of the bullet) or an object
  with `match` plus optional `text` to reword it. Escapes and wrapping are ignored, so
  write matches naturally — `M&V` finds a stored `M\&V`.
- **Manifest order is page order** within each section. No relevance heuristic runs.
- `"variant": "split"` splits into *Relevant Experience* and *Additional Experience*;
  `"additional": true` puts a role in the second group. Use split when the strongest
  evidence isn't the most recent — the heading is what licenses non-chronological order.
  Use `chronological` when recent work already leads.
- `projects`, `skills`, and everything under `sections` are **optional whole sections**.
  Omit or empty them to drop the heading entirely. Projects earns its space on few postings.
- `sections` reaches any other `# Section` in `master.md`, by its heading: a list of
  match strings for a section of bare bullets (like Certifications), or entries shaped like
  `projects` for a section of `## Entry` blocks (like Volunteer).
- Education always appears, whole.
- `order` (optional) names the sections in page order for this one resume, overriding
  `section_order` in `master.md`. Sections it leaves out follow in the usual order.
- `max_pages` (optional) overrides the page limit for this one resume. A federal resume,
  or a senior one, may warrant two; otherwise leave the profile's limit alone.

### What to put on it

**Fill the page.** A resume with white space at the bottom is wasted room — it reads as
though there was nothing more to say. Put the evidence that earns the role in
`experience`, then list everything else worth having in `fill` (next section). Do not
guess at length: the builder measures.

**Leave off what doesn't serve this posting.** This is the point of the manifest. A role
that contributes nothing but a generic line is diluting the page, not covering it.

**But the timeline has to hold.** A role may be omitted only if its absence opens no gap
in the employment dates — the builder enforces a ~3 month tolerance and refuses a trim
that would break it, but choose deliberately rather than relying on the check. A role that
sits inside another role's dates (an internship during a degree, a side role during a
longer job) is droppable; roles that carry the timeline are not. **The current role
always appears.**

**A role that must appear for continuity but has little to say** gets one bullet — its
`S` summary line is written for exactly that. Where that role may sit is the next rule.

### One-bullet roles: where they belong, and how many

**Nothing under Relevant Experience may carry a single bullet.** The heading asserts the
work matters; a role supporting that with one sentence undercuts the claim. Give it a
second bullet, move it to Additional Experience with `"additional": true`, or build
chronological — which makes no relevance claim, so one-line roles are fine there.

**The builder refuses to file a split resume that breaks this.** It exits non-zero with
the offending roles named and nothing is written to `Applications/`, because this shipped
once: a resume went out with a one-line internship under Relevant Experience.

**In Additional Experience and the optional sections, one bullet is fine** — that is what
those sections are for. But cap the total: **two one-line roles is comfortable, three is
tolerable, four makes the page read as a list of jobs with nothing to say about them.**
The builder warns above three, and the fill pass will not create a fourth.

### Filling the leftover space

Trimming has a counterpart. A manifest written conservatively produces a short page, and
nothing in the build used to notice — several resumes went out with 7–8 lines of unused
room at the bottom.

So the manifest carries a second, optional list. **`experience` is what the page must
show; `fill` is what it should also show if there is room.**

```json
{
  "experience": [ ... ],
  "skills": [ ... ],
  "fill": [
    {"employer": "Acme Energy", "role": "Project Engineer",
     "bullets": ["Conducted measurement and verification"]},
    {"employer": "Initech", "additional": true,
     "bullets": ["Built a risk-modeling system"]},
    {"section": "projects", "employer": "Capstone",
     "bullets": ["Developed process flow models"]},
    {"section": "skills", "match": "Process Engineering"},
    {"section": "Licenses & Certifications", "match": "ACLS"}
  ]
}
```

Entries take the same shape as `experience`, `projects`, `skills`, and `sections`; for
any other section, `section` is its heading. A candidate may add bullets to a role already
on the page, or **an entire role that isn't there yet** — name a role not in `experience`
and it is appended to its section.

How the builder handles them:

- Candidates are tried **in the order you list them**, so order by value, not by size.
- Each is kept only if the page count still holds — it recompiles and re-checks after
  every one. This is a measurement, not an estimate.
- A candidate that doesn't fit at the current spacing gets the tighter spacing tiers
  before it is rejected: a page with slightly narrower margins and one more piece of
  evidence beats a roomier page that stops two thirds down. Tightening never trims what
  you chose — if no tier fits the candidate, the candidate goes.
- A candidate that doesn't fit is reverted and the next is still tried: a one-line skills
  entry fits where a three-bullet role didn't.
- Every candidate is resolved against `master.md` up front, so a typo fails the build
  immediately rather than only on runs where the page happened to have room.

**What to put in `fill`. Rank by relevance to the posting, full stop.** Do not rank by
where the bullet lives. If the most relevant remaining evidence sits in a role you left
off entirely, that role goes at the top of the list — bringing back a whole role is not a
last resort, it is a normal outcome of ranking honestly.

The one thing that overrides relevance order is the one-line cap above: a candidate that
would add a *fourth* single-bullet role is skipped no matter how well it scores. That is
also the ordering hint — put candidates that deepen a role already on the page above
candidates that introduce a new one-line role, since the first kind never trips the cap.

If the build still reports slack with every candidate placed, go back to `master.md` and
find more. That message means you under-asked.

### Rewriting bullets to the posting

Once the right bullets are chosen, reword them in the posting's vocabulary via `text`.

- The builder can only **replace** a bullet that already exists. It cannot add one.
- A match hitting zero or several bullets is a **hard error**, never a silent no-op.
- **Write `text` the way `master.md` is written.** Plain text for a plain-text file — the
  builder escapes it. For a LaTeX-source file, `text` carries its own escapes (`\$11M`,
  `M\&V`, `10\%`) and unescaped specials are rejected, because `%` comments out the rest
  of the bullet and `$` opens math mode; balanced short math spans like `CO$_2$` are fine.
- Rewrites are **transient**. Nothing is written to `master.md`; the filed `.tex` is the
  record of what was sent.

**Reword only what is already documented.** Check each rewrite against the original: same
scope, same numbers, same verbs of ownership. "Coordinated contractors" may become "served
as the owner's liaison to the contractors" — same work, the posting's words. It may not
become "managed the contracts."

**Never invent, embellish, or infer a claim.** If the posting wants something the user
genuinely lacks, that is a **gap to report**, not something to word around. When in doubt,
ask — a fabricated bullet is far worse than a thinner resume.

### When something belongs in master.md instead

If real experience is missing from `master.md` entirely, it cannot go on a resume. That is
a gap to raise with the user so **they** add it. `master.md` is human-maintained ground
truth; never add a fact to it on their behalf, and tell them explicitly if they ask you to
change it. The one route in besides their own hand is the cover-letter interview, which
adds what they tell it and approve (CLAUDE.md).

## Step 4 — build

```bash
python scripts/build_resume.py --manifest plan.json \
    --company "<Company>" --title "<Job Title>"
```

Files both artifacts:

```
Applications/<Company>/<Job Title>.pdf
Applications/<Company>/<Job Title>.tex
```

Those plus the `- posting.txt` from Step 1. `pdflatex` runs with
`-output-directory Resume/build`, so `.aux`, `.log`, `.out`, and `.synctex.gz` never reach
an application folder. Keep manifests in scratch — they are build inputs, not deliverables.

The filed `.tex` matters: every build overwrites `Resume/LaTeX/editing_<variant>.tex`, so
without the copy a batch would keep only the last. It is standalone — CTAN packages, no
local includes — so it recompiles anywhere.

**Never hand-edit a filed `.tex`.** It is a snapshot of what was sent. Change the manifest
and rebuild.

Read the output. It reports how `master.md` was read, what landed on the page, every
rewrite, the fill pass (`+` placed, `-` no room), and **anything trimmed to hold the page
limit**.

Two lines decide whether you are done:

- **`trimmed to hold the page limit`** — you overshot, and the builder chose what to lose.
  Check what went: if it was evidence the posting asked for, cut something else in the
  manifest instead of accepting the builder's pick.
- **`roughly N lines of slack still on the page`** — you under-asked. Add more `fill`
  candidates and rebuild. Do not leave this line unanswered; it is the exact defect the
  fill pass exists to catch. LaTeX measures this itself, so it appears on every machine.

### ATS keyword check

Everything above optimizes for a 30-second human scan. At a large employer a parser
screens first, which is a different test:

```bash
python scripts/ats_check.py --jd "Applications/<Company>/<Job Title> - posting.txt" \
    --resume "Applications/<Company>/<Job Title>.tex" --company "<Company>"
```

Check the `.tex` filed with the application. `Resume/LaTeX/editing_<variant>.tex` holds
only the last build, which in a batch is some other role's resume.

Missing keywords split two ways, and the split matters more than the percentage. If the
evidence is in `master.md` and you didn't pick it, that's a tailoring miss — fix the
manifest. If it appears nowhere in `master.md`, either the user did the work and never
used that word (rephrasing is legitimate) or they genuinely lack it (report the gap).
Don't chase the raw percentage; compare between postings, where a much lower score means
a real stretch.

## Step 5 — verify by looking at it

Read the generated PDF. The page count alone cannot see a missing employer, a widow line,
or a section that reads oddly. Check:

- Within the page limit, no unexplained gap in dates, current role present
- The top third carries the evidence this posting asks for
- Nothing overflows or leaves a nearly-empty extra page
- Company and title spelled the way the employer spells them

## Step 6 — report

Variant, what landed, **every rewrite old → new**, anything trimmed, gaps found against the
posting, and where the files landed.

---

## Notes

- `--all` builds the full CV from every bullet with no manifest:
  `--all --out cv_generated --max-pages 2` (that name is gitignored).
- `editing_chronological.tex` and `editing_split.tex` are build artifacts. Never edit them
  by hand and never treat them as sources.
- Work-history roles need dates the builder can read — "May 2022 – May 2024",
  "Sept. 2019 - Dec 2021", "Summer 2023 – 2024", "05/2022 – Present". It stops and names
  the role otherwise, because an unreadable date would let it cut a role that holds the
  timeline together.
- `--master` and `--contact` build from other files, such as an example profile, without
  touching the user's own.

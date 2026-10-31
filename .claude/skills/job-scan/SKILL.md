---
name: job-scan
description: Scan job boards for roles matching the user's profile and write a ranked digest. Asks which role clusters to target, then fetches, scores, and writes digests/YYYY-MM-DD.md. Use when the user says "job scan", "scan for jobs", "run the job search", or invokes /job-scan.
---

# Job scan

One interactive pass: ask what to look for, run it immediately, write the digest.
Takes a few minutes end to end. Run it whenever you feel like looking.

## Step 1 — ask what to target

Read `profile/clusters.yaml` for the available clusters. Ask with `AskUserQuestion`,
`multiSelect: true`, one option per cluster, using each cluster's `label` as the option
label and a short line from its `rationale` as the description.

If `data/last-run.json` exists, mention which clusters were used last time — repeating a
scan with the same targeting is the common case.

Ask only this one question unless the user has already said what they want, in which case
skip straight to Step 2. Do not ask about metros, age windows, or comp — those live in
`profile/filters.yaml` and are settled. When the user does narrow a run themselves ("New
York only", "no remote this time"), pass `--metros <keys>` or `--remote exclude|only`: both
apply to every source for that run and change nothing in the profile.

## Step 2 — fetch

```bash
python scripts/fetch_jobs.py --clusters <comma-separated ids>
```

Which sources it reads comes from `sources` in `profile/filters.yaml` — the company
boards, Adzuna, USAJOBS, and whichever scraped boards (Indeed, LinkedIn, Glassdoor,
ZipRecruiter) the user has turned on. Do not add source flags unless the user asks for a
narrower or wider run than the profile sets, and **never turn on a scraped board the user
has not turned on**: those boards' terms prohibit scraping, and turning one on is the
user's decision. The scan prints a warning line for each scraped board it runs; pass
those through.

A few minutes across ~188 boards plus the other sources; LinkedIn, paced at one query
every few seconds, is the slowest. Writes `data/candidates-YYYY-MM-DD.json` and prints
counts to stderr. No LLM involved — every mechanical filter (metro allowlist, comp floor,
posting age, title regex, seniority, aggregator domain gate, experience gate, dedupe) has
already been applied by the time it returns.

The aggregators and scraped boards are where breadth comes from: on 2026-08-19 the
company boards alone gave 70 of 576 candidates, and Indeed reached 161 employers no other
source did. If a scraped board reports `skipped`, the JobSpy library is not installed;
see README.md, because the obvious pip command installs a 2023 version that silently
does the wrong thing. A board that refuses requests mid-run is stopped and says so — the
next scan retries it; do not rerun it straight away.

Record the chosen clusters to `data/last-run.json` so the next run can offer them as the
default.

If the command fails, show the error and stop. Do not fall back to a partial scan.

## Step 3 — read scoring context

Read in this order:
- `profile/profile.md` — in full. It is the user's own account of who they are, what
  they want, and how to judge a role. **The rubric it states is the scoring rubric.**
- `profile/feedback.md` — past verdicts; these are the calibration signal
- `profile/clusters.yaml` — `scoring.min_score`, and each active cluster's `min_score`,
  `scoring_note`, and `default_resume`
- `data/candidates-YYYY-MM-DD.json`

With more than 40 candidates, score in batches of 25. Score every candidate — never skip
some to save effort, then filter by threshold afterward.

> **This rule costs real time on a large scan.** A run can produce hundreds of
> candidates, and "score everything in 25s" is then a dozen batches or more. Do not
> quietly start skipping candidates to make that tractable: ranking before scoring sorts
> unreachable prestige roles to the top. If the volume is impractical, say so to the user
> and let them choose: a cheap triage pass over all of them followed by full scoring of
> the top slice, or scoring everything.
>
> Two settings in `filters.yaml` decide how much there is to read: `max_candidates` (how
> many) and `max_description_chars` (how much of each). Lowering either is the user's
> decision, made in that file — never a way to finish a scan sooner.

## Step 4 — score

Per candidate: `fit` (0-100), `why` (one sentence), `resume` variant, `gaps`,
`effort` (low/med/high).

**Score against the rubric in `profile.md`, not keyword overlap.** The profile says what
makes a role worth the user's time — what to score up, what to score down, and why. Apply
it as written; it overrides any generic sense of a good job. A posting does not earn points
for restating the user's resume back at them, and a role with unglamorous keywords can
still score high when it matches what the profile says matters.

Apply `profile/feedback.md`'s standing corrections on every run, as that file says. They
are rules drawn from verdicts the user actually gave.

If a candidate's cluster has a `scoring_note` in `clusters.yaml`, apply it as well.

**Then subtract the location penalty** already computed in each candidate's `loc_penalty`
field. It comes from the metro's `penalty` in `filters.yaml`, or `remote.penalty` for a
remote posting. Use it as given; do not re-derive it.

**Thresholds.** A candidate reaches the digest when its final score is at least its
cluster's `min_score` in `clusters.yaml`, or `scoring.min_score` when the cluster sets
none. A candidate in several clusters needs only the lowest of their bars.

**Resume variant.** Suggest `chronological` or `split`, the two layouts the builder has.
Start from the cluster's `default_resume`. `split` suits a posting whose strongest evidence
is not the user's most recent work. The tailoring step makes the final call after reading
the full posting.

## Step 5 — write the digest

Write `digests/YYYY-MM-DD.md`, sorted by final score descending. If a digest for today
already exists, append a new run section rather than overwriting it.

```markdown
# Job digest — 2026-08-06

**Clusters:** clinical-informatics, cardiac-critical-care
**Scanned:** 80 boards · 6,384 postings · 33 candidates after filters · 12 scored ≥60

> Mark each entry. These verdicts calibrate the next run's scoring.

---

### 1. Valley Health Partners — Clinical Informatics Nurse · **84** · Sacramento · $128,000
- [ ] apply
- [ ] skip — reason:

**Why:** Turns bedside workflows into Epic build requirements across 12 hospitals, the
move from bedside to informatics the profile is after.
**Resume:** chronological · **Effort:** low
**Gaps:** prefers an Epic certification; the user has super-user experience instead
[View posting](https://...)
```

Rules:
- **Always state the metro**, and show the penalty for anything outside the user's top
  metro (the one with penalty 0). A role at 80 is only useful if it's obvious where it is.
- If `duplicate_count` > 1, note "N identical reqs posted".
- Show comp only when disclosed. Never guess or estimate it.
- If `stats.clipped` > 0, say so — the candidate cap was hit and something was dropped.
- If `stale_boards` is non-empty, list it under `## Warnings`. A board failing 3+ runs is
  a silent coverage hole.
- If nothing clears the threshold, still write the digest with the counts and say plainly
  that nothing cleared. A thin digest is information, not a failure.

## Step 6 — reconcile applications

List `Applications/`. A folder there means the user has applied to **that company**, not
necessarily to this role — applying to a second role at the same employer is normal and
often sensible. So annotate rather than exclude:

- If the folder contains files matching this specific role, mark it **already applied**
  and drop it out of the ranking.
- If the folder exists but the role looks different, keep it ranked and add a one-line
  note: "previously applied to <company>" — useful context for a referral or follow-up.

Folder names won't always match a digest's spelling of the employer ("Black and Veatch"
vs "Black & Veatch"), so compare names loosely.

## Step 7 — offer to record verdicts

Show the top few in chat and offer to append verdicts to `profile/feedback.md` once the
user has read the digest. Don't append blank entries — a verdict with no reason teaches
nothing.

---

## Notes

- Never edit `profile/profile.md`. It's human-maintained ground truth.
- Never widen filters to produce more results. A thin digest means the market is thin this
  week, or board coverage needs work — fix coverage, not the filters. Roughly half of
  established employers sit on ATS platforms we cannot read from Python (Oracle HCM, Taleo,
  Avature, Eightfold, UKG, Phenom, iCIMS), which is the real ceiling.
- To add a company: `python scripts/detect_ats.py 'domain.com=Company Name'`, then paste
  the emitted block into the `manual:` list in `sources/companies.yaml`.
- To tune a cluster's title patterns, or check a title preset, run
  `python scripts/fetch_jobs.py --clusters <ids> --preview`. It lists what each cluster
  lets through in the user's metros and what each exclude pattern drops, and writes
  nothing.

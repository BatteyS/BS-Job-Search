# Example profiles

Two complete, fictional profiles, from fields far apart, to show what the files look like
filled in. Read one before running `/setup`: it is the quickest way to see what the
interview is building toward, and how much detail is worth giving it.

| Example | Who | Shows |
|---|---|---|
| [`nurse-sacramento/`](nurse-sacramento/) | Jordan Rivera, a cardiovascular ICU nurse moving toward clinical informatics | A one-page resume with a licenses section, hourly pay against an annual floor, USAJOBS scoped to the VA, and exclusions written for nursing |
| [`product-marketer-chicago/`](product-marketer-chicago/) | Avery Chen, a senior product marketer aiming for director | A two-page resume, a remote-friendly search with a nationwide remote query, and a preset left out on purpose (see its `clusters.yaml`) |

Every person, employer, school, and number in them is invented.

## What each file is

| File | Lives at, in your copy | What it holds |
|---|---|---|
| `contact.md` | `content/contact.local.md` | Name, email, links. Gitignored there, so your details never reach the repository. |
| `master.md` | `content/master.md` | Every resume fact you have, more than any one resume holds. Each resume is selected from it; nothing on a resume can come from anywhere else. |
| `story.md` | `content/story.md` | What a cover letter needs that a resume does not: why this field, what you want next, the stories behind your best bullets. In your own words. |
| `profile.md` | `profile/profile.md` | How a scan should judge a role for you: constraints, what to score up and down, hard passes. Candid, and never sent to anyone. |
| `clusters.yaml` | `profile/clusters.yaml` | The kinds of role to look for: title patterns, search terms, score bars. |
| `filters.yaml` | `profile/filters.yaml` | Where to look and how much: metros, remote, pay floor, sources, and the two settings that decide what a scan costs to score. |

`profile/feedback.md` is not shown: it starts empty and fills with your verdicts on each
digest. Nor is `profile/applications.yaml`, which the page's Applications tab writes as you
record where each application stands; each demo has one.

## Demos

Each example also has a `demo/` folder: a fictional digest, the postings for the roles it
marked `apply`, the resume selections (manifests) for them, a cover letter, and
`applications.yaml`, where those applications stand. From those,
`ui/build_demo.py` builds the local page as static files, filled in for that person, with
the resumes and letters built from their `master.md` and `story.md`:

```bash
python ui/build_demo.py demo-site
```

Open `demo-site/index.html` through any static file server, or see them published at
[batteys.github.io/BS-Job-Search](https://batteys.github.io/BS-Job-Search/).

## Trying one

Build an example's full resume — every bullet, fitted to its page limit:

```bash
python scripts/build_resume.py --all --master examples/nurse-sacramento/master.md --contact examples/nurse-sacramento/contact.md --out editing_example
```

The PDF lands in `Resume/pdf/editing_example.pdf`. Use `uv run python` in place of
`python` if you set up with uv.

See which job titles an example's clusters would keep, among the company boards in
`sources/companies.yaml` (this reads those boards, so it needs a network connection):

```bash
python scripts/fetch_jobs.py --all-clusters --preview --sources boards --clusters-file examples/nurse-sacramento/clusters.yaml --filters examples/nurse-sacramento/filters.yaml
```

## Starting your own

Press **Set up** on the page's Setup tab, or run `/setup` in Claude Code. It interviews
you and writes these six files, then leaves them yours to edit. You do not need to copy
an example first.

To write them by hand instead, put each file at the path in the table above, starting
from whichever example is closer to you, and run `python scripts/doctor.py` to see what
is still missing. Pick metros from `presets/metros.yaml` and copy them into your
`filters.yaml` whole; the copy is yours to edit.

---
name: cover-letter
description: Write a cover letter for a specific job posting from content/master.md and content/story.md, with every factual claim citing its source, then file the PDF, .tex, and a plain-text copy into Applications/<Company>/<Job Title> - cover letter.*. When those files lack what the letter needs, interviews the user and, with their approval, adds the answers to story.md and master.md first. Use when the user says "write a cover letter", "cover letter for <company>", or asks for a letter alongside a tailored resume.
---

# Cover letter

A cover letter does one thing a resume cannot: it says why this person wants this role,
and connects two or three pieces of their evidence to what the posting asks for, in
sentences. It fails in two predictable ways. It invents — enthusiasm the user never
expressed, a metric slightly better than the real one. Or it says nothing — boilerplate
that could go to any employer. Everything below guards against one or the other.

## Step 1 — read the posting in full

If the resume for this role was tailored already, the posting is saved beside it:
`Applications/<Company>/<Job Title> - posting.txt`. Otherwise fetch it the way
`tailor-resume` Step 1 does:

```bash
python scripts/fetch_posting.py --url "<url>" --out "Applications/<Company>/<Job Title> - posting.txt"
```

**Never write a letter from a digest snippet.** Read the posting for what the role owns,
what the first qualification demands, the problems the team is hiring to solve, and the
words the employer uses for the work.

## Step 2 — read the user's material

Read in full:

- `content/master.md` — the facts a letter may use.
- `content/story.md` — motivations, career moves in the user's words, the stories behind
  the bullets, and things to keep out. Some users leave its stories for later, and some
  have no story.md yet. Either way, Step 3b asks for what this letter needs, and Step 3c
  adds it, starting the file from the headings of `content/story.example.md` if there is
  none.
- The resume filed for this role, `Applications/<Company>/<Job Title>.tex`, if there is
  one. The letter complements it — it tells the story behind two or three of its
  bullets — rather than restating it.

Do **not** draw on `profile/profile.md`. It is written for scoring, candidly, and holds
things an employer should not read.

## Step 3 — ask why this company

Ask the user one question: why do they want **this** role at **this** company? A sentence
or two, in their own words. The letter needs it, and it is the one thing you cannot
supply — enthusiasm the user did not express is a fabrication, however plausible.
`story.md` may say why the field; the reason for this company comes from the user.

If they would rather not say, the letter opens with the fit between what the posting
asks for and what they have done, and says nothing about feelings it was not told.

Their answer belongs to this letter alone. Cite it as `user`, and keep it out of
`story.md`, where another company's letter could pick it up.

## Step 3b — interview for what the letter still needs

Pick the two or three strongest matches between the posting's asks and the user's work
in `master.md`. For each, look in `story.md` for the story behind it: the situation, what
they did, and what changed. Look too for a "Why this field" paragraph that fits this
posting's field. Ask for whatever is missing, the way `/setup` interviews:

- **One story at a time, a few questions per turn.** What was the situation? What did
  *they* do? What changed because of it, and how do they know?
- **Keep every claim as they give it.** Numbers only as stated, so an estimate stays an
  estimate. The same verb of ownership: helped is not led. Their scope, not a bigger one.
- **Ask nothing the files already answer.** If an answer differs from `master.md` or
  `story.md`, say how, and ask which is right.

If they would rather not tell a story, choose other evidence or write one evidence
paragraph instead of two. Never fill the gap yourself.

## Step 3c — save what they said, then write

Before writing the letter, put each answer where it belongs, so this letter cites a file
and the next letter finds it there:

- **`story.md`.** A story under Stories worth telling, a reason for a new field under Why
  this field, a move under Career moves. Write it in their words: tidy the grammar, keep
  their phrasing, and make each paragraph a whole thought that stands alone. Update any
  comment there that marks what is still to tell.
- **`master.md`.** A new resume fact, such as a number, a scope, or an accomplishment
  the file lacks, becomes a bullet under its role in the file's own format, with the
  priority they choose.
- **Keep out of letters.** Anything they want kept out, by topic, never the details.

Show the exact text for each file and write only what the user approves. Add to these
files; never rewrite or remove what is already there. Then cite the new passages as
`story` or `master`.

## Step 4 — write the letter file

250–400 words in three or four paragraphs:

1. **Opening** — the role, and why this company, built on the user's own sentence.
2. **Evidence**, one or two paragraphs — the two or three strongest matches between the
   posting's asks and the user's work, each told as a story: the situation, what they
   did, what changed. Choose evidence the resume shows briefly and a paragraph can expand.
3. **Close** — one or two sentences, forward-looking, no padding.

```json
{
  "greeting": "Dear Hiring Team,",
  "paragraphs": [
    {"text": "...", "sources": [{"user": "..."}, {"posting": "..."}]},
    {"text": "...", "sources": [{"master": "..."}, {"story": "..."}]},
    {"text": "...", "sources": []}
  ],
  "closing": "Sincerely,"
}
```

Each paragraph lists what backs its claims:

| Source | What it names |
|---|---|
| `master` | a unique fragment of a `master.md` bullet, or of a role heading ("Acme Energy \| Project Engineer") for titles and dates |
| `story` | a unique fragment of a `story.md` paragraph or list item, never one under "Keep out of letters", which the builder refuses |
| `posting` | a phrase quoted exactly from the saved posting — for anything said about the company or the role |
| `user` | what the user told you in this conversation, in their words: chiefly why this company |

The resume's rules, applied to sentences:

- **Every claim traces to a source.** Paraphrase freely; add nothing. Same scope, same
  numbers, same verbs of ownership as the source.
- **Every number has to appear in one of its paragraph's sources** — in digits or words,
  so "three years" counts. The builder checks, and refuses a letter that fails. It cannot
  catch everything: a claim with no number in it is yours to check against its sources.
- **Nothing about the company beyond the posting** and what the user said. No researched
  facts, no guessed mission statements.
- **A paragraph with no sources may make no factual claim** — a closing line, a thanks.
- **Address a named person only if the posting names them.** Otherwise "Dear Hiring Team,".
- No salary, no reasons for leaving a job, and nothing `story.md` lists to keep out.

Voice: plain and specific. If `story.md` has a writing sample, sound like it. Cut stock
phrases — "I am writing to express my interest", "passionate", "proven track record",
"great fit". The builder flags them; each one tells the reader nothing.

Keep letter files in scratch. They are build inputs, not deliverables.

## Step 5 — check, then build

```bash
python scripts/build_letter.py --letter letter.json \
    --company "<Company>" --title "<Job Title>" --check
```

`--check` resolves every source and runs every check without building anything. Fix each
error it names: a source matching nothing or several passages, a posting quote that is
not in the posting, a number no source contains. Then build:

```bash
python scripts/build_letter.py --letter letter.json --company "<Company>" --title "<Job Title>"
```

It files three files beside the resume, and reads the saved posting to check quotes:

```
Applications/<Company>/<Job Title> - cover letter.pdf
Applications/<Company>/<Job Title> - cover letter.tex
Applications/<Company>/<Job Title> - cover letter.txt    plain text, for application forms
```

A letter longer than one page is refused, never trimmed — cutting a paragraph changes
what the letter says. Shorten it and rebuild.

## Step 6 — show the user every claim

Read the PDF, then report:

- the letter in full
- each paragraph beside its sources, from the builder's report — this is where the user
  checks that nothing drifted
- any note the builder raised (length, stock phrasing)
- where the files landed

The user approves the letter before it goes anywhere. If they change a claim, it has to
be true of them; if it is new, it goes into `story.md` or `master.md` first, as Step 3c
does, with their approval.

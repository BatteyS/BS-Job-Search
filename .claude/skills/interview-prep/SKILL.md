---
name: interview-prep
description: Write an interview prep sheet for one application filed under Applications/<Company>/ — the questions its posting makes likely, each answered from content/master.md and content/story.md as situation, action, result; the gaps it exposes, each with an honest way to address it; and questions to ask the employer — with every claim citing its source, checked by scripts/build_prep.py, then file it as Applications/<Company>/<Job Title> - interview prep.md. When those files lack a story an answer needs, interviews the user and, with their approval, adds it to story.md and master.md first. Use when the user says "interview prep", "prep me for the interview", "I have an interview with <company>", or invokes /interview-prep.
---

# Interview prep

An interview asks for what a resume only claims: the story behind a bullet, told out
loud, under follow-up questions. A prep sheet fails the way a cover letter does. It
invents — a better number than the real one, a story the user never told, an eagerness
they never voiced — or it says nothing, with answers that would fit any posting. And it
fails a third way: it skips the gaps, which the interviewer then finds.

The sheet is for the user's eyes, but every answer on it is something they will say to the
employer, so a letter's rules hold: every claim comes from `master.md`, `story.md`, the
posting, or the user in chat, and every number from one of them.

## Step 1 — find the application

From the page, the prompt names the posting:
`/interview-prep for Applications/<Company>/<Job Title> - posting.txt`. From a terminal,
the user names the company or the role; list `Applications/` and find the role's
`- posting.txt`. If several match, ask which.

Read in full:

- **The posting.** If none was saved, fetch it the way `tailor-resume` Step 1 does, or
  ask the user to paste it:

  ```bash
  python scripts/fetch_posting.py --url "<url>" --out "Applications/<Company>/<Job Title> - posting.txt"
  ```

  Never prepare from a digest snippet.
- **The resume filed for it**, `Applications/<Company>/<Job Title>.tex`. The interviewer
  has it in hand, and most questions start from a line on it.
- **The cover letter filed beside it**, `<Job Title> - cover letter.txt`, if there is one.
  An answer must not contradict what the letter told them.

If the user has said anything about the interview itself — who they are meeting, the
format, what the recruiter told them — use it. Don't interrogate them for it.

## Step 2 — read the user's material

Read in full:

- `content/master.md` — the facts an answer may use, including the bullets this resume
  left out.
- `content/story.md` — the stories behind the bullets, career moves in the user's words,
  what they want next, and what to keep out. If there is no story.md yet, Step 4c starts
  one from the headings of `content/story.example.md`.

Do **not** draw on `profile/profile.md`. It is written for scoring, candidly, and holds
things an employer should not hear.

## Step 3 — find the gaps the posting exposes

```bash
python scripts/ats_check.py --jd "Applications/<Company>/<Job Title> - posting.txt" \
    --resume "Applications/<Company>/<Job Title>.tex" --company "<Company>" --json
```

Leave out `--resume` when no resume was filed. Read its two lists for what they are:

- **`gaps`** — words the posting leans on that `master.md` never uses. Most are noise
  ("before", "bring") or vocabulary: the user did the work under another name, and an
  answer can use the posting's word for it. The rest are real gaps. When you cannot
  tell which, ask the user; it is a question about their work, so it belongs to Step 4b.
- **`selectable`** — evidence `master.md` has that the resume left out. An interview is
  where it can come up, so prefer it for an answer when a question calls for it.

Then read the posting's duties and requirements yourself, because a keyword count misses
most real gaps. A duty the user has never done ("test new and changed flowsheets before
each release") or a requirement they fall short of is a sentence, not a word. So is depth:
having used a tool is not having built in it.

## Step 4 — choose the questions

Five to eight questions an interviewer for this posting is likely to ask:

- **One for each main thing the role owns**, and for its first requirement, asked the
  way an interviewer would: "Tell me about a time you…", "How do you…". These get an
  answer told as situation, action, and result.
- **What any interviewer asks of this resume:** why this field, why each move (Career
  moves in `story.md`), and why this role. For "why this role" or "why us", ask the user
  once, as `/cover-letter` Step 3 does, in a sentence or two of their own; if a letter
  was filed, show them its opening so they can say whether it still holds. That answer
  belongs to this application: cite it as `user` and keep it out of `story.md`.
- **What the posting signals beyond its lists:** a phrase it repeats, a habit it names.

Each question lists what it was drawn from under `from`: the posting phrase that makes it
likely, or the `master.md` line it will land on. The gaps are Step 5's, not questions here.

A topic under "Keep out of letters" can still come up in an interview: a reason for
leaving a job, pay. If the resume or the posting makes one likely, list the question with
no answer, so the user decides what to say. Never draft that answer, and never cite the
item. A passage elsewhere in `story.md` may answer the professional side of it — a move
under Career moves — while the candid reason stays out.

## Step 4b — interview for what the answers still need

For each question, find the evidence that answers it best: a `master.md` bullet, and the
story behind it in `story.md`. A bullet usually holds the action and the result; the story
holds the situation and how it went. Where an answer needs a story `story.md` does not
have, ask for it, the way `/cover-letter` Step 3b does:

- **One story at a time, a few questions per turn.** What was the situation? What did
  *they* do? What changed because of it, and how do they know?
- **Keep every claim as they give it.** Numbers only as stated, so an estimate stays an
  estimate. The same verb of ownership: helped is not led. Their scope, not a bigger one.
- **Ask nothing the files already answer.** If an answer differs from `master.md` or
  `story.md`, say how, and ask which is right.

If they would rather not tell a story, choose other evidence, or leave the question with
no answer: the sheet shows it as one to prepare. Never fill the gap yourself.

## Step 4c — save what they said, then write

Before writing the sheet, put each answer where it belongs, as `/cover-letter` Step 3c
does, so this sheet cites a file and the next sheet or letter finds it there:

- **`story.md`.** A story under Stories worth telling, a move under Career moves, a
  reason under Why this field or What I'm looking for next. In their words: tidy the
  grammar, keep their phrasing, and make each paragraph a whole thought that stands alone.
- **`master.md`.** A new resume fact, such as a number, a scope, or an accomplishment the
  file lacks, becomes a bullet under its role in the file's own format, with the priority
  they choose.
- **Keep out of letters.** Anything they want kept out, by topic, never the details.

Show the exact text for each file and write only what the user approves. Add to these
files; never rewrite or remove what is already there. The one change allowed is ending a
role the user says has ended: when a new current role goes in, the old one's "– Present"
becomes the month they give. Then cite the new passages as `story` or `master`.

## Step 5 — the gaps, honestly

Each real gap from Step 3, named in a few words, with:

- **`from`** — the posting's words where it asks for this. Required: a gap the posting
  does not expose is not one.
- **`address`** — how to answer it in the room. Say it plainly first. Then the nearest
  real evidence, cited. Then what the user is already doing about it, only if a file or the
  user says so, such as a certificate in progress. If the posting offers training for it,
  quote that too. Never a claim that closes the gap: "I learn fast" is not evidence, and
  an eagerness the user did not voice is invented.

If the posting asks for nothing the files lack, list no gaps and say so in the report.

## Step 6 — questions to ask them

Three to five, each drawn from the posting — what the team owns, how the work is split,
how success is measured — and, where it fits, from what the user wants next in
`story.md`, so the answer tells them whether this role offers it. Each lists what it came
from. Nothing about pay or benefits unless the user asks for it, and nothing from "Keep
out of letters".

## Step 7 — write the prep file

```json
{
  "questions": [
    {"question": "Tell me about a time you ...",
     "from": [{"posting": "..."}],
     "situation": "...", "action": "...", "result": "...",
     "sources": [{"master": "..."}, {"story": "..."}]},
    {"question": "Why this role?",
     "from": [{"posting": "..."}],
     "answer": "...",
     "sources": [{"story": "..."}, {"user": "..."}]},
    {"question": "...", "from": [{"posting": "..."}]}
  ],
  "gaps": [
    {"gap": "...", "from": [{"posting": "..."}],
     "address": "...", "sources": [{"master": "..."}]}
  ],
  "ask": [
    {"question": "...", "from": [{"posting": "..."}, {"story": "..."}]}
  ]
}
```

Sources are the cover letter's four kinds:

| Source | What it names |
|---|---|
| `master` | a unique fragment of a `master.md` bullet, or of a role heading ("Acme Energy \| Project Engineer") for titles and dates |
| `story` | a unique fragment of a `story.md` paragraph or list item, never one under "Keep out of letters", which the builder refuses |
| `posting` | a phrase quoted exactly from the saved posting |
| `user` | what the user told you in this conversation, in their words |

The rules:

- **Every claim traces to a source.** Paraphrase freely; add nothing. Same scope, same
  numbers, same verbs of ownership as the source.
- **An answer is told as `situation`, `action` and `result`**, a sentence or two each, in
  the first person, as the user would say it; or, for a question about motivation, as one
  `answer`. It must cite `master`, `story`, or `user`: a posting quote says what the
  employer wants, never what the user did.
- **A question with no answer has no sources.** The sheet shows it as one to prepare.
- **Every number has to appear in its own passage's sources:** a question's in its
  `from`, an answer's or an address's in its `sources`. The builder checks, and refuses a
  sheet that fails. A claim with no number in it is yours to check against its sources.
- **A gap's `address` may go without sources** only when it says nothing about the user's
  past, as a letter's closing line does.

Keep prep files in scratch. They are build inputs, not deliverables.

## Step 8 — check, then file

```bash
python scripts/build_prep.py --prep prep.json \
    --company "<Company>" --title "<Job Title>" --check
```

`--check` resolves every source and runs every check without filing anything. Fix each
error it names: a source matching nothing or several passages, a posting quote that is not
in the posting, a number no source contains, an answer with nothing about the user behind
it, a gap with no posting quote. Then file it:

```bash
python scripts/build_prep.py --prep prep.json --company "<Company>" --title "<Job Title>"
```

It reads the posting saved beside the resume to check quotes, and files the sheet beside
it, where the page's Applications tab shows it:

```
Applications/<Company>/<Job Title> - interview prep.md
```

## Step 9 — show the user every claim

Report:

- each question with its answer, beside its sources, from the builder's report — this is
  where the user checks that nothing drifted
- the gaps, and how to address each
- the questions to ask them
- any question left without an answer, and why
- anything added to `story.md` or `master.md`, stated explicitly
- where the sheet landed

If the user changes an answer, it has to be true of them; if it is new, it goes into
`story.md` or `master.md` first, as Step 4c does, with their approval, and the sheet is
built again.

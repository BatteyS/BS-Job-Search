---
name: Your Name
phone: (555) 555-5555
email: you@example.com
location: City, ST
linkedin:
github:
website:
portfolio:
---

Copy this file to `content/contact.local.md` and fill in your real details.

`name` and `email` are required. The rest are optional: leave one blank and it is left
off the resume. Links print after your location, without the `https://` — write them
as `linkedin.com/in/you` or `https://you.example.com`. Write everything as plain text;
the builder escapes it.

`contact.local.md` is gitignored on purpose — it is the only file holding personal
contact information, so the repository can be shared or made public without a scrub.

**This is the one manual step when setting up a new machine.** Since the file never
syncs, `build_resume.py` will stop with an explicit message if it is missing rather than
quietly emitting a resume with placeholder contact details.

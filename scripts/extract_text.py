"""Pull the text out of a resume file, for /setup to transcribe into master.md.

    python scripts/extract_text.py ~/Downloads/resume.pdf
    python scripts/extract_text.py resume.docx --out resume.txt

A .docx needs nothing extra: it is a zip of XML, read with the standard library,
and bulleted paragraphs keep a leading "- ". A PDF needs the pypdf package,
which uv installs with the rest (or `pip install pypdf`). Plain text and
Markdown pass through. An old binary .doc cannot be read; save it as .docx or PDF first.

Layout does not survive. Columns, tables, and text boxes come out in reading
order at best, so the transcription reads this alongside the original, not
instead of it.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(path: str) -> str:
    """Paragraphs from the body, plus headers and footers -- contact details
    often sit in a header."""
    with zipfile.ZipFile(path) as z:
        parts = [n for n in z.namelist()
                 if re.fullmatch(r"word/(header\d*|document|footer\d*)\.xml", n)]
        parts.sort(key=lambda n: (0 if "header" in n else 1 if "document" in n else 2, n))
        out = []
        for name in parts:
            root = ET.fromstring(z.read(name))
            for p in root.iter(f"{W}p"):
                chunks = []
                for node in p.iter():
                    if node.tag == f"{W}t" and node.text:
                        chunks.append(node.text)
                    elif node.tag == f"{W}tab":
                        chunks.append("\t")
                    elif node.tag in (f"{W}br", f"{W}cr"):
                        chunks.append("\n")
                text = "".join(chunks).strip()
                if not text:
                    continue
                bulleted = p.find(f"{W}pPr/{W}numPr") is not None
                out.append(("- " if bulleted else "") + text)
    return "\n".join(out)


def pdf_text(path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit("Reading a PDF needs pypdf. `python scripts/doctor.py` prints the "
                         "command that installs it without removing anything else. Or "
                         "save the resume as .docx, or paste its text, and use that "
                         "instead.")
    reader = PdfReader(path)
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)


def extract(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return docx_text(path)
    if ext == ".pdf":
        return pdf_text(path)
    if ext in (".txt", ".md", ".markdown", ".text"):
        return open(path, encoding="utf-8", errors="replace").read()
    if ext == ".doc":
        raise SystemExit("An old .doc file cannot be read. Open it and save it as .docx "
                         "or PDF, then run this again.")
    raise SystemExit(f"Don't know how to read {ext or 'that'} files; use .docx, .pdf, "
                     "or .txt.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="the resume: .docx, .pdf, .txt, or .md")
    ap.add_argument("--out", help="write the text here instead of printing it")
    args = ap.parse_args()
    if not os.path.exists(args.path):
        raise SystemExit(f"No such file: {args.path}")
    text = extract(args.path).strip() + "\n"
    if len(text.strip()) < 50:
        print("warning: almost no text came out -- a scanned resume is an image, and "
              "needs its text pasted instead", file=sys.stderr)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {len(text.split())} words to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

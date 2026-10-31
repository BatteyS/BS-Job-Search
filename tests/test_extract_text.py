"""Pulling text out of a resume file for /setup."""

from __future__ import annotations

import zipfile

import pytest

from extract_text import extract

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def para(text: str, bullet: bool = False) -> str:
    num = ('<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
           if bullet else "")
    runs = "<w:tab/>".join(f"<w:t>{t}</w:t>" for t in text.split("\t"))
    return f"<w:p>{num}<w:r>{runs}</w:r></w:p>"


def make_docx(path, body: list[str], header: str | None = None) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{W}"><w:body>{"".join(body)}</w:body></w:document>')
        if header:
            z.writestr("word/header1.xml", f'<w:hdr xmlns:w="{W}">{para(header)}</w:hdr>')


def test_docx_keeps_the_header_bullets_and_tabs(tmp_path):
    path = tmp_path / "resume.docx"
    make_docx(path, [para("Acme\tJan 2022 – Present"), para("Led the rollout.", bullet=True)],
              header="Jordan Rivera")
    assert extract(str(path)).splitlines() == [
        "Jordan Rivera", "Acme\tJan 2022 – Present", "- Led the rollout."]


def test_text_passes_through(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text("Jordan Rivera\nNurse\n", encoding="utf-8")
    assert extract(str(path)) == "Jordan Rivera\nNurse\n"


@pytest.mark.parametrize("suffix, message", [(".doc", "save it as .docx"),
                                             (".pages", "Don't know how to read")])
def test_unreadable_formats_say_what_to_do(tmp_path, suffix, message):
    path = tmp_path / f"resume{suffix}"
    path.write_bytes(b"x")
    with pytest.raises(SystemExit, match=message):
        extract(str(path))

"""Fetching a posting: LinkedIn's page chrome must not pass for a description."""

from __future__ import annotations

import pytest

import fetch_posting

CHROME = "<nav>Sign in Join now</nav>" + "<p>Similar jobs: Project Engineer, Hayward</p>" * 200


def linkedin_page(description: str) -> str:
    return (f"<html><body>{CHROME}<section class=\"show-more-less-html\">"
            f"<div class=\"show-more-less-html__markup relative\">{description}</div>"
            f"</section>{CHROME}</body></html>")


class Page:
    def __init__(self, html: str, url: str):
        self.text, self.url, self.status_code, self.ok = html, url, 200, True


@pytest.fixture
def serve(monkeypatch):
    def serve(html: str, url: str = "https://www.linkedin.com/jobs/view/1"):
        monkeypatch.setattr(fetch_posting.requests, "get", lambda *a, **kw: Page(html, url))
    return serve


def test_a_blurb_only_linkedin_listing_is_too_short(serve):
    serve(linkedin_page("<p>At Acme Solar, our vision is a brighter grid.</p>"))
    text, meta, status = fetch_posting.fetch_description("https://www.linkedin.com/jobs/view/1")
    assert status == "short"
    assert meta["source"] == "linkedin" and "Similar jobs" not in text


def test_a_full_linkedin_listing_keeps_only_the_posting(serve):
    body = "<p>Own BESS projects from scoping to commissioning.</p>" * 40
    serve(linkedin_page(f"<div>{body}</div>"))
    text, _, status = fetch_posting.fetch_description("https://www.linkedin.com/jobs/view/1")
    assert status == "ok"
    assert "Own BESS projects" in text and "Similar jobs" not in text


def test_other_boards_still_fall_back_to_the_page(serve):
    serve("<html><body>" + "<p>Responsibilities and requirements.</p>" * 60 + "</body></html>",
          url="https://jobs.example.com/123")
    _, meta, status = fetch_posting.fetch_description("https://jobs.example.com/123")
    assert status == "ok" and meta["source"] == "page-text"

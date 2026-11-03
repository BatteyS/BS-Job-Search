"""A recruiter's posting for an unnamed employer is flagged, not taken for the employer."""

from __future__ import annotations

import pytest

from fetch_jobs import posted_by_recruiter


@pytest.mark.parametrize("opening", [
    "The Role: We're partnering with a well-funded direct air capture startup.",
    "Our client is a fast-growing battery storage developer in Oakland.",
    "On behalf of our client, we are hiring a Senior Project Engineer.",
    "A confidential client in the energy sector seeks a project engineer.",
])
def test_recruiter_openings_are_flagged(opening):
    assert posted_by_recruiter(opening + " Responsibilities follow.")


@pytest.mark.parametrize("text", [
    "Redwood Materials is deploying large-scale battery energy storage systems.",
    "As a consultant you will support our clients across utilities and industry.",
    "You will work with our client teams on interconnection studies.",
    "",
])
def test_employer_postings_are_not(text):
    assert not posted_by_recruiter(text)


def test_only_the_opening_is_read():
    late = "About us. " + "We build storage. " * 60 + "We're working with a utility on a pilot."
    assert not posted_by_recruiter(late)

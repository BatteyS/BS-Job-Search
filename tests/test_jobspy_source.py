"""Scraped boards: a board that refuses or keeps failing is dropped for the run."""

from __future__ import annotations

import logging

import pytest

import jobspy_source

TASKS = [(term, "bay_area", "San Francisco, CA") for term in ("a", "b", "c", "d")]


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(jobspy_source.time, "sleep", lambda seconds: None)


def board_logging(message: str):
    """A stand-in for JobSpy that logs `message` as an error and finds nothing."""
    calls = []

    def scrape_jobs(**kw):
        calls.append(kw["search_term"])
        logging.getLogger("jobspy.glassdoor").error(message)
        return None
    return scrape_jobs, calls


def test_a_board_that_keeps_failing_is_stopped():
    scrape_jobs, calls = board_logging("Glassdoor: location not parsed")
    rows, status = jobspy_source._board("glassdoor", scrape_jobs, TASKS, 336, 30, 1, False)
    assert rows == []
    assert len(calls) == jobspy_source.ERRORS_BEFORE_STOP
    assert "stopped after" in status and "location not parsed" in status


def test_a_refusing_board_gets_one_cool_off_then_stops():
    scrape_jobs, calls = board_logging("Glassdoor response status code 403")
    _, status = jobspy_source._board("glassdoor", scrape_jobs, TASKS, 336, 30, 1, False)
    assert calls == ["a", "a"]
    assert "refused requests" in status

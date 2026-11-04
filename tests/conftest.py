"""The scripts import each other by module name, as each puts scripts/ on its
own path. pytest loads this file first, so every test can do the same in any
order.

No test reads the user's own profile/applications.yaml: each one starts with
the tracker pointed at an empty folder, and a test that wants a tracker points
it at its own."""

import os
import sys

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


@pytest.fixture(autouse=True)
def no_real_tracker(tmp_path_factory, monkeypatch):
    import tracker
    monkeypatch.setattr(tracker, "ROOT", str(tmp_path_factory.mktemp("no-tracker")))

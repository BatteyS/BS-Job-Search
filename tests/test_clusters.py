"""Title matching: the presets, and the example profiles' patterns."""

from __future__ import annotations

import re

import pytest
import yaml

from helpers import example, run
from fetch_jobs import PRESETS, ClusterMatcher, preset_patterns

NURSE = [
    ("Registered Nurse - CVICU", {"cardiac-critical-care"}),
    ("Registered Nurse (ICU)", {"cardiac-critical-care"}),
    ("Charge Nurse - Progressive Care Unit", {"cardiac-critical-care"}),
    ("Clinical Informatics Nurse", {"clinical-informatics"}),
    ("Nurse (Informatics)", {"clinical-informatics"}),
    ("Epic Clinical Analyst - ClinDoc", {"clinical-informatics"}),
    ("Clinical Nurse Educator - Critical Care", {"nurse-educator", "cardiac-critical-care"}),
    ("Nurse Residency Program Coordinator", {"nurse-educator"}),
    ("Travel RN - ICU", set()),
    ("Per Diem RN - CVICU", set()),
    ("LVN - Telemetry", set()),
    ("Patient Care Technician - Telemetry", set()),
    ("Nurse Practitioner - Cardiology", set()),
    ("Director of Nursing - Critical Care", set()),
    ("Epic Analyst - Beaker", set()),
]
MARKETER = [
    ("Director of Product Marketing", {"product-marketing"}),
    ("Product Marketing Manager, Sales Enablement", {"product-marketing"}),
    ("Principal PMM, Analytics", {"product-marketing"}),
    ("Director, Go-To-Market Strategy", {"gtm-strategy"}),
    ("Competitive Intelligence Manager", {"gtm-strategy"}),
    ("VP, Product Marketing", set()),
    ("MBA Full-Time Hire - Product Marketing", set()),
    ("Data Engineer, GTM", set()),
    ("Demand Generation Manager", set()),
    ("Account Executive, Enterprise", set()),
]


def test_every_preset_compiles():
    lib = yaml.safe_load(open(PRESETS, encoding="utf-8"))
    names = [k for k, v in lib.items() if isinstance(v, dict)]
    for name, pattern in preset_patterns(names):
        re.compile(pattern, re.I)


def test_an_unknown_preset_stops_the_run():
    with pytest.raises(SystemExit, match="unknown title preset"):
        preset_patterns(["no_such_preset"])


@pytest.mark.parametrize("name, cases", [("nurse-sacramento", NURSE),
                                         ("product-marketer-chicago", MARKETER)])
def test_example_titles(name, cases):
    cfg = yaml.safe_load(open(example(name, "clusters.yaml"), encoding="utf-8"))
    matcher = ClusterMatcher(cfg)
    ids = {c["id"] for c in cfg["clusters"]}
    wrong = [(t, sorted(matcher.match(t, ids))) for t, want in cases
             if set(matcher.match(t, ids)) != want]
    assert not wrong, wrong


def test_try_titles_explains_a_drop():
    code, out = run("try_titles", "--clusters-file", example("nurse-sacramento", "clusters.yaml"),
                    "Travel RN - ICU", "Registered Nurse - CVICU")
    assert code == 0, out
    assert "dropped from cardiac-critical-care (global:" in out
    assert "kept by cardiac-critical-care" in out

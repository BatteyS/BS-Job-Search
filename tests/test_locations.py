"""Checks on presets/metros.yaml and the location filter that reads it.

    python tests/test_locations.py

Every check builds its profile from the library itself, so nothing here reads
a user's files or the network. The cases in test_cases are real location
strings from job boards, each one a way the filter has gone wrong before.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import adzuna_source  # noqa: E402
import scan_config  # noqa: E402
from fetch_jobs import LocationResolver, load_places  # noqa: E402

LIB = load_places()
METROS = LIB["metros"]
AMBIGUOUS = {c.lower() for c in LIB["ambiguous_cities"]}
REMOTE = (None, True)


def names(metro: dict) -> list[str]:
    return [c.lower() for c in (metro.get("cities") or []) + (metro.get("regions") or [])]


def resolver(only=None, mode="include") -> LocationResolver:
    return LocationResolver({"metros": METROS, "remote": {"penalty": -6}},
                            only_metros=only, mode=mode)


def where(r: LocationResolver, raw: str):
    got = r.resolve(raw)
    return got[:2] if got else None


def check(failures: list[str]) -> None:
    assert not failures, f"{len(failures)} failed:\n  " + "\n  ".join(failures)


def test_metro_fields():
    bad = []
    for key, m in METROS.items():
        states = m.get("states") or []
        if not states or set(states) - set(scan_config.STATE_NAMES):
            bad.append(f"{key}: states {states}")
        cities = m.get("cities") or []
        if not cities or any(c != c.lower() for c in cities):
            bad.append(f"{key}: cities must be present and lowercase")
        for place in scan_config._places(m):
            if where(resolver(only={key}), place) != (key, False):
                bad.append(f"{key}: search_as {place!r} is not inside the metro")
    check(bad)


def test_shared_names_are_ambiguous():
    seen: dict[str, list[str]] = {}
    for key, m in METROS.items():
        for n in set(names(m)):
            seen.setdefault(n, []).append(key)
    check([f"{n!r} is in {', '.join(ks)} but not ambiguous_cities"
           for n, ks in sorted(seen.items()) if len(ks) > 1 and n not in AMBIGUOUS])


def test_each_city_resolves_to_its_metro():
    """'City, ST' finds its own metro, and no other metro claims it."""
    bad = []
    for key, m in METROS.items():
        own, rest = resolver(only={key}), resolver(only=set(METROS) - {key})
        st = m["states"][0]
        for n in names(m):
            raw = f"{n}, {st}"
            if where(own, raw) != (key, False):
                bad.append(f"{raw!r} -> {where(own, raw)}, not {key}")
            other = where(rest, raw)
            if other and n not in names(METROS[other[0]]):
                bad.append(f"{raw!r} is claimed by {other[0]} as well as {key}")
    check(bad)


def test_bare_names():
    """A name alone resolves only when nothing else could be meant by it."""
    r, bad = resolver(), []
    for key, m in METROS.items():
        for n in names(m):
            got = where(r, n)
            if n in AMBIGUOUS:
                if got is not None:
                    bad.append(f"{n!r} alone -> {got}; it needs a state")
            elif got is None and not r.foreign(n):
                bad.append(f"{n!r} alone -> nothing")
            elif got and n not in names(METROS[got[0]]):
                bad.append(f"{n!r} alone -> {got[0]}")
    check(bad)


CASES = [
    # Non-US markers are whole words, and a US state beside one wins.
    ("Remote - Indiana", REMOTE),
    ("Remote - Indianapolis, Indiana", ("indianapolis", True)),
    ("Remote - New Mexico", REMOTE),
    ("Remote - New England", REMOTE),
    ("Vancouver, WA, US", ("portland", False)),
    ("Vancouver, Washington", ("portland", False)),
    ("Vancouver, BC", None),
    ("Vancouver", None),
    # A state code that is also a country's code proves nothing.
    ("Toronto, CA", None),
    ("Toronto, ON, CA", None),
    ("Berlin, DE", None),
    ("Pune, MH, IN", None),
    ("Remote - Tel Aviv, IL", None),
    # Several places: the US ones decide.
    ("New York | Toronto", ("new_york", False)),
    ("London, UK; San Francisco, CA", ("bay_area", False)),
    ("San Francisco | Toronto | New York | Montreal | Seattle", ("bay_area", False)),
    ("Toronto, Ontario - Remote; Atlanta, GA - Hybrid", ("atlanta", False)),
    ("Barcelona; Dublin; London", None),
    # Remote beside a non-US place is remote there, unless the US is named.
    ("Remote", REMOTE),
    ("Remote (US or Canada)", REMOTE),
    ("Remote - Canada", None),
    ("Remote | London", None),
    ("London, UK | Remote (UK)", None),
    ("Remote | United States | Poland | United Kingdom", REMOTE),
    ("Remote - EMEA", None),
    ("Remote (Europe)", None),
    # A city's own state must fit its metro.
    ("Carson City, NV", None),
    ("Lexington-Kentucky-United States of America", None),
    ("Glendale Heights, IL, US, Remote", REMOTE),
    ("Portland, ME", None),
    ("Portland", ("portland", False)),
    ("Manhattan Beach, Los Angeles County, CA", ("los_angeles", False)),
    # Ambiguous names need a state; spelled out counts.
    ("Dublin", None),
    ("Dublin, Ireland", None),
    ("Dublin, CA, US, 94568", ("bay_area", False)),
    ("Dublin-Ohio-United States of America", ("columbus", False)),
    ("Cambridge", None),
    ("Cambridge, England", None),
    ("Cambridge, MA", ("boston", False)),
    ("Burlington-Massachusetts-United States of America", ("boston", False)),
    ("Burlington, Middlesex County, MA", ("boston", False)),
    ("West Concord, Middlesex County, MA", None),
    ("Glendale, AZ", ("phoenix", False)),
    ("Glendale, CA", ("los_angeles", False)),
    ("Glendale", None),
    ("Arlington, VA", ("washington_dc", False)),
    ("Arlington, TX", ("dallas", False)),
    ("Arlington", None),
    # The District is a city, Washington a state.
    ("Washington, DC", ("washington_dc", False)),
    ("Washington, D.C.", ("washington_dc", False)),
    ("Seattle, Washington", ("seattle", False)),
    ("Boston, Lincolnshire, United Kingdom", None),
    ("San Jose, Costa Rica", None),
    ("Kansas City, KS", ("kansas_city", False)),
]


def test_cases():
    r = resolver()
    check([f"{raw!r} -> {where(r, raw)}, expected {want}"
           for raw, want in CASES if where(r, raw) != want])


def test_longer_names_win():
    """A city inside a longer known name is not a match, even when the
    profile's metros do not include the longer one."""
    check([f"{raw!r} with only {only} -> {where(resolver(only={only}), raw)}"
           for raw, only in [("Costa Mesa", "phoenix"), ("St. Louis Park", "st_louis"),
                             ("Upper Arlington, OH", "dallas"),
                             ("Saratoga Springs", "bay_area"),
                             ("Golden Valley", "colorado")]
           if where(resolver(only={only}), raw) is not None])


def test_remote_modes():
    raw = "Toronto, Ontario - Remote; New York, NY"
    assert where(resolver(mode="exclude"), raw) == ("new_york", False)
    assert where(resolver(mode="only"), raw) is None
    assert where(resolver(mode="exclude"), "Remote - US") is None
    assert where(resolver(mode="only"), "Remote - US") == REMOTE


def test_adzuna_adds_the_state():
    r = {"id": "1", "title": "Nurse", "company": {"display_name": "Clinic"},
         "location": {"display_name": "Burlington, Middlesex County",
                      "area": ["US", "Massachusetts", "Middlesex County", "Burlington"]}}
    j = adzuna_source.to_job(r, "Boston, MA")
    assert j.location_raw == "Burlington, Middlesex County, MA", j.location_raw
    r["location"].pop("area")
    assert adzuna_source.to_job(r, "Boston, MA").location_raw == "Burlington, Middlesex County"


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok      {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAILED  {name}: {e}")
    print(f"\n{len(tests) - failed} of {len(tests)} passed")
    raise SystemExit(1 if failed else 0)

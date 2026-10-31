"""Scanner settings shared by fetch_jobs.py and the aggregator sources.

Which places to search and which words to search for are profile data, not
code. Each aggregator source used to carry its own copy of both -- the same
seven metros hard-coded three times, and for USAJOBS its own term list -- so a
profile naming a different city, or a cluster added after the code was written,
quietly got no aggregator results at all. The aggregators are where breadth
comes from (Adzuna surfaced 163 employers on the 2026-08-17 scan against 21 from
the company boards), so that failure emptied a digest without saying why.

Everything a source needs to plan its queries now comes from
profile/filters.yaml and profile/clusters.yaml, through the helpers below.
"""

from __future__ import annotations

import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLUSTERS_YAML = os.path.join(ROOT, "profile/clusters.yaml")
FILTERS_YAML = os.path.join(ROOT, "profile/filters.yaml")

REMOTE_MODES = ("include", "exclude", "only")

# Not a metro. Remote work has no place to search around, so a search for it is
# planned under this key and each source turns it into its own nationwide
# remote query. What comes back still passes the location filter like anything
# else.
NATIONWIDE = "nationwide"

# Postal code -> name. The scan is US only, and sources write a state either
# way: "Boston, MA", "Boston, Massachusetts", or not at all.
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}
# Lowercase name -> code.
STATE_CODES = {name.lower(): code for code, name in STATE_NAMES.items()}


def load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def remote_mode(filters: dict, override: str | None = None) -> str:
    """How remote postings are treated: `include` keeps them beside metro
    roles (with the remote penalty), `exclude` drops them, `only` keeps
    nothing else. filters.yaml sets it; --remote overrides it for one run."""
    mode = override or (filters.get("remote") or {}).get("mode") or "include"
    mode = str(mode).strip().lower()
    if mode not in REMOTE_MODES:
        raise SystemExit(
            f"remote mode must be one of {', '.join(REMOTE_MODES)}, not {mode!r}")
    return mode


def metro_keys(filters: dict, only=None) -> list[str]:
    """The metros in play: every one in filters.yaml, or the subset --metros
    names. An unknown name stops the run rather than matching nothing."""
    keys = list(filters.get("metros") or {})
    if only:
        unknown = sorted(set(only) - set(keys))
        if unknown:
            raise SystemExit(f"unknown metro(s): {', '.join(unknown)}\n"
                             f"available: {', '.join(keys)}")
        keys = [k for k in keys if k in set(only)]
    return keys


def _places(metro: dict) -> list[str]:
    raw = (metro or {}).get("search_as")
    places = [raw] if isinstance(raw, str) else list(raw or [])
    return [str(p).strip() for p in places if str(p).strip()]


def search_locations(filters: dict, only=None,
                     mode: str | None = None) -> dict[str, list[str]]:
    """Metro key -> the place names aggregator queries use for it.

    A metro's `search_as` is one place name ("San Francisco, CA") or a list of
    them, for a metro too spread out for one search radius to cover. A metro
    with none cannot be searched by an aggregator; see unsearchable_metros().

    `remote.mode: only` plans a single nationwide remote search instead of the
    metros. `remote.search_nationwide: true` adds that search beside the metros
    in `include` mode.
    """
    mode = remote_mode(filters, mode)
    metros = filters.get("metros") or {}
    out: dict[str, list[str]] = {}
    if mode != "only":
        for k in metro_keys(filters, only):
            places = _places(metros.get(k))
            if places:
                out[k] = places
    nationwide = (filters.get("remote") or {}).get("search_nationwide")
    if mode == "only" or (mode == "include" and nationwide):
        out[NATIONWIDE] = [NATIONWIDE]
    return out


def unsearchable_metros(filters: dict, only=None,
                        mode: str | None = None) -> list[str]:
    """Metros in play that no aggregator can query, for lack of `search_as`.

    The company boards still cover them, but the aggregators reach most of the
    market, so this is reported rather than skipped silently.
    """
    if remote_mode(filters, mode) == "only":
        return []
    metros = filters.get("metros") or {}
    return [k for k in metro_keys(filters, only) if not _places(metros.get(k))]


def cluster_terms(clusters_cfg: dict, key: str = "search_terms") -> dict[str, list[str]]:
    """Cluster id -> its retrieval vocabulary for one kind of source.

    `search_terms` feeds Adzuna and Indeed. USAJOBS reads `usajobs_terms`,
    because federal postings are titled by occupational series and only broad
    single words match them -- see usajobs_source.py.
    """
    return {c["id"]: [str(t).strip() for t in (c.get(key) or []) if str(t).strip()]
            for c in clusters_cfg.get("clusters") or []}


def plan_queries(clusters, terms: dict[str, list[str]],
                 locations: dict[str, list[str]]) -> list[tuple[str, str, str]]:
    """Every (term, metro key, place) to query, each issued once.

    Clusters share vocabulary -- three of six used "energy" for USAJOBS, which
    sent that request three times per metro -- so repeats collapse here.
    """
    plan: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for c in sorted(clusters):
        for term in terms.get(c, []):
            for mkey in sorted(locations):
                for place in locations[mkey]:
                    if (term, place) in seen:
                        continue
                    seen.add((term, place))
                    plan.append((term, mkey, place))
    return plan


def missing_terms(clusters, terms: dict[str, list[str]]) -> list[str]:
    """Active clusters with no vocabulary for a source, so that source asks
    nothing on their behalf."""
    return sorted(c for c in clusters if not terms.get(c))

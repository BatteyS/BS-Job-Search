"""Check job titles against the role clusters, offline.

    python scripts/try_titles.py "Registered Nurse - CVICU" "Travel RN - ICU"
    python scripts/try_titles.py --file titles.txt
    python scripts/try_titles.py --clusters-file examples/nurse-sacramento/clusters.yaml "Nurse Educator"

For each title it prints the clusters that keep it, the pattern that drops it,
or that no cluster's include pattern matches -- the same rules a scan applies.
Nothing is fetched, so a pattern can be tried as many times as it takes. Then
`fetch_jobs.py --preview` shows the patterns against what is actually posted in
your metros.

Write the titles both ways: ones the cluster should keep, and near misses it
should drop. A pattern tested only on titles it should keep will keep too much.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_config  # noqa: E402
from fetch_jobs import ClusterMatcher  # noqa: E402


def verdict(why: dict[str, tuple[str, str] | None]) -> str:
    kept = [c for c, w in why.items() if w is None]
    dropped = [f"{c} ({w[0]}: {w[1]})" for c, w in why.items() if w is not None]
    if not why:
        return "no cluster's include pattern matches"
    parts = []
    if kept:
        parts.append("kept by " + ", ".join(kept))
    if dropped:
        parts.append("dropped from " + "; ".join(dropped))
    return " | ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("titles", nargs="*", help="job titles to check")
    ap.add_argument("--file", help="a file of titles, one per line")
    ap.add_argument("--clusters-file", default=scan_config.CLUSTERS_YAML)
    ap.add_argument("--clusters", help="comma-separated cluster ids (default: all)")
    args = ap.parse_args()

    titles = list(args.titles)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            titles += [t.strip() for t in fh if t.strip() and not t.startswith("#")]
    if not titles:
        raise SystemExit("give some titles, or --file with one per line")

    cfg = scan_config.load_yaml(args.clusters_file)
    ids = [c["id"] for c in cfg.get("clusters") or []]
    active = ({c.strip() for c in args.clusters.split(",") if c.strip()}
              if args.clusters else set(ids))
    unknown = sorted(active - set(ids))
    if unknown:
        raise SystemExit(f"unknown cluster(s): {', '.join(unknown)}\n"
                         f"available: {', '.join(ids)}")

    matcher = ClusterMatcher(cfg)
    width = min(max(len(t) for t in titles), 60)
    kept = 0
    for t in titles:
        why = matcher.explain(t, active)
        kept += any(w is None for w in why.values())
        print(f"  {t:<{width}}  {verdict(why)}")
    print(f"\n{kept} of {len(titles)} kept", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

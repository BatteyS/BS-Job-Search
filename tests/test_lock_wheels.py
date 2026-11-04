"""Every package uv.lock installs has a ready-built wheel for each kind of
machine the page runs on, so nobody's install has to compile anything.

A package without a wheel for a machine is built from source there, which can
need compilers the machine lacks: on 2026-11-03 cryptography 49 stopped
shipping wheels for Intel Macs, and a new user's first start failed asking for
Rust and OpenSSL (pyproject.toml's constraint-dependencies holds Intel Macs back
since). This reads only uv.lock, offline, and walks it the way uv would on each
machine: the project's dependencies, its extras and test group, and each
package's own, following every marker.

The machines: macOS 13 (Claude Code's floor) on Intel and on Apple silicon,
Linux on x86_64 with glibc 2.28, and 64-bit Windows, under the CPython that
.python-version names.
"""

from __future__ import annotations

import collections
import os
import tomllib

import pytest
from packaging.markers import Marker
from packaging.tags import compatible_tags, cpython_tags, mac_platforms
from packaging.utils import parse_wheel_filename

from helpers import ROOT

with open(os.path.join(ROOT, ".python-version"), encoding="utf-8") as fh:
    PY = tuple(int(x) for x in fh.read().strip().split(".")[:2])
FULL = f"{PY[0]}.{PY[1]}.99"


def _env(sys_platform: str, machine: str, system: str, os_name: str) -> dict:
    return {"sys_platform": sys_platform, "platform_machine": machine,
            "platform_system": system, "os_name": os_name,
            "python_version": f"{PY[0]}.{PY[1]}", "python_full_version": FULL,
            "implementation_name": "cpython", "platform_python_implementation": "CPython",
            "implementation_version": FULL, "platform_release": "", "platform_version": "",
            "extra": ""}


LINUX = [f"manylinux_2_{m}_x86_64" for m in range(28, 4, -1)] + [
    "manylinux2014_x86_64", "manylinux2010_x86_64", "manylinux1_x86_64", "linux_x86_64"]

MACHINES = {
    "macOS 13, Intel": (_env("darwin", "x86_64", "Darwin", "posix"),
                        list(mac_platforms((13, 0), "x86_64"))),
    "macOS 13, Apple silicon": (_env("darwin", "arm64", "Darwin", "posix"),
                                list(mac_platforms((13, 0), "arm64"))),
    "Linux x86_64": (_env("linux", "x86_64", "Linux", "posix"), LINUX),
    "Windows x64": (_env("win32", "AMD64", "Windows", "nt"), ["win_amd64"]),
}


def _lock() -> dict:
    with open(os.path.join(ROOT, "uv.lock"), "rb") as fh:
        return tomllib.load(fh)


def installed(lock: dict, env: dict) -> list[dict]:
    """The packages uv would install on a machine with this environment."""
    by_name = collections.defaultdict(list)
    for p in lock["package"]:
        by_name[p["name"]].append(p)
    root = next(p for p in lock["package"] if p.get("source", {}).get("virtual") == ".")
    edges = list(root.get("dependencies", []))
    for group in ("optional-dependencies", "dev-dependencies"):
        for deps in root.get(group, {}).values():
            edges += deps
    seen: dict[tuple[str, str], dict] = {}
    while edges:
        edge = edges.pop()
        if "marker" in edge and not Marker(edge["marker"]).evaluate(env):
            continue
        candidates = by_name[edge["name"]]
        if "version" in edge:
            candidates = [p for p in candidates if p["version"] == edge["version"]]
        assert len(candidates) == 1, f"uv.lock names {edge['name']} ambiguously: {edge}"
        pkg = candidates[0]
        key = (pkg["name"], pkg["version"])
        extras = edge.get("extra", [])
        if key not in seen:
            seen[key] = pkg
            edges += pkg.get("dependencies", [])
        for extra in extras:
            edges += pkg.get("optional-dependencies", {}).get(extra, [])
    return list(seen.values())


@pytest.mark.parametrize("machine", MACHINES)
def test_every_package_has_a_wheel(machine):
    env, platforms = MACHINES[machine]
    tags = set(cpython_tags(PY, platforms=platforms)) | set(
        compatible_tags(PY, f"cp{PY[0]}{PY[1]}", platforms=platforms))
    lock = _lock()
    packages = installed(lock, env)
    assert len(packages) > 20, "the walk found too little of uv.lock to mean anything"
    missing = []
    for pkg in packages:
        wheels = [parse_wheel_filename(w["url"].rsplit("/", 1)[-1])[3] for w in pkg.get("wheels", [])]
        if not any(t & tags for t in wheels):
            missing.append(f"{pkg['name']} {pkg['version']}")
    assert not missing, (f"no wheel for {machine}, Python {PY[0]}.{PY[1]}, so these would be built "
                         f"from source there: {', '.join(missing)}")


def test_intel_macs_stay_on_a_cryptography_with_wheels():
    """The case that broke a first install: Intel Macs get cryptography 48."""
    for machine, major in (("macOS 13, Intel", 48), ("macOS 13, Apple silicon", None)):
        got = [p for p in installed(_lock(), MACHINES[machine][0]) if p["name"] == "cryptography"]
        assert len(got) == 1
        if major:
            assert int(got[0]["version"].split(".")[0]) == major

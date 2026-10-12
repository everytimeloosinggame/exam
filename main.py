#!/usr/bin/env python3
"""Check pinned packages in a requirements file against PyPI.

Usage: python check_requirements.py [requirements.txt]
"""
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PYPI_URL = "https://pypi.org/pypi/{}/json"

# name, optional [extras], optional operator + version
LINE_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(===|==|~=|!=|>=|<=|>|<)?\s*([^\s;,#]+)?"
)


def parse_requirements(path):
    """Return a list of (name, operator, version) tuples."""
    entries = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split(" #")[0].strip()
            # skip blanks, comments, options (-r, -e, --index-url) and URLs
            if not line or line.startswith(("#", "-")) or "://" in line:
                continue
            match = LINE_RE.match(line)
            if match:
                entries.append(match.groups())
    return entries


def fetch_package(name):
    """Return PyPI JSON for a package, or None if it doesn't exist."""
    req = urllib.request.Request(PYPI_URL.format(name), headers={"User-Agent": "req-checker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def release_date(data, version):
    """Earliest upload time among the release's files, or None."""
    files = data["releases"].get(version) or []
    times = [f["upload_time_iso_8601"] for f in files if f.get("upload_time_iso_8601")]
    return min(times) if times else None


def check(entry):
    name, op, version = entry
    try:
        data = fetch_package(name)
    except Exception as e:  # network problems etc.
        return {"name": name, "version": version, "status": "error", "detail": str(e)}
    if data is None:
        return {"name": name, "version": version, "status": "missing_package"}
    if op in ("==", "===") and version:
        if version not in data["releases"]:
            return {"name": name, "version": version, "status": "missing_version"}
        return {"name": name, "version": version, "status": "ok",
                "date": release_date(data, version)}
    return {"name": name, "version": version, "status": "unpinned"}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "requirements.txt"
    entries = parse_requirements(path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, entries))

    missing_pkgs = [r for r in results if r["status"] == "missing_package"]
    missing_vers = [r for r in results if r["status"] == "missing_version"]
    errors = [r for r in results if r["status"] == "error"]
    valid = [r for r in results if r["status"] == "ok" and r.get("date")]

    # for r in missing_pkgs:
    #     print(f"Package not found on PyPI: {r['name']}")
    # for r in missing_vers:
    #     print(f"Package found but not the mentioned version: {r['name']}=={r['version']}")
    for r in errors:
        print(f"Could not check {r['name']}: {r['detail']}")

    print(f"Dependencies checked: {len(entries)}")
    print(f"Packages not on PyPI: {len(missing_pkgs)}")
    print(f"Versions not on PyPI: {len(missing_vers)}")

    if valid:
        oldest = min(valid, key=lambda r: r["date"])
        print(f"Oldest pinned release: {oldest['name']}=={oldest['version']} ({oldest['date'][:4]}).")
    else:
        print("Oldest pinned release: none (no valid pinned packages)")


if __name__ == "__main__":
    main()
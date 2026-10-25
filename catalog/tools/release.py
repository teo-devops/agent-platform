"""Release tools: from a commit log to the next version and its notes.

Pure functions over text, following Conventional Commits
(https://www.conventionalcommits.org) and Semantic Versioning (https://semver.org).
Deciding a version is arithmetic, not judgement: the model calls these instead
of guessing, and explains what they return.
"""

from __future__ import annotations

import re

_COMMIT = re.compile(r"^(?P<type>[a-z]+)(\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s*(?P<subject>.+)$")
_SEMVER = re.compile(r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")

#: Commit types that ship something users can notice, in the order notes list them.
SECTIONS = {"feat": "features", "fix": "fixes", "perf": "fixes"}


def parse_commits(log: str) -> dict:
    """Groups a commit log, one commit subject per line, by Conventional Commits type.

    Args:
        log: Commit subjects separated by newlines, e.g. "feat(api): add pagination".
            Lines starting with "BREAKING CHANGE:" mark the commit above them as breaking.

    Returns:
        A dict with lists 'breaking', 'features', 'fixes' and 'other' (each item has
        'scope' and 'subject'), and 'unparsed' for lines that do not follow the convention.
    """
    groups: dict[str, list] = {"breaking": [], "features": [], "fixes": [], "other": [], "unparsed": []}
    last: dict | None = None

    for line in (raw.strip().lstrip("-* ").strip() for raw in log.splitlines()):
        if not line:
            continue
        if line.upper().startswith("BREAKING CHANGE:"):
            if last is not None and last not in groups["breaking"]:
                groups["breaking"].append(last)
            continue
        match = _COMMIT.match(line)
        if not match:
            groups["unparsed"].append(line)
            last = None
            continue
        last = {"scope": match["scope"] or "", "subject": match["subject"].strip()}
        groups[SECTIONS.get(match["type"], "other")].append(last)
        if match["breaking"]:
            groups["breaking"].append(last)

    return groups


def next_version(current: str, log: str) -> dict:
    """Computes the next semantic version from the current one and a commit log.

    A breaking change bumps the major version (the minor one while still on 0.x),
    a feature the minor one, and anything else the patch.

    Args:
        current: The version released last, e.g. "1.4.2" or "v1.4.2".
        log: Commit subjects since that release, one per line.

    Returns:
        A dict with 'current', 'next', the 'bump' applied ("major", "minor",
        "patch" or "none") and the 'reason', or an 'error' if the version is not semver.
    """
    match = _SEMVER.match(current.strip())
    if not match:
        return {"error": f"'{current}' is not a semantic version like 1.4.2"}
    major, minor, patch = (int(match[k]) for k in ("major", "minor", "patch"))
    groups = parse_commits(log)

    if groups["breaking"]:
        bump, reason = ("minor", "breaking change while on 0.x") if major == 0 else ("major", "breaking change")
    elif groups["features"]:
        bump, reason = "minor", "new features"
    elif groups["fixes"] or groups["other"]:
        bump, reason = "patch", "fixes or maintenance only"
    else:
        return {"current": current, "next": current, "bump": "none", "reason": "no commits to release"}

    if bump == "major":
        version = f"{major + 1}.0.0"
    elif bump == "minor":
        version = f"{major}.{minor + 1}.0"
    else:
        version = f"{major}.{minor}.{patch + 1}"
    return {"current": current, "next": version, "bump": bump, "reason": reason}

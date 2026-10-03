"""Prepare local release files from reviewed Unreleased notes; never commit, tag, or push."""

import argparse
import re
import shutil
import subprocess
import tomllib
from datetime import date
from pathlib import Path

from scripts.release_notes import TAG_PATTERN, changelog_notes, validate_release

TOOL_PATHS = (
    "integrations/openwebui/craft_wrapper_tool.py",
    "integrations/openwebui/craft_documents_tool.py",
)
RELEASE_PATHS = (
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    *TOOL_PATHS,
    "CHANGELOG.md",
    "README.md",
    "PROJECT.md",
)


def replace_once(text: str, old: str, new: str, path: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Expected exactly one release version field in {path}")
    return text.replace(old, new, 1)


def promote_notes(text: str, version: str, release_date: date) -> str:
    headings = list(re.finditer(r"(?m)^## (.+)$", text))
    if not headings or headings[0][1] != "Unreleased":
        raise ValueError("Add a top-level ## Unreleased section with reviewed release notes")
    if sum(heading[1] == "Unreleased" for heading in headings) != 1:
        raise ValueError("Expected exactly one Unreleased section")
    if re.search(rf"(?m)^## {re.escape(version)}(?:\s|$)", text):
        raise ValueError("Changelog already contains the requested release version")
    end = headings[1].start() if len(headings) > 1 else len(text)
    notes = text[headings[0].end() : end].strip()
    if not notes:
        raise ValueError(
            "Unreleased notes must not be empty; review them before preparing a release"
        )
    result = (
        text[: headings[0].start()]
        + "## Unreleased\n\n"
        + f"## {version} — {release_date.isoformat()}\n\n{notes}\n\n"
        + text[end:]
    )
    changelog_notes(result, version)
    return result


def prepare_release(
    repo: Path, version: str, release_date: date, *, dry_run: bool = False
) -> list[str]:
    if re.fullmatch(TAG_PATTERN, "v" + version) is None:
        raise ValueError("Version must be MAJOR.MINOR.PATCH without leading zeroes or a v prefix")
    original = {path: (repo / path).read_text() for path in RELEASE_PATHS}
    current = tomllib.loads(original["pyproject.toml"])["project"]["version"]
    if re.fullmatch(TAG_PATTERN, "v" + current) is None:
        raise ValueError("Current package version must be MAJOR.MINOR.PATCH")
    if tuple(map(int, version.split("."))) <= tuple(map(int, current.split("."))):
        raise ValueError("Requested version must be greater than the current package version")
    validate_release(current, original.__getitem__, TOOL_PATHS)
    tag = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/tags/v" + version],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if tag.returncode == 0:
        raise ValueError("Requested release tag already exists; existing tags are never changed")
    if tag.returncode != 1:
        raise ValueError("Could not check release tags; run inside a Git checkout")

    updated = dict(original)
    updated["pyproject.toml"] = replace_once(
        original["pyproject.toml"],
        f'version = "{current}"',
        f'version = "{version}"',
        "pyproject.toml",
    )
    updated["Dockerfile"] = replace_once(
        original["Dockerfile"],
        f'org.opencontainers.image.version="{current}"',
        f'org.opencontainers.image.version="{version}"',
        "Dockerfile",
    )
    for path in TOOL_PATHS:
        updated[path] = replace_once(
            original[path], f"version: {current}\n", f"version: {version}\n", path
        )
    updated["CHANGELOG.md"] = promote_notes(original["CHANGELOG.md"], version, release_date)
    for path in ("README.md", "PROJECT.md"):
        updated[path] = replace_once(
            original[path],
            f"The current release version is **{current}**",
            f"The current release version is **{version}**",
            path,
        )
    if dry_run:
        return list(RELEASE_PATHS)
    if shutil.which("uv") is None:
        raise ValueError("uv is required to update the lockfile and installed package metadata")

    stage = "updating release files"
    try:
        for path, content in updated.items():
            if content != original[path]:
                (repo / path).write_text(content)
        for command in (["uv", "lock"], ["uv", "sync", "--locked", "--dev"]):
            stage = " ".join(command)
            result = subprocess.run(command, cwd=repo, capture_output=True, check=False)
            if result.returncode:
                raise ValueError("Release preparation command failed")
        stage = "validating prepared metadata"
        validate_release(version, lambda path: (repo / path).read_text(), TOOL_PATHS)
    except (OSError, ValueError, KeyboardInterrupt):
        for path, content in original.items():
            (repo / path).write_text(content)
        raise ValueError(
            f"Release preparation failed during {stage}; release files were restored. "
            "Run uv sync --locked --dev to reconcile the environment."
        ) from None
    return list(RELEASE_PATHS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Explicit release version, for example 0.4.0")
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
        help="Release date YYYY-MM-DD; defaults to the local calendar date",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and list files without changes"
    )
    args = parser.parse_args()
    try:
        paths = prepare_release(
            Path(__file__).resolve().parents[1], args.version, args.date, dry_run=args.dry_run
        )
    except (OSError, ValueError) as error:
        parser.exit(1, f"Release preparation error: {error}\n")
    print(("Would prepare " if args.dry_run else "Prepared ") + args.version + ":")
    for path in paths:
        print(f"  {path}")
    print("Review the diff and run the project checks, then commit, tag, and push separately.")


if __name__ == "__main__":
    main()

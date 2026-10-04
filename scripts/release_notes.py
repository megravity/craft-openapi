"""Validate a tagged release and extract its changelog notes without external dependencies."""

import argparse
import re
import subprocess
import tomllib
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

TAG_PATTERN = r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"


def tagged_file(repo: Path, tag: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"refs/tags/{tag}:{path}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"Release tag must exist and contain {path}")
    return result.stdout


def tagged_tool_paths(repo: Path, tag: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", f"refs/tags/{tag}", "integrations/openwebui"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("Release tag must exist")
    return result.stdout.splitlines()


def changelog_notes(changelog: str, version: str) -> str:
    headings = list(re.finditer(r"(?m)^## (.+)$", changelog))
    pattern = rf"{re.escape(version)} [—-] (\d{{4}}-\d{{2}}-\d{{2}})"
    matches = [i for i, heading in enumerate(headings) if re.fullmatch(pattern, heading[1])]
    if len(matches) != 1:
        raise ValueError("Changelog must contain exactly one dated entry for the release version")
    index = matches[0]
    heading = headings[index]
    match = re.fullmatch(pattern, heading[1])
    assert match is not None
    try:
        date.fromisoformat(match[1])
    except ValueError:
        raise ValueError("Changelog entry has an invalid calendar date") from None
    end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
    body = changelog[heading.end() : end].strip()
    if not body:
        raise ValueError("Changelog release notes must not be empty")
    return body + "\n"


def prepare_notes(tag: str, repo: Path = Path(".")) -> str:
    if re.fullmatch(TAG_PATTERN, tag) is None:
        raise ValueError("Release tags must be vMAJOR.MINOR.PATCH without leading zeroes")
    version = tag[1:]
    return validate_release(
        version, lambda path: tagged_file(repo, tag, path), tagged_tool_paths(repo, tag)
    )


def validate_release(
    version: str, read_file: Callable[[str], str], tool_paths: Iterable[str]
) -> str:
    """Validate matching release metadata in either a working tree or a tagged snapshot."""
    project = tomllib.loads(read_file("pyproject.toml"))
    if project.get("project", {}).get("version") != version:
        raise ValueError("Release version does not match the package version")
    lock = tomllib.loads(read_file("uv.lock"))
    package_versions = [
        package.get("version")
        for package in lock.get("package", [])
        if package.get("name") == "craft-openapi-wrapper"
    ]
    if package_versions != [version]:
        raise ValueError("Release lockfile does not match the package version")
    dockerfile = read_file("Dockerfile")
    if re.findall(r'^LABEL org\.opencontainers\.image\.version="([^"]+)"$', dockerfile, re.M) != [
        version
    ]:
        raise ValueError("Release Docker image label does not match the package version")
    present = set(tool_paths)
    recognized = {
        "integrations/openwebui/craft_wrapper_tool.py",
        "integrations/openwebui/craft_space_tool.py",
        "integrations/openwebui/craft_documents_tool.py",
        "integrations/openwebui/craft_daily_tool.py",
    }
    if not present.intersection(
        {
            "integrations/openwebui/craft_wrapper_tool.py",
            "integrations/openwebui/craft_space_tool.py",
        }
    ):
        raise ValueError("Release must contain a Space Open WebUI tool")
    paths = sorted(present & recognized)
    for path in paths:
        tool = read_file(path)
        header = re.match(r'\s*"""(.*?)"""', tool, re.S)
        if header is None or re.findall(r"^version: (\S+)$", header[1], re.M) != [version]:
            raise ValueError("Release Open WebUI tool version does not match the package version")
    return changelog_notes(read_file("CHANGELOG.md"), version)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        notes = prepare_notes(args.tag)
        args.output.write_text(notes)
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

import subprocess
import tomllib
from datetime import date
from pathlib import Path

import pytest

from scripts import prepare_release as release

RELEASE_DATE = date(2026, 10, 3)
NOTES = "- Reviewed fix.\n\n### Compatibility\n\n- Preserve existing API paths."
HISTORY = "## 0.3.0 — 2026-10-03\n\n- Previous capability.\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    files = {
        "pyproject.toml": '[project]\nname = "craft-openapi-wrapper"\nversion = "0.3.0"\n',
        "uv.lock": (
            '[[package]]\nname = "craft-openapi-wrapper"\nversion = "0.3.0"\n\n'
            '[[package]]\nname = "dependency"\nversion = "0.3.0"\n'
        ),
        "Dockerfile": 'LABEL org.opencontainers.image.version="0.3.0"\n',
        **dict.fromkeys(release.TOOL_PATHS, '"""\nversion: 0.3.0\n"""\n'),
        "CHANGELOG.md": f"# Changelog\n\n## Unreleased\n\n{NOTES}\n\n{HISTORY}",
        "README.md": (
            "The current release version is **0.3.0**, adding a capability.\nExample tag: v0.3.0\n"
        ),
        "PROJECT.md": "The current release version is **0.3.0**. Implemented capabilities.\n",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def snapshot(repo: Path) -> dict[str, str]:
    return {path: (repo / path).read_text() for path in release.RELEASE_PATHS}


@pytest.fixture
def commands(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    recorded: list[list[str]] = []

    def run(command: list[str], *, cwd: Path, **kwargs) -> subprocess.CompletedProcess[bytes]:
        recorded.append(command)
        if command == ["uv", "lock"]:
            version = tomllib.loads((cwd / "pyproject.toml").read_text())["project"]["version"]
            lock = (cwd / "uv.lock").read_text()
            (cwd / "uv.lock").write_text(
                lock.replace('version = "0.3.0"', f'version = "{version}"', 1)
            )
        return subprocess.CompletedProcess(command, 1 if command[0] == "git" else 0)

    monkeypatch.setattr(release.subprocess, "run", run)
    monkeypatch.setattr(release.shutil, "which", lambda command: "/example/uv")
    return recorded


def test_preparation_aligns_versions_and_preserves_notes(repo: Path, commands: list[list[str]]):
    paths = release.prepare_release(repo, "0.3.1", RELEASE_DATE)
    assert paths == list(release.RELEASE_PATHS)
    assert (
        release.validate_release(
            "0.3.1", lambda path: (repo / path).read_text(), release.TOOL_PATHS
        )
        == NOTES + "\n"
    )
    assert (repo / "CHANGELOG.md").read_text() == (
        f"# Changelog\n\n## Unreleased\n\n## 0.3.1 — 2026-10-03\n\n{NOTES}\n\n{HISTORY}"
    )
    assert (repo / "README.md").read_text() == (
        "The current release version is **0.3.1**, adding a capability.\nExample tag: v0.3.0\n"
    )
    assert tomllib.loads((repo / "uv.lock").read_text())["package"][1]["version"] == "0.3.0"
    assert commands == [
        ["git", "show-ref", "--verify", "--quiet", "refs/tags/v0.3.1"],
        ["uv", "lock"],
        ["uv", "sync", "--locked", "--dev"],
    ]


def test_dry_run_changes_nothing_and_does_not_require_uv(
    repo: Path, commands: list[list[str]], monkeypatch: pytest.MonkeyPatch
):
    before = snapshot(repo)
    monkeypatch.setattr(release.shutil, "which", lambda command: None)
    assert release.prepare_release(repo, "0.4.0", date(2026, 11, 1), dry_run=True) == list(
        release.RELEASE_PATHS
    )
    assert snapshot(repo) == before
    assert commands == [["git", "show-ref", "--verify", "--quiet", "refs/tags/v0.4.0"]]


@pytest.mark.parametrize(
    "version", ["v0.4.0", "0.04.0", "0.4", "0.4.0-rc.1", "0.3.0", "0.2.9", "0.3.0; command"]
)
def test_invalid_or_non_increasing_version_never_runs_commands(
    repo: Path, commands: list[list[str]], version: str
):
    before = snapshot(repo)
    with pytest.raises(ValueError, match="Version must|greater than"):
        release.prepare_release(repo, version, RELEASE_DATE)
    assert commands == []
    assert snapshot(repo) == before


@pytest.mark.parametrize("status,message", [(0, "tag already exists"), (128, "Git checkout")])
def test_tag_check_fails_before_changes(
    repo: Path, monkeypatch: pytest.MonkeyPatch, status: int, message: str
):
    before = snapshot(repo)
    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, status),
    )
    with pytest.raises(ValueError, match=message):
        release.prepare_release(repo, "0.4.0", RELEASE_DATE)
    assert snapshot(repo) == before


@pytest.mark.parametrize(
    "changelog,message",
    [
        (HISTORY, "Unreleased section"),
        ("## Unreleased\n\n" + HISTORY, "must not be empty"),
        (
            "## Unreleased\n\n- Fix\n\n## Unreleased\n\n- Other\n\n" + HISTORY,
            "exactly one Unreleased",
        ),
        (
            "## Unreleased\n\n- Fix\n\n## 0.4.0 — 2026-10-04\n\n- Already prepared\n\n" + HISTORY,
            "already contains",
        ),
    ],
)
def test_missing_or_ambiguous_notes_never_change_files(
    repo: Path, commands: list[list[str]], changelog: str, message: str
):
    (repo / "CHANGELOG.md").write_text(changelog)
    before = snapshot(repo)
    with pytest.raises(ValueError, match=message):
        release.prepare_release(repo, "0.4.0", RELEASE_DATE)
    assert snapshot(repo) == before
    assert all(command[0] == "git" for command in commands)


@pytest.mark.parametrize("path", ["uv.lock", "Dockerfile", *release.TOOL_PATHS])
def test_mismatched_current_metadata_never_changes_files(
    repo: Path, commands: list[list[str]], path: str
):
    file = repo / path
    file.write_text(file.read_text().replace("0.3.0", "0.2.0"))
    before = snapshot(repo)
    with pytest.raises(ValueError, match="version"):
        release.prepare_release(repo, "0.4.0", RELEASE_DATE)
    assert snapshot(repo) == before
    assert commands == []


def test_missing_uv_never_changes_files(
    repo: Path, commands: list[list[str]], monkeypatch: pytest.MonkeyPatch
):
    before = snapshot(repo)
    monkeypatch.setattr(release.shutil, "which", lambda command: None)
    with pytest.raises(ValueError, match="uv is required"):
        release.prepare_release(repo, "0.4.0", RELEASE_DATE)
    assert snapshot(repo) == before
    assert all(command[0] == "git" for command in commands)


@pytest.mark.parametrize(
    "content", ["Missing version reference", "The current release version is **0.3.0**\n" * 2]
)
def test_ambiguous_documentation_anchor_never_changes_files(
    repo: Path, commands: list[list[str]], content: str
):
    (repo / "README.md").write_text(content)
    before = snapshot(repo)
    with pytest.raises(ValueError, match="exactly one release version field in README"):
        release.prepare_release(repo, "0.4.0", RELEASE_DATE)
    assert snapshot(repo) == before
    assert all(command[0] == "git" for command in commands)


@pytest.mark.parametrize("failure", ["lock", "sync", "validation", "oserror", "interrupt"])
def test_failure_restores_all_release_files(
    repo: Path, commands: list[list[str]], monkeypatch: pytest.MonkeyPatch, failure: str
):
    original_run = release.subprocess.run

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess[bytes]:
        if command[0] == "uv":
            if failure == "oserror":
                raise OSError("Command failed with private diagnostic")
            if failure == "interrupt":
                raise KeyboardInterrupt
            if command[1] == failure:
                return subprocess.CompletedProcess(command, 1, stderr=b"Private diagnostic")
            if failure == "validation" and command[1] == "lock":
                return subprocess.CompletedProcess(command, 0)
        return original_run(command, **kwargs)

    monkeypatch.setattr(release.subprocess, "run", run)
    before = snapshot(repo)
    with pytest.raises(ValueError, match="files were restored.*uv sync") as error:
        release.prepare_release(repo, "0.4.0", RELEASE_DATE)
    assert "Private" not in str(error.value)
    assert snapshot(repo) == before


def test_custom_date_and_numeric_version_order(repo: Path, commands: list[list[str]]):
    release.prepare_release(repo, "0.10.0", date(2027, 1, 2))
    assert "## 0.10.0 — 2027-01-02" in (repo / "CHANGELOG.md").read_text()

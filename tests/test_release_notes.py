import importlib.util
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def release_module() -> Any:
    path = Path(__file__).parents[1] / "scripts/release_notes.py"
    spec = importlib.util.spec_from_file_location("release_notes_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release_files():
    return {
        "pyproject.toml": '[project]\nversion = "0.2.0"\n',
        "uv.lock": '[[package]]\nname = "craft-openapi-wrapper"\nversion = "0.2.0"\n',
        "Dockerfile": 'LABEL org.opencontainers.image.version="0.2.0"\n',
        "integrations/openwebui/craft_wrapper_tool.py": '"""\nversion: 0.2.0\n"""\n',
        "CHANGELOG.md": "# Changelog\n\n## 0.2.0 — 2026-10-02\n\n- Example capability.\n",
    }


def test_tagged_snapshot_used_instead_of_working_tree(release_module, release_files, tmp_path):
    env = {
        "PATH": os.defpath,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }

    def git(*arguments):
        return subprocess.run(
            ["git", *arguments], cwd=tmp_path, env=env, capture_output=True, check=True
        )

    git("init", "-q")
    for name, content in release_files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git("add", ".")
    git(
        "-c",
        "user.name=Example Contributor",
        "-c",
        "user.email=contributor@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "Example release",
    )
    git("tag", "v0.2.0")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.3.0"\n')
    (tmp_path / "CHANGELOG.md").write_text("New notes not part of the tag")
    assert release_module.prepare_notes("v0.2.0", tmp_path) == "- Example capability.\n"
    with pytest.raises(ValueError, match="tag must exist"):
        release_module.prepare_notes("v0.9.0", tmp_path)


@pytest.mark.parametrize(
    "tag",
    ["0.2.0", "v02.0.0", "v0.2", "v0.2.0-rc.1", "v1٠.2.3", "v0.2.0; command", "refs/heads/main"],
)
def test_invalid_tag_rejected_before_git(release_module, monkeypatch, tag):
    def unexpected(*args):
        pytest.fail("Invalid tags must not be passed to git")

    monkeypatch.setattr(release_module, "tagged_file", unexpected)
    with pytest.raises(ValueError, match="vMAJOR.MINOR.PATCH"):
        release_module.prepare_notes(tag)


@pytest.mark.parametrize(
    "path,content,error",
    [
        ("pyproject.toml", '[project]\nversion = "0.3.0"', "package version"),
        ("uv.lock", '[[package]]\nname = "craft-openapi-wrapper"\nversion = "0.3.0"', "lockfile"),
        ("uv.lock", "", "lockfile"),
        ("Dockerfile", 'LABEL org.opencontainers.image.version="0.3.0"', "Docker image"),
        ("integrations/openwebui/craft_wrapper_tool.py", '"""\nversion: 0.3.0\n"""', "Open WebUI"),
        ("integrations/openwebui/craft_wrapper_tool.py", "# no metadata", "Open WebUI"),
        ("CHANGELOG.md", "# Changelog", "exactly one dated entry"),
        ("CHANGELOG.md", "## 0.2.0 — 2026-10-02\n\n", "must not be empty"),
        ("CHANGELOG.md", "## 0.2.0 — 2026-02-30\n\n- Fix.", "invalid calendar date"),
        (
            "CHANGELOG.md",
            "## 0.2.0 — 2026-10-02\n- One\n## 0.2.0 — 2026-10-03\n- Two",
            "exactly one dated entry",
        ),
    ],
)
def test_incomplete_or_mismatched_release_rejected(
    release_module, release_files, monkeypatch, path, content, error
):
    release_files[path] = content
    monkeypatch.setattr(release_module, "tagged_tool_paths", lambda repo, tag: list(release_files))
    monkeypatch.setattr(release_module, "tagged_file", lambda repo, tag, name: release_files[name])
    with pytest.raises(ValueError, match=error):
        release_module.prepare_notes("v0.2.0")


def test_only_matching_release_notes_are_extracted(release_module):
    text = """# Changelog

## Unreleased

- Future work.

## 0.3.0 — 2026-10-03

- New feature.

## 0.2.0 — 2026-10-02

- Example capability.

### Details

- Keep subheadings.

## 0.1.0 — 2026-10-01

- Previous work.
"""
    assert release_module.changelog_notes(text, "0.2.0") == (
        "- Example capability.\n\n### Details\n\n- Keep subheadings.\n"
    )


@pytest.mark.parametrize("header", ['"""\nversion: 0.3.0\n"""', "# missing metadata"])
def test_documents_tool_version_validated_when_in_tag(
    release_module, release_files, monkeypatch, header
):
    release_files["integrations/openwebui/craft_documents_tool.py"] = header
    monkeypatch.setattr(release_module, "tagged_tool_paths", lambda repo, tag: list(release_files))
    monkeypatch.setattr(release_module, "tagged_file", lambda repo, tag, name: release_files[name])
    with pytest.raises(ValueError, match="Open WebUI"):
        release_module.prepare_notes("v0.2.0")


def test_matching_documents_tool_version(release_module, release_files, monkeypatch):
    release_files["integrations/openwebui/craft_documents_tool.py"] = '"""\nversion: 0.2.0\n"""'
    monkeypatch.setattr(release_module, "tagged_tool_paths", lambda repo, tag: list(release_files))
    monkeypatch.setattr(release_module, "tagged_file", lambda repo, tag, name: release_files[name])
    assert release_module.prepare_notes("v0.2.0") == "- Example capability.\n"


@pytest.mark.parametrize("space_name", ["craft_wrapper_tool.py", "craft_space_tool.py"])
@pytest.mark.parametrize(
    "extra_tools",
    [[], ["craft_documents_tool.py"], ["craft_documents_tool.py", "craft_daily_tool.py"]],
)
def test_historical_and_current_tool_layouts(
    release_module, release_files, monkeypatch, space_name, extra_tools
):
    header = release_files.pop("integrations/openwebui/craft_wrapper_tool.py")
    for name in [space_name, *extra_tools]:
        release_files["integrations/openwebui/" + name] = header
    monkeypatch.setattr(release_module, "tagged_tool_paths", lambda repo, tag: list(release_files))
    monkeypatch.setattr(release_module, "tagged_file", lambda repo, tag, name: release_files[name])
    assert release_module.prepare_notes("v0.2.0") == "- Example capability.\n"


@pytest.mark.parametrize(
    "filename",
    [
        "craft_wrapper_tool.py",
        "craft_space_tool.py",
        "craft_documents_tool.py",
        "craft_daily_tool.py",
    ],
)
def test_every_recognized_tool_present_must_match(
    release_module, release_files, monkeypatch, filename
):
    for name in ("craft_space_tool.py", "craft_documents_tool.py", "craft_daily_tool.py"):
        release_files["integrations/openwebui/" + name] = '"""\nversion: 0.2.0\n"""\n'
    release_files["integrations/openwebui/" + filename] = '"""\nversion: 0.3.0\n"""\n'
    monkeypatch.setattr(release_module, "tagged_tool_paths", lambda repo, tag: list(release_files))
    monkeypatch.setattr(release_module, "tagged_file", lambda repo, tag, name: release_files[name])
    with pytest.raises(ValueError, match="Open WebUI tool version"):
        release_module.prepare_notes("v0.2.0")


def test_missing_space_tool_rejected(release_module, release_files, monkeypatch):
    release_files.pop("integrations/openwebui/craft_wrapper_tool.py")
    monkeypatch.setattr(release_module, "tagged_tool_paths", lambda repo, tag: list(release_files))
    monkeypatch.setattr(release_module, "tagged_file", lambda repo, tag, name: release_files[name])
    with pytest.raises(ValueError, match="Space Open WebUI tool"):
        release_module.prepare_notes("v0.2.0")

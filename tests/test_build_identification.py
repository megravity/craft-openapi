import asyncio
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = Path(__file__).parents[1]
    repo = tmp_path / "checkout with spaces"
    (repo / "scripts").mkdir(parents=True)
    for name in ("build-id.sh", "export-tools.sh"):
        shutil.copy2(root / "scripts" / name, repo / "scripts" / name)
    for name in (".dockerignore", "Dockerfile", "pyproject.toml", "uv.lock"):
        shutil.copyfile(root / name, repo / name)
    shutil.copytree(root / "integrations/openwebui", repo / "integrations/openwebui")
    (repo / "src").mkdir()
    (repo / "src/example.py").write_text("VALUE = 1\n")
    return repo


def build_id(repo: Path, target: str) -> str:
    return subprocess.check_output(
        ["/bin/sh", str(repo / "scripts/build-id.sh"), target], text=True
    ).strip()


def test_identifiers_track_public_inputs_not_checkout_location_or_secrets(checkout, tmp_path):
    before = build_id(checkout, "wrapper")
    tool_before = build_id(checkout, "space")
    assert re.fullmatch(r"\d+\.\d+\.\d+-dev\.[0-9a-f]{12}", before)
    for name in (".env", ".openwebui-tools.env", "NATIVE_COLLECTION_INTEGRATION_PLAN.md"):
        (checkout / name).write_text("private data must not affect the build\n")
    assert build_id(checkout, "wrapper") == before
    assert build_id(checkout, "space") == tool_before
    relocated = tmp_path / "other checkout"
    shutil.copytree(checkout, relocated)
    assert build_id(relocated, "wrapper") == before
    (checkout / "src/example.py").write_text("VALUE = 2\n")
    assert build_id(checkout, "wrapper") != before
    assert build_id(checkout, "space") == tool_before
    source = checkout / "integrations/openwebui/craft_space_tool.py"
    source.write_text(source.read_text() + "\n# Changed tool source\n")
    assert build_id(checkout, "space") != tool_before


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_exported_tool_reports_version_without_changing_release_source(checkout, adapter):
    source = checkout / f"integrations/openwebui/craft_{adapter}_tool.py"
    original = source.read_bytes()
    subprocess.run(["/bin/sh", str(checkout / "scripts/export-tools.sh")], check=True)
    exported = checkout / f"build/openwebui/craft_{adapter}_tool.py"
    expected = build_id(checkout, adapter)
    assert f"version: {expected}\n" in exported.read_text()
    assert source.read_bytes() == original
    spec = importlib.util.spec_from_file_location(f"stamped_{adapter}", exported)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tool = module.Tools()

    async def capabilities(valves):
        return {"statusCode": 200, "response": {"profileId": "planner"}}

    tool._capabilities = capabilities
    result = asyncio.run(getattr(tool, f"craft_{adapter}_get_capabilities")())
    assert result["toolVersion"] == expected
    assert result["response"] == {"profileId": "planner"}

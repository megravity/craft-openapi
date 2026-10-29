import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def updater(tmp_path: Path):
    repo = tmp_path / "checkout with spaces"
    (repo / "scripts").mkdir(parents=True)
    script = repo / "scripts/update-tools.sh"
    shutil.copyfile(Path(__file__).parents[1] / "scripts/update-tools.sh", script)
    identity = repo / "scripts/build-id.sh"
    shutil.copyfile(Path(__file__).parents[1] / "scripts/build-id.sh", identity)
    identity.chmod(0o755)
    source = repo / "integrations/openwebui/craft_space_tool.py"
    source.parent.mkdir(parents=True)
    source.write_text('"""\nversion: 0.4.0\n"""\nclass Tools:\n    pass\n')
    (repo / ".openwebui-tools.env").write_text(
        "OWUI_URL=https://owui.example/prefix\nOWUI_API_TOKEN='synthetic-token-$(id)'\n"
        "OWUI_TIMEOUT_SECONDS=60\n"
    )
    before = {
        "id": "space_test",
        "name": "Custom test name",
        "content": "# previous source\n",
        "meta": {
            "description": "Custom description",
            "i18n": None,
            "manifest": {"version": "0.4.0"},
        },
        "write_access": True,
        "access_grants": [{"principal_id": "example-group", "permission": "read"}],
        "valves": {"WRAPPER_PROFILE": "planner"},
        "updated_at": 1,
    }
    state = tmp_path / "state.json"
    state.write_text(json.dumps(before))
    events = tmp_path / "events.jsonl"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
def flag(name): return args[args.index(name)+1]
method = flag('--request')
assert args[0] == '-q' and '--location' not in args
assert flag('--retry') == '0'
assert 'synthetic-token' not in str(args)
auth = Path(flag('--config')).read_text()
assert 'Authorization: Bearer ' + os.environ.get('OWUI_API_TOKEN', 'synthetic-token-$(id)') in auth
state = Path(os.environ['TASK_STATE'])
data = json.loads(state.read_text())
status = 200
payload = None
if not args[-1].startswith('https://owui.example/prefix/api/v1/tools/'):
    status = 404
elif args[-1].endswith('/id/missing'):
    status = 404
elif method == 'POST':
    payload = json.loads(Path(flag('--data-binary')[1:]).read_text())
    status = int(os.environ.get('TASK_STATUS', '200'))
    if status == 200:
        data.update(payload)
        version = next(
            line[9:] for line in payload['content'].splitlines() if line.startswith('version: ')
        )
        data['meta']['manifest'] = {{'version': version}}
        data['updated_at'] = 2
        state.write_text(json.dumps(data))
with Path(os.environ['TASK_EVENTS']).open('a') as f:
    f.write(json.dumps({{'method':method,'payload':payload}})+'\\n')
response = data
if args[-1].endswith('/tools/'):
    response = [{{'id':data['id'],'name':data['name'],'meta':data['meta']}}]
body = json.dumps(response) if status == 200 else 'private upstream error'
Path(flag('--output')).write_text(body)
print(status, end='')
""")
    curl.chmod(0o755)

    def run(*args: str, overrides: dict[str, str] | None = None):
        env = {key: value for key, value in os.environ.items() if not key.startswith("OWUI_")}
        env.update(
            {
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "TASK_STATE": str(state),
                "TASK_EVENTS": str(events),
            }
        )
        return subprocess.run(
            ["/bin/sh", str(script), *args],
            cwd=tmp_path,
            env=env | (overrides or {}),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    return run, before, state, events, source


def test_preview_update_preserves_configuration_and_skips_unchanged(updater):
    run, before, state, events, source = updater
    listing = run("--list")
    assert listing.returncode == 0
    assert json.loads(listing.stdout) == [
        {"id": "space_test", "name": "Custom test name", "version": "0.4.0"}
    ]
    preview = run("--tool", "space=space_test")
    assert preview.returncode == 0 and "would update" in preview.stdout
    assert json.loads(state.read_text()) == before
    applied = run("--tool", "space=space_test", "--apply")
    assert applied.returncode == 0 and "updated and verified" in applied.stdout
    saved = json.loads(state.read_text())
    fingerprint = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    stamped = source.read_text().replace("version: 0.4.0\n", f"version: 0.4.0-dev.{fingerprint}\n")
    assert saved["content"] == stamped
    assert f"0.4.0-dev.{fingerprint}" in applied.stdout
    assert "version: 0.4.0\n" in source.read_text()  # Tracked source stays release-compatible.
    assert saved["meta"]["manifest"]["version"] == f"0.4.0-dev.{fingerprint}"
    for key in ("description", "i18n"):
        assert saved["meta"][key] == before["meta"][key]
    for key in ("name", "access_grants", "valves"):
        assert saved[key] == before[key]
    assert json.loads(run("--list").stdout)[0]["version"] == f"0.4.0-dev.{fingerprint}"
    unchanged = run("--tool", "space=space_test", "--apply")
    assert unchanged.returncode == 0 and "unchanged" in unchanged.stdout
    calls = [json.loads(line) for line in events.read_text().splitlines()]
    posts = [call for call in calls if call["method"] == "POST"]
    assert len(posts) == 1
    assert set(posts[0]["payload"]) == {"id", "name", "content", "meta"}
    assert "synthetic-token" not in preview.stdout + applied.stdout + applied.stderr


def test_failed_save_is_not_retried_and_errors_are_sanitized(updater):
    run, before, state, events, _ = updater
    result = run("--tool", "space=space_test", "--apply", overrides={"TASK_STATUS": "400"})
    assert result.returncode == 1
    assert "HTTP 400" in result.stderr and "may have been applied" in result.stderr
    assert "private upstream error" not in result.stderr
    assert "synthetic-token" not in result.stderr
    assert json.loads(state.read_text()) == before
    calls = [json.loads(line) for line in events.read_text().splitlines()]
    assert sum(call["method"] == "POST" for call in calls) == 1


def test_all_targets_preflight_before_any_save(updater):
    run, before, state, events, _ = updater
    result = run("--tool", "space=space_test", "--tool", "space=missing", "--apply")
    assert result.returncode == 1 and "HTTP 404" in result.stderr
    assert json.loads(state.read_text()) == before
    assert all(json.loads(line)["method"] == "GET" for line in events.read_text().splitlines())


def test_environment_overrides_saved_credentials(updater):
    run, _, _, _, _ = updater
    result = run("--tool", "space=space_test", overrides={"OWUI_API_TOKEN": "override-token"})
    assert result.returncode == 0 and "would update" in result.stdout
    assert "override-token" not in result.stdout + result.stderr
    blank = run("--tool", "space=space_test", overrides={"OWUI_API_TOKEN": ""})
    assert blank.returncode == 1 and "Configure OWUI_API_TOKEN" in blank.stderr

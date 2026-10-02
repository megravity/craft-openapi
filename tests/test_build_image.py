import os
import shutil
import subprocess
from pathlib import Path

import pytest

WEBHOOK = "https://portainer.example.com/api/stacks/webhooks/example-secret"


@pytest.fixture
def build_script(tmp_path):
    repo = tmp_path / "repo with spaces"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "build-image.sh"
    shutil.copyfile(Path(__file__).parents[1] / "scripts/build-image.sh", script)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'printf "docker\\n" >> "$TASK_EVENTS"\n'
        'printf "%s\\n" "$@" > "$TASK_DOCKER_ARGS"\n'
        'exit "${TASK_BUILD_EXIT:-0}"\n'
    )
    curl = fake_bin / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        'printf "curl\\n" >> "$TASK_EVENTS"\n'
        'printf "%s\\n" "$@" > "$TASK_CURL_ARGS"\n'
        'cat > "$TASK_CURL_INPUT"\n'
        'printf "%s" "${TASK_HTTP_STATUS:-204}"\n'
        'exit "${TASK_CURL_EXIT:-0}"\n'
    )
    docker.chmod(0o755)
    curl.chmod(0o755)
    events = tmp_path / "events"
    docker_args = tmp_path / "docker_args"
    curl_args = tmp_path / "curl_args"
    curl_input = tmp_path / "curl_input"
    env = {
        "PATH": str(fake_bin) + os.pathsep + os.defpath,
        "TASK_EVENTS": str(events),
        "TASK_DOCKER_ARGS": str(docker_args),
        "TASK_CURL_ARGS": str(curl_args),
        "TASK_CURL_INPUT": str(curl_input),
    }

    def run(*arguments, overrides=None):
        return subprocess.run(
            ["/bin/sh", str(script), *arguments],
            cwd=tmp_path,
            env=env | (overrides or {}),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    return repo, run, events, docker_args, curl_args, curl_input


def test_build_only_without_webhook(build_script):
    repo, run, events, docker_args, curl_args, _ = build_script
    result = run()
    assert result.returncode == 0
    assert events.read_text().splitlines() == ["docker"]
    assert docker_args.read_text().splitlines() == [
        "build",
        "--tag",
        "craft-openapi-wrapper:local",
        str(repo),
    ]
    assert not curl_args.exists()


def test_successful_build_calls_webhook_once_without_pulling(build_script):
    repo, run, events, docker_args, curl_args, curl_input = build_script
    (repo / ".portainer-webhook").write_text(WEBHOOK + "\n")
    result = run("example-image:local")
    assert result.returncode == 0
    assert events.read_text().splitlines() == ["docker", "curl"]
    assert docker_args.read_text().splitlines()[2] == "example-image:local"
    assert curl_input.read_text() == f'url = "{WEBHOOK}?pullimage=false"\n'
    args = curl_args.read_text().splitlines()
    assert args == [
        "-q",
        "--config",
        "-",
        "--request",
        "POST",
        "--silent",
        "--output",
        "/dev/null",
        "--write-out",
        "%{http_code}",
        "--connect-timeout",
        "10",
        "--max-time",
        "60",
        "--proto",
        "=http,https",
        "--retry",
        "0",
        "--stderr",
        "/dev/null",
    ]
    assert WEBHOOK not in result.stdout + result.stderr + curl_args.read_text()
    assert "accepted" in result.stdout
    assert "completed" not in result.stdout


def test_build_failure_never_calls_webhook(build_script):
    _, run, events, _, curl_args, _ = build_script
    result = run(overrides={"PORTAINER_WEBHOOK_URL": WEBHOOK, "TASK_BUILD_EXIT": "17"})
    assert result.returncode == 17
    assert events.read_text().splitlines() == ["docker"]
    assert not curl_args.exists()
    assert "accepted" not in result.stdout


def test_exported_url_overrides_file_and_empty_export_disables_hook(build_script):
    repo, run, events, _, _, curl_input = build_script
    (repo / ".portainer-webhook").write_text(WEBHOOK)
    override = "http://other.example.com/api/stacks/webhooks/other-secret"
    result = run(overrides={"PORTAINER_WEBHOOK_URL": override})
    assert result.returncode == 0
    assert override in curl_input.read_text()
    events.unlink()
    result = run(overrides={"PORTAINER_WEBHOOK_URL": ""})
    assert result.returncode == 0
    assert events.read_text().splitlines() == ["docker"]


@pytest.mark.parametrize("status", ["200", "202", "204"])
def test_all_success_statuses_are_accepted(build_script, status):
    _, run, events, _, _, _ = build_script
    result = run(overrides={"PORTAINER_WEBHOOK_URL": WEBHOOK, "TASK_HTTP_STATUS": status})
    assert result.returncode == 0
    assert events.read_text().splitlines() == ["docker", "curl"]


@pytest.mark.parametrize("status", ["307", "400", "403", "409", "500"])
def test_redirects_and_http_errors_fail_without_retry(build_script, status):
    _, run, events, _, _, _ = build_script
    result = run(overrides={"PORTAINER_WEBHOOK_URL": WEBHOOK, "TASK_HTTP_STATUS": status})
    assert result.returncode == 1
    assert events.read_text().splitlines() == ["docker", "curl"]
    assert f"HTTP {status}" in result.stderr
    assert WEBHOOK not in result.stdout + result.stderr


def test_transport_failure_reports_image_built_and_uncertainty(build_script):
    _, run, events, _, _, _ = build_script
    result = run(overrides={"PORTAINER_WEBHOOK_URL": WEBHOOK, "TASK_CURL_EXIT": "28"})
    assert result.returncode == 1
    assert events.read_text().splitlines() == ["docker", "curl"]
    assert "Image built" in result.stderr
    assert "Check the stack before retrying" in result.stderr
    assert WEBHOOK not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "url",
    [
        "not a URL",
        "ftp://portainer.example.com/api/stacks/webhooks/example-secret",
        WEBHOOK + "?pullimage=true",
        WEBHOOK + "#fragment",
        WEBHOOK + '"\nverbose',
        WEBHOOK + "\\",
        "https://user:secret@portainer.example.com/api/stacks/webhooks/example-secret",
        "https://portainer.example.com/api/stacks/webhooks/",
        WEBHOOK + "\n" + WEBHOOK,
    ],
)
def test_invalid_url_rejected_before_build_without_exposing_it(build_script, url):
    _, run, events, _, _, _ = build_script
    result = run(overrides={"PORTAINER_WEBHOOK_URL": url})
    assert result.returncode == 2
    assert not events.exists()
    assert "example-secret" not in result.stdout + result.stderr


def test_empty_config_file_is_an_error(build_script):
    repo, run, events, _, _, _ = build_script
    (repo / ".portainer-webhook").write_text("")
    result = run()
    assert result.returncode == 2
    assert not events.exists()


def test_too_many_arguments_rejected_before_build(build_script):
    _, run, events, _, _, _ = build_script
    result = run("first", "second")
    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert not events.exists()

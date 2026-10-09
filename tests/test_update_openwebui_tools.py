import copy
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts import update_openwebui_tools as updater


@pytest.fixture
def sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    content = {
        adapter: f'"""version: 0.4.0"""\n# {adapter}\nclass Tools:\n    pass\n'
        for adapter in ("space", "documents", "daily")
    }
    paths = {}
    for adapter, source in content.items():
        path = tmp_path / f"craft_{adapter}_tool.py"
        path.write_text(source)
        paths[adapter] = path
    monkeypatch.setattr(updater, "TOOL_PATHS", paths)
    return content


def record(tool_id: str = "space_test", content: str = "# previous source\n") -> dict[str, Any]:
    return {
        "id": tool_id,
        "name": "Existing test tool",
        "content": content,
        "write_access": True,
        "user_id": "synthetic-owner",
        "meta": {
            "description": "Custom description",
            "i18n": {"en": {"name": "Custom name"}},
            "manifest": {"version": "previous"},
            "has_user_valves": False,
        },
        "access_grants": [
            {"principal_type": "group", "principal_id": "synthetic-group", "permission": "read"}
        ],
        "valves": {"WRAPPER_PROFILE": "planner", "WRAPPER_API_TOKEN": "synthetic-secret"},
        "specs": [{"name": "previous_function"}],
        "updated_at": 1,
        "created_at": 1,
    }


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_update_mapping_readback_and_preserved_configuration(adapter: str, sources: dict[str, str]):
    tool_id = f"{adapter}_test"
    state = record(tool_id)
    original = copy.deepcopy(state)
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-key"
        if request.method == "POST":
            assert request.url.path == f"/prefix/api/v1/tools/id/{tool_id}/update"
            body = json.loads(request.content)
            assert body == {
                "id": tool_id,
                "name": original["name"],
                "content": sources[adapter],
                "meta": original["meta"],
            }
            state.update(body)
            state["meta"] = {**body["meta"], "manifest": {"version": "0.4.0"}}
            state["updated_at"] = 2
        else:
            assert request.url.path == f"/prefix/api/v1/tools/id/{tool_id}"
        return httpx.Response(200, json=state)

    with httpx.Client(
        base_url=updater.base_url("https://owui.example/prefix/"),
        headers={"Authorization": "Bearer synthetic-key"},
        transport=httpx.MockTransport(respond),
    ) as client:
        plan = updater.plan_updates(client, [(adapter, tool_id)])[0]
        updater.apply_update(client, plan)
        assert not updater.plan_updates(client, [(adapter, tool_id)])[0].changed
    assert [request.method for request in requests] == ["GET", "GET", "POST", "GET", "GET"]
    assert state["valves"] == original["valves"]
    assert state["access_grants"] == original["access_grants"]
    assert state["name"] == original["name"]


@pytest.mark.parametrize("apply", [False, True])
def test_cli_preview_apply_and_unchanged_skip(
    apply: bool,
    sources: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    state = record()
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            state.update(json.loads(request.content))
        return httpx.Response(200, json=state)

    real_client = httpx.Client

    def client(**kwargs: Any) -> httpx.Client:
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return real_client(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(updater.httpx, "Client", client)
    monkeypatch.setenv("OWUI_URL", "https://owui.example")
    monkeypatch.setenv("OWUI_API_TOKEN", "synthetic-key")
    for name in ("httpx", "httpcore"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", False)
    args = ["--tool", "space=space_test", "--apply" if apply else "--dry-run"]
    assert updater.main(args) == 0
    output = capsys.readouterr().out
    assert ("updated and verified" if apply else "would update") in output
    assert "synthetic-secret" not in output
    assert "# previous source" not in output
    assert sum(request.method == "POST" for request in requests) == int(apply)
    if apply:
        assert updater.main(args) == 0
        assert "unchanged" in capsys.readouterr().out
        assert sum(request.method == "POST" for request in requests) == 1


def test_default_cli_is_preview_and_list_escapes_names(
    sources: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/tools/"):
            return httpx.Response(200, json=[{"id": "space_test", "name": "Name\x1b[2J"}])
        return httpx.Response(200, json=record())

    real_client = httpx.Client
    monkeypatch.setattr(
        updater.httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    monkeypatch.setenv("OWUI_URL", "https://owui.example")
    monkeypatch.setenv("OWUI_API_TOKEN", "synthetic-key")
    assert updater.main(["--tool", "space=space_test"]) == 0
    assert "Preview only" in capsys.readouterr().out
    assert updater.main(["--list"]) == 0
    output = capsys.readouterr().out
    assert "\\u001b" in output and "\x1b" not in output
    assert all(request.method == "GET" for request in requests)


@pytest.mark.parametrize(
    "invalid",
    [
        {"content": None},
        {"write_access": False},
        {"write_access": None},
        {"id": "wrong"},
        {"meta": None},
        {"name": None},
        {"access_grants": None},
    ],
)
def test_preflight_fails_closed(invalid: dict[str, Any], sources: dict[str, str]):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={**record(), **invalid})

    with httpx.Client(
        base_url="https://owui.example/", transport=httpx.MockTransport(respond)
    ) as c:
        with pytest.raises(updater.UpdateError):
            updater.plan_updates(c, [("space", "space_test")])
    assert [request.method for request in requests] == ["GET"]


def test_all_targets_preflight_before_any_update(sources: dict[str, str]):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/daily_missing"):
            return httpx.Response(404, json={"detail": "private response"})
        return httpx.Response(200, json=record())

    with httpx.Client(
        base_url="https://owui.example/", transport=httpx.MockTransport(respond)
    ) as c:
        with pytest.raises(updater.UpdateError, match="HTTP 404"):
            updater.plan_updates(c, [("space", "space_test"), ("daily", "daily_missing")])
    assert [request.method for request in requests] == ["GET", "GET"]


def test_concurrent_edit_stops_before_post(sources: dict[str, str]):
    reads = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal reads
        assert request.method == "GET"
        reads += 1
        return httpx.Response(200, json={**record(), "updated_at": reads})

    with httpx.Client(
        base_url="https://owui.example/", transport=httpx.MockTransport(respond)
    ) as c:
        plan = updater.plan_updates(c, [("space", "space_test")])[0]
        with pytest.raises(updater.UpdateError, match="changed since preflight"):
            updater.apply_update(c, plan)
    assert reads == 2


@pytest.mark.parametrize("failure", ["timeout", "http", "json", "wrong_source", "sharing"])
def test_post_or_verification_failure_never_retries(failure: str, sources: dict[str, str]):
    requests = []
    state = record()

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic-secret private-url", request=request)
            if failure == "http":
                return httpx.Response(400, text="synthetic-secret private-url")
            if failure == "json":
                return httpx.Response(200, text="synthetic-secret private-url")
            state.update(json.loads(request.content))
            if failure == "wrong_source":
                state["content"] = "# different source"
            if failure == "sharing":
                state["access_grants"] = []
        return httpx.Response(200, json=state)

    with httpx.Client(
        base_url="https://owui.example/", transport=httpx.MockTransport(respond)
    ) as c:
        plan = updater.plan_updates(c, [("space", "space_test")])[0]
        with pytest.raises(updater.UpdateError, match="may have been applied") as caught:
            updater.apply_update(c, plan)
    assert "synthetic-secret" not in str(caught.value)
    assert "private-url" not in str(caught.value)
    assert sum(request.method == "POST" for request in requests) == 1


def test_redirect_not_followed_and_response_limit(monkeypatch: pytest.MonkeyPatch):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://other.example/"})

    with httpx.Client(
        base_url="https://owui.example/", transport=httpx.MockTransport(respond)
    ) as c:
        with pytest.raises(updater.UpdateError, match="HTTP 302"):
            updater.request_json(c, "GET", "id/space_test")
    assert len(requests) == 1
    monkeypatch.setattr(updater, "MAX_RESPONSE_BYTES", 8)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="x" * 9))
    ) as c:
        with pytest.raises(updater.UpdateError, match="exceeded"):
            updater.request_json(c, "GET", "https://owui.example/")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ftp://owui.example",
        "https://user:secret@owui.example",
        "https://@owui.example",
        "https://:secret@owui.example",
        "https://owui.example?secret=x",
        "https://owui.example#fragment",
        "https://owui.example:bad",
        "https://owui.example\n",
    ],
)
def test_invalid_base_urls_are_sanitized(value: str):
    with pytest.raises(updater.UpdateError) as caught:
        updater.base_url(value)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("value", ["space", "bad=tool", "space=../tool", "space=Upper", "daily="])
def test_invalid_selection(value: str):
    with pytest.raises(updater.argparse.ArgumentTypeError):
        updater.tool_selection(value)


def test_duplicate_ids_and_invalid_python_make_no_requests(sources: dict[str, str]):
    def unexpected(_: httpx.Request) -> httpx.Response:
        pytest.fail("No request expected")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as c:
        with pytest.raises(updater.UpdateError, match="only once"):
            updater.plan_updates(c, [("space", "same"), ("daily", "same")])
        updater.TOOL_PATHS["space"].write_text("def invalid(:")
        with pytest.raises(updater.UpdateError, match="invalid Python"):
            updater.plan_updates(c, [("space", "space_test")])


def test_valid_source_is_never_executed_locally(sources: dict[str, str]):
    updater.TOOL_PATHS["space"].write_text('raise RuntimeError("Must not execute")\n')
    with httpx.Client(
        base_url="https://owui.example/",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=record())),
    ) as c:
        assert updater.plan_updates(c, [("space", "space_test")])[0].changed


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "not-a-number"])
def test_cli_invalid_timeout_is_sanitized(
    timeout: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("OWUI_URL", "https://owui.example")
    monkeypatch.setenv("OWUI_API_TOKEN", "synthetic-key")
    monkeypatch.setenv("OWUI_TIMEOUT_SECONDS", timeout)
    assert updater.main(["--list"]) == 1
    assert "positive and finite" in capsys.readouterr().err


def test_batch_stops_after_first_failed_save(sources: dict[str, str]):
    states = {tool_id: record(tool_id) for tool_id in ("space_test", "daily_test", "daily_other")}
    posted = []

    def respond(request: httpx.Request) -> httpx.Response:
        tool_id = request.url.path.split("/")[-1 if request.method == "GET" else -2]
        if request.method == "POST":
            posted.append(tool_id)
            if tool_id == "daily_test":
                return httpx.Response(500, text="private response")
            states[tool_id].update(json.loads(request.content))
        return httpx.Response(200, json=states[tool_id])

    with httpx.Client(
        base_url="https://owui.example/", transport=httpx.MockTransport(respond)
    ) as c:
        plans = updater.plan_updates(
            c, [("space", "space_test"), ("daily", "daily_test"), ("daily", "daily_other")]
        )
        with pytest.raises(updater.UpdateError, match="daily_test: .*may have been applied"):
            for plan in plans:
                updater.apply_update(c, plan)
    assert posted == ["space_test", "daily_test"]
    assert states["space_test"]["content"] == sources["space"]
    assert states["daily_other"]["content"] == "# previous source\n"


@pytest.mark.parametrize("token", ["", "Bearer synthetic-key", "bad\nkey", "nonascii-\u00e9"])
def test_cli_rejects_invalid_credentials_without_echoing(
    token: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("OWUI_URL", "https://owui.example")
    monkeypatch.setenv("OWUI_API_TOKEN", token)
    assert updater.main(["--list"]) == 1
    message = capsys.readouterr().err
    assert "Set OWUI_API_TOKEN" in message
    assert "synthetic-key" not in message
    assert "nonascii" not in message

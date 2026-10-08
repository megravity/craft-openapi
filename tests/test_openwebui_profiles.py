import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest


@pytest.fixture(params=["space", "documents", "daily"])
def tool_context(request, monkeypatch):
    adapter = request.param
    path = Path(__file__).parents[1] / "integrations" / "openwebui" / f"craft_{adapter}_tool.py"
    spec = importlib.util.spec_from_file_location(f"profile_tool_{adapter}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tool = module.Tools()
    tool.valves.WRAPPER_URL = "http://wrapper.test"
    tool.valves.WRAPPER_API_TOKEN = "profile-tool-fixture-token"
    original = httpx.AsyncClient
    calls = []

    def connect(handler):
        def wrapped(request):
            calls.append(request)
            return handler(request)

        monkeypatch.setattr(
            module.httpx,
            "AsyncClient",
            lambda **kwargs: original(transport=httpx.MockTransport(wrapped), **kwargs),
        )

    return adapter, module, tool, calls, connect


@pytest.mark.parametrize("kind", ["collection", "block"])
@pytest.mark.parametrize("answer", [True, False, None, {"error": "disconnected"}, 1])
def test_delete_dialogs_fail_closed_and_show_exact_target(tool_context, kind, answer):
    adapter, module, tool, calls, connect = tool_context

    def handler(request):
        if request.method == "GET":
            assert request.headers["authorization"] == "Bearer profile-tool-fixture-token"
            if kind == "collection":
                return httpx.Response(
                    200, json={"items": [{"id": "row/?", "title": "Example row"}]}
                )
            return httpx.Response(
                200, json={"id": "text/?", "type": "text", "markdown": "Example text"}
            )
        assert request.method == "DELETE"
        return httpx.Response(200, json={"id": "row/?" if kind == "collection" else "text/?"})

    connect(handler)
    events = []

    async def confirm(event):
        events.append(event)
        assert event["type"] == "confirmation"
        assert ("all nested item content" if kind == "collection" else "leaf text block") in event[
            "data"
        ]["message"]
        assert (
            "row/?" in event["data"]["message"]
            if kind == "collection"
            else "text/?" in event["data"]["message"]
        )
        assert "profile-tool-fixture-token" not in json.dumps(event)
        return answer

    method = getattr(
        tool, f"craft_{adapter}_delete_" + ("collection_item" if kind == "collection" else "block")
    )
    args = (
        ("collection", "row/?")
        if kind == "collection"
        else ("text/?", {"date": "today"} if adapter == "daily" else {"documentId": "root"})
    )
    statuses = []

    async def emit(event):
        statuses.append(event)

    result = asyncio.run(method(*args, __event_call__=confirm, __event_emitter__=emit))
    assert len(events) == 1
    assert [r.method for r in calls] == (["GET", "DELETE"] if answer is True else ["GET"])
    if answer is True:
        assert result["statusCode"] == 200
        assert statuses == []
    else:
        assert result["response"]["error"]["outcomeUnknown"] is False
        assert result["response"]["error"]["code"] == (
            "tool_confirmation_declined"
            if answer is False
            else "tool_confirmation_invalid_response"
        )
        assert result["statusCode"] is None and result["requestId"] is None
        assert len(statuses) == 1
        assert statuses[0]["type"] == "status"
        assert statuses[0]["data"]["description"].startswith("Nothing deleted.")
        assert statuses[0]["data"]["done"] is True
        assert statuses[0]["data"]["hidden"] is False
        assert "Do not automatically retry" in statuses[0]["data"]["description"]


def test_missing_callback_and_unreadable_preview_never_delete(tool_context):
    adapter, module, tool, calls, connect = tool_context
    connect(lambda request: httpx.Response(404, json={"error": {"code": "not_found"}}))
    method = getattr(tool, f"craft_{adapter}_delete_collection_item")
    statuses = []

    async def emit(event):
        statuses.append(event)

    result = asyncio.run(method("c", "row", __event_emitter__=emit))
    assert result["response"]["error"]["code"] == "tool_confirmation_required"
    assert statuses[-1]["data"]["description"].startswith("Nothing deleted.")
    assert calls == []

    async def confirm(event):
        pytest.fail("Unreadable targets must not prompt")

    result = asyncio.run(method("c", "row", __event_call__=confirm, __event_emitter__=emit))
    assert result["response"]["error"]["code"] == "tool_preview_unavailable"
    assert len(statuses) == 2
    assert "Could not read" in statuses[-1]["data"]["description"]
    assert [r.method for r in calls] == ["GET"]


def test_confirmation_timeout_never_deletes(tool_context, monkeypatch):
    adapter, module, tool, calls, connect = tool_context
    monkeypatch.setattr(module, "CONFIRMATION_TIMEOUT_SECONDS", 0.001)
    connect(
        lambda request: httpx.Response(200, json={"items": [{"id": "row", "title": "Example"}]})
    )

    async def confirm(event):
        await asyncio.sleep(0.1)
        return True

    statuses = []

    async def emit(event):
        statuses.append(event)

    result = asyncio.run(
        getattr(tool, f"craft_{adapter}_delete_collection_item")(
            "c", "row", __event_call__=confirm, __event_emitter__=emit
        )
    )
    assert result["response"]["error"]["code"] == "tool_confirmation_unavailable"
    assert "timed out" in statuses[0]["data"]["description"]
    assert [r.method for r in calls] == ["GET"]


def test_confirmation_exception_reports_safe_failure(tool_context):
    adapter, module, tool, calls, connect = tool_context
    connect(
        lambda request: httpx.Response(200, json={"items": [{"id": "row", "title": "Example"}]})
    )
    statuses = []

    async def confirm(event):
        raise RuntimeError("private-callback-value")

    async def emit(event):
        statuses.append(event)

    result = asyncio.run(
        getattr(tool, f"craft_{adapter}_delete_collection_item")(
            "c", "row", __event_call__=confirm, __event_emitter__=emit
        )
    )
    assert result["response"]["error"]["code"] == "tool_confirmation_unavailable"
    assert "Confirmation failed" in statuses[0]["data"]["description"]
    assert "private-callback-value" not in json.dumps([result, statuses])
    assert [r.method for r in calls] == ["GET"]


@pytest.mark.parametrize("failure", ["exception", "timeout"])
def test_status_delivery_failure_preserves_cancellation(tool_context, monkeypatch, failure):
    adapter, module, tool, calls, connect = tool_context
    monkeypatch.setattr(module, "UI_EVENT_TIMEOUT_SECONDS", 0.001)
    connect(
        lambda request: httpx.Response(200, json={"items": [{"id": "row", "title": "Example"}]})
    )

    async def confirm(event):
        return False

    async def emit(event):
        if failure == "timeout":
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("Unavailable UI")

    result = asyncio.run(
        getattr(tool, f"craft_{adapter}_delete_collection_item")(
            "c", "row", __event_call__=confirm, __event_emitter__=emit
        )
    )
    assert result["response"]["error"]["code"] == "tool_confirmation_declined"
    assert result["response"]["error"]["outcomeUnknown"] is False
    assert [r.method for r in calls] == ["GET"]


def test_daily_task_deletion_emits_cancellation_status(tool_context):
    adapter, module, tool, calls, connect = tool_context
    if adapter != "daily":
        return
    connect(
        lambda request: httpx.Response(
            200, json={"id": "task", "type": "text", "markdown": "Example task"}
        )
    )
    statuses = []

    async def confirm(event):
        return False

    async def emit(event):
        statuses.append(event)

    result = asyncio.run(
        tool.craft_daily_delete_task("task", __event_call__=confirm, __event_emitter__=emit)
    )
    assert result["response"]["error"]["code"] == "tool_confirmation_declined"
    assert statuses[0]["data"]["description"].startswith("Nothing deleted.")
    assert [r.method for r in calls] == ["GET"]


@pytest.mark.parametrize("failure", ["denied", "network", "malformed", "wrong-profile", "expired"])
def test_profile_capability_failures_do_not_fall_back_or_mutate(tool_context, failure):
    adapter, module, tool, calls, connect = tool_context
    tool.valves.WRAPPER_PROFILE = "planner"

    def handler(request):
        assert request.url.path == "/profiles/planner/capabilities"
        if failure == "network":
            raise httpx.ConnectError("private error", request=request)
        if failure == "expired":
            return httpx.Response(403, json={"error": {"code": "profile_expired"}})
        operations = (
            []
            if failure == "denied"
            else None
            if failure == "malformed"
            else [f"craft_{adapter}_add_collection_item"]
        )
        return httpx.Response(
            200,
            json={
                "profileId": "migration" if failure == "wrong-profile" else "planner",
                "operations": operations,
            },
        )

    connect(handler)
    result = asyncio.run(
        getattr(tool, f"craft_{adapter}_add_collection_item")("c", {"title": "Example"})
    )
    assert result["statusCode"] != 201
    assert len(calls) == 1 and calls[0].method == "GET"


def test_profile_and_request_are_captured_before_confirmation(tool_context):
    adapter, module, tool, calls, connect = tool_context
    tool.valves.WRAPPER_PROFILE = "planner"

    def handler(request):
        assert request.url.host == "wrapper.test"
        assert request.headers["authorization"] == "Bearer profile-tool-fixture-token"
        assert request.url.path.startswith("/profiles/planner/")
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(
                200, json={"profileId": "planner", "operations": [f"craft_{adapter}_delete_block"]}
            )
        if request.method == "GET":
            return httpx.Response(200, json={"id": "text", "type": "text", "markdown": "Original"})
        assert dict(request.url.params) == (
            {"date": "today"} if adapter == "daily" else {"documentId": "root"}
        )
        return httpx.Response(200, json={"id": "text"})

    connect(handler)
    parameters = {"date": "today"} if adapter == "daily" else {"documentId": "root"}

    async def confirm(event):
        parameters.clear()
        parameters["documentId"] = "foreign"
        tool.valves.WRAPPER_PROFILE = "migration"
        tool.valves.WRAPPER_URL = "http://other.test"
        tool.valves.WRAPPER_API_TOKEN = "other-fixture-token"
        return True

    result = asyncio.run(
        getattr(tool, f"craft_{adapter}_delete_block")("text", parameters, __event_call__=confirm)
    )
    assert result["statusCode"] == 200
    assert [r.method for r in calls] == ["GET", "GET", "DELETE"]


def test_capability_discovery_and_document_context_forwarding(tool_context):
    adapter, module, tool, calls, connect = tool_context
    tool.valves.WRAPPER_PROFILE = "planner"
    op = f"craft_{adapter}_update_block_markdown"

    def handler(request):
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(
                200,
                json={
                    "profileId": "planner",
                    "operations": [op],
                    "writeTargets": {"space": {"documentIds": ["root"]}},
                },
            )
        assert request.url.path == f"/profiles/planner/v1/{adapter}/blocks/text"
        assert dict(request.url.params) == (
            {"date": "today"} if adapter == "daily" else {"documentId": "root"}
        )
        assert json.loads(request.content) == {"markdown": "Updated"}
        return httpx.Response(200, json={"id": "text", "type": "text", "markdown": "Updated"})

    connect(handler)
    result = asyncio.run(getattr(tool, f"craft_{adapter}_get_capabilities")())
    assert result["response"]["operations"] == [op]
    result = asyncio.run(
        getattr(tool, op)(
            "text",
            {"markdown": "Updated"},
            parameters={"date": "today"} if adapter == "daily" else {"documentId": "root"},
        )
    )
    assert result["statusCode"] == 200
    assert [r.method for r in calls] == ["GET", "GET", "PATCH"]


@pytest.mark.parametrize("tool_context", ["space"], indirect=True)
def test_reviewed_copy_workflow_keeps_sources_and_checks_existing_ids(tool_context, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from craft_wrapper.config import Settings
    from craft_wrapper.main import create_app

    adapter, module, tool, calls, connect = tool_context
    source_tasks = [
        {
            "id": "existing-source",
            "markdown": "Already copied",
            "taskInfo": {"state": "todo"},
            "location": {"type": "document", "documentId": "project"},
        },
        {
            "id": "new-source",
            "markdown": "Backlog task",
            "taskInfo": {"state": "todo"},
            "location": {"type": "document", "documentId": "project"},
        },
    ]
    original_sources = json.dumps(source_tasks, sort_keys=True)
    rows = [
        {
            "id": "existing-row",
            "title": "Already copied",
            "properties": {"source_task_id": "existing-source"},
        }
    ]
    upstream_calls = []

    def upstream(request):
        upstream_calls.append(request)
        path = request.url.path.split("/api/v1/")[1]
        if path == "tasks":
            assert request.method == "GET" and dict(request.url.params) == {"scope": "all"}
            return httpx.Response(200, json={"items": source_tasks})
        if path.endswith("/schema"):
            assert request.method == "GET"
            return httpx.Response(
                200,
                json={
                    "name": "Backlog",
                    "properties": [
                        {"key": "source_task_id", "name": "Source task ID", "type": "text"}
                    ],
                },
            )
        assert path == "collections/backlog/items"
        if request.method == "POST":
            values = json.loads(request.content)["items"][0]
            assert values["properties"]["source_task_id"] == "new-source"
            rows.append({"id": "new-row", **values})
            return httpx.Response(200, json={"items": [rows[-1]]})
        assert request.method == "GET"
        return httpx.Response(200, json={"items": rows})

    settings = Settings(
        _env_file=None,
        craft_space_base_url="https://connect.craft.do/links/copy-fixture-secret/api/v1",
        wrapper_migration_token="copy-fixture-token",
        wrapper_profiles_json=json.dumps(
            {
                "migration": {
                    "adapters": ["space"],
                    "expiresAt": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    "writeTargets": {"space": {"collectionIds": ["backlog"]}},
                }
            }
        ),
    )
    app = create_app(settings, upstream_transport=httpx.MockTransport(upstream))
    original = httpx.AsyncClient
    tool.valves.WRAPPER_PROFILE = "migration"
    tool.valves.WRAPPER_API_TOKEN = "copy-fixture-token"

    async def run():
        async with app.router.lifespan_context(app):
            monkeypatch.setattr(
                module.httpx,
                "AsyncClient",
                lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs),
            )
            discovered = await tool.craft_space_list_tasks({"scope": "all"})
            schema = await tool.craft_space_get_collection_schema("backlog")
            key = schema["response"]["properties"][0]["key"]
            existing = await tool.craft_space_list_collection_items("backlog")
            source_ids = {row["properties"][key] for row in existing["response"]["items"]}
            for task in discovered["response"]["items"]:
                if task["id"] in source_ids:
                    continue
                result = await tool.craft_space_add_collection_item(
                    "backlog", {"title": task["markdown"], "properties": {key: task["id"]}}
                )
                assert result["statusCode"] == 201
                checked = await tool.craft_space_list_collection_items("backlog")
                assert any(
                    row["id"] == result["response"]["id"] and row["properties"][key] == task["id"]
                    for row in checked["response"]["items"]
                )
            denied = await tool.craft_space_update_collection_item_properties(
                "backlog", "existing-row", {"properties": {key: "changed"}}
            )
            assert denied["response"]["error"]["code"] == "tool_permission_denied"

    asyncio.run(run())
    assert json.dumps(source_tasks, sort_keys=True) == original_sources
    assert len(rows) == 2
    assert len([r for r in upstream_calls if r.method == "POST"]) == 1
    assert not any(r.method in {"PUT", "DELETE", "PATCH"} for r in upstream_calls)


@pytest.mark.parametrize("change", ["expire", "revoke"])
@pytest.mark.parametrize("tool_context", ["space"], indirect=True)
def test_server_rechecks_access_after_live_confirmation(tool_context, monkeypatch, change):
    from datetime import UTC, datetime, timedelta

    from craft_wrapper.config import Settings
    from craft_wrapper.main import create_app

    adapter, module, tool, calls, connect = tool_context
    upstream_calls = []

    def upstream(request):
        upstream_calls.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json={"name": "Backlog", "properties": []})
        return httpx.Response(200, json={"items": [{"id": "row", "title": "Example"}]})

    settings = Settings(
        _env_file=None,
        craft_space_base_url="https://connect.craft.do/links/approval-fixture-secret/api/v1",
        wrapper_planner_token="approval-fixture-token",
        wrapper_profiles_json=json.dumps(
            {
                "planner": {
                    "adapters": ["space"],
                    "writeTargets": {"space": {"collectionIds": ["backlog"]}},
                }
            }
        ),
    )
    app = create_app(settings, upstream_transport=httpx.MockTransport(upstream))
    original = httpx.AsyncClient
    tool.valves.WRAPPER_PROFILE = "planner"
    tool.valves.WRAPPER_API_TOKEN = "approval-fixture-token"

    async def confirm(event):
        if change == "expire":
            settings.profiles["planner"].expiresAt = datetime.now(UTC) - timedelta(seconds=1)
        else:
            settings.profiles["planner"].enabled = False
        return True

    async def run():
        async with app.router.lifespan_context(app):
            monkeypatch.setattr(
                module.httpx,
                "AsyncClient",
                lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs),
            )
            result = await tool.craft_space_delete_collection_item(
                "backlog", "row", __event_call__=confirm
            )
            assert result["statusCode"] == 403
            assert result["response"]["error"]["code"] == (
                "profile_expired" if change == "expire" else "permission_denied"
            )

    asyncio.run(run())
    assert len(upstream_calls) == 2

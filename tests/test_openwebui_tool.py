import asyncio
import importlib.util
import inspect
import json
import logging
import sys
from pathlib import Path
from typing import Any, get_type_hints

import httpx
import pytest
from pydantic import ValidationError, create_model

from craft_wrapper.main import create_app


@pytest.fixture(params=["space", "documents", "daily"])
def tool_module(request) -> Any:
    filename = "craft_" + request.param + "_tool.py"
    path = Path(__file__).parents[1] / "integrations/openwebui" / filename
    spec = importlib.util.spec_from_file_location("craft_owui_test_" + request.param, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tool(tool_module):
    result = tool_module.Tools()
    result.valves = result.Valves(
        WRAPPER_URL="http://wrapper.test", WRAPPER_API_TOKEN="test-wrapper-token"
    )
    return result


def adapter(tool) -> str:
    if hasattr(tool, "craft_daily_get_note"):
        return "daily"
    return "space" if hasattr(tool, "craft_space_list_documents") else "documents"


def operation(tool, name: str):
    if adapter(tool) == "daily":
        name = {"list_documents": "get_note", "search_documents": "search_notes"}.get(name, name)
    return getattr(tool, "craft_" + adapter(tool) + "_" + name)


def tool_app(settings, tool, upstream):
    if adapter(tool) == "daily":
        settings = settings.model_copy(
            update={
                "craft_daily_base_url": settings.craft_space_base_url,
                "craft_space_base_url": None,
            }
        )
        return create_app(settings, daily_upstream_transport=httpx.MockTransport(upstream))
    if adapter(tool) == "documents":
        settings = settings.model_copy(
            update={
                "craft_documents_base_url": settings.craft_space_base_url,
                "craft_space_base_url": None,
            }
        )
        return create_app(settings, documents_upstream_transport=httpx.MockTransport(upstream))
    return create_app(settings, upstream_transport=httpx.MockTransport(upstream))


def connect_mock(monkeypatch, tool_module, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(transport=transport, **kwargs)

    monkeypatch.setattr(tool_module.httpx, "AsyncClient", client)


@pytest.mark.parametrize(
    "name,arguments,method,path,query,body",
    [
        ("list_folders", {}, "GET", "/folders", {}, None),
        (
            "list_documents",
            {"parameters": {"fetchMetadata": False, "createdDateGte": "today", "folderId": None}},
            "GET",
            "/documents",
            {"fetchMetadata": "false", "createdDateGte": "today"},
            None,
        ),
        (
            "search_documents",
            {"parameters": {"query": "a & b", "fetchBlocks": True}},
            "GET",
            "/documents/search",
            {"query": "a & b", "fetchBlocks": "true"},
            None,
        ),
        (
            "create_document",
            {"body": {"title": "Example", "location": "templates"}},
            "POST",
            "/documents",
            {},
            {"title": "Example", "location": "templates"},
        ),
        (
            "get_block",
            {"blockId": "page", "parameters": {"maxDepth": -1}},
            "GET",
            "/blocks/page",
            {"maxDepth": "-1"},
            None,
        ),
        ("read_markdown", {"blockId": "page"}, "GET", "/blocks/page/markdown", {}, None),
        (
            "insert_markdown",
            {"pageId": "page", "body": {"markdown": "Hello"}},
            "POST",
            "/blocks/page/content",
            {},
            {"markdown": "Hello"},
        ),
        (
            "update_block_markdown",
            {"blockId": "text", "body": {"markdown": ""}},
            "PATCH",
            "/blocks/text",
            {},
            {"markdown": ""},
        ),
        (
            "list_collections",
            {"parameters": {"documentId": "page"}},
            "GET",
            "/collections",
            {"documentId": "page"},
            None,
        ),
        (
            "get_collection_schema",
            {"collectionId": "collection"},
            "GET",
            "/collections/collection/schema",
            {},
            None,
        ),
        (
            "list_collection_items",
            {"collectionId": "collection"},
            "GET",
            "/collections/collection/items",
            {},
            None,
        ),
        (
            "add_collection_item",
            {
                "collectionId": "collection",
                "body": {"title": "Row", "properties": {"due": "2026-10-02"}},
            },
            "POST",
            "/collections/collection/items",
            {},
            {"title": "Row", "properties": {"due": "2026-10-02"}},
        ),
        (
            "update_collection_item_properties",
            {
                "collectionId": "collection",
                "itemId": "row",
                "body": {"properties": {"status": "Done"}},
            },
            "PATCH",
            "/collections/collection/items/row",
            {},
            {"properties": {"status": "Done"}},
        ),
    ],
)
def test_all_operation_mappings(
    tool_module, tool, monkeypatch, name, arguments, method, path, query, body
):
    if not hasattr(tool, "craft_" + adapter(tool) + "_" + name):
        pytest.skip("Operation is not implemented by this adapter")
    calls = []

    async def confirm(event):
        return True

    if method == "DELETE":
        arguments = {**arguments, "__event_call__": confirm}

    def handler(request):
        if method == "DELETE" and request.method == "GET":
            assert request.url.path == "/v1/" + adapter(tool) + "/blocks/task"
            return httpx.Response(200, json={"id": "task", "type": "text", "markdown": "Task"})
        calls.append(request)
        assert request.method == method
        assert request.url.host == "wrapper.test"
        assert request.url.path == "/v1/" + adapter(tool) + path
        assert dict(request.url.params) == query
        assert request.headers["Authorization"] == "Bearer test-wrapper-token"
        assert request.headers["Accept"] == "application/json"
        assert (json.loads(request.content) if request.content else None) == body
        return httpx.Response(
            201 if method == "POST" else 200,
            json={"id": "result"},
            headers={"X-Request-Id": "trace"},
        )

    connect_mock(monkeypatch, tool_module, handler)
    result = asyncio.run(operation(tool, name)(**arguments))
    assert result == {
        "request": {"method": method, "path": "/v1/" + adapter(tool) + path, "query": query},
        "statusCode": 201 if method == "POST" else 200,
        "requestId": "trace",
        "response": {"id": "result"},
    }
    assert len(calls) == 1
    assert "test-wrapper-token" not in json.dumps(result)


def test_unknown_fields_and_string_writes_reach_real_wrapper(
    tool_module, tool, monkeypatch, settings
):
    upstream_calls = []

    def upstream(request):
        upstream_calls.append(request)
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json={"name": "Example", "properties": []})
        assert json.loads(request.content) == {
            "itemsToUpdate": [{"id": "row", "properties": {"due": "2026-10-02"}}]
        }
        return httpx.Response(
            200, json={"items": [{"id": "row", "properties": {"due": "2026-10-02"}}]}
        )

    original = httpx.AsyncClient
    app = tool_app(settings, tool, upstream)

    async def run():
        async with app.router.lifespan_context(app):
            monkeypatch.setattr(
                tool_module.httpx,
                "AsyncClient",
                lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs),
            )
            invalid = await operation(tool, "list_documents")({"documentId": "unsupported"})
            assert invalid["statusCode"] == 422
            assert invalid["request"]["query"] == {"documentId": "unsupported"}
            assert invalid["response"]["error"]["code"] == "validation_error"
            empty = await operation(tool, "search_documents")({"query": ""})
            assert empty["statusCode"] == 422
            complex_value = await operation(tool, "update_collection_item_properties")(
                "collection", "row", {"properties": {"due": ["bad"]}}
            )
            assert complex_value["statusCode"] == 422
            assert not upstream_calls
            valid = await operation(tool, "update_collection_item_properties")(
                "collection", "row", {"properties": {"due": "2026-10-02"}}
            )
            assert valid["statusCode"] == 200
            assert valid["response"]["properties"] == {"due": "2026-10-02"}

    asyncio.run(run())
    assert len(upstream_calls) == 2


def test_read_only_wrapper_still_controls_writes(tool_module, tool, monkeypatch, settings):
    settings.wrapper_enabled_operations = "read_only"
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={"items": []})

    app = tool_app(settings, tool, upstream)
    original = httpx.AsyncClient

    async def run():
        async with app.router.lifespan_context(app):
            monkeypatch.setattr(
                tool_module.httpx,
                "AsyncClient",
                lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs),
            )
            result = await operation(tool, "insert_markdown")("page", {"markdown": "Example"})
            assert result["statusCode"] == 404
            assert result["response"]["error"]["code"] == "not_found"
            assert not calls

    asyncio.run(run())


def test_encoded_identifiers(tool_module, tool, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        assert (
            request.url.raw_path
            == ("/v1/" + adapter(tool) + "/blocks/id%2F%3F%23%20%25/markdown").encode()
        )
        return httpx.Response(200, json={"markdown": "Example"})

    connect_mock(monkeypatch, tool_module, handler)
    asyncio.run(operation(tool, "read_markdown")("id/?# %"))
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 404, 429, 502])
def test_wrapper_errors_preserved(tool_module, tool, monkeypatch, status):
    payload = {
        "error": {
            "code": "example",
            "message": "Safe message",
            "retryAfterSeconds": 60,
            "outcomeUnknown": True,
            "requestId": "trace",
        }
    }
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=payload)

    connect_mock(monkeypatch, tool_module, handler)
    result = asyncio.run(operation(tool, "insert_markdown")("page", {"markdown": "Example"}))
    assert result["response"] == payload
    assert result["statusCode"] == status
    assert len(calls) == 1


@pytest.mark.parametrize("write", [False, True])
@pytest.mark.parametrize(
    "failure", ["timeout", "network", "html", "json", "array", "large", "redirect"]
)
def test_failure_bounds_and_no_retries(tool_module, tool, monkeypatch, failure, write):
    calls = []
    monkeypatch.setattr(tool_module, "MAX_RESPONSE_BYTES", 100)

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("test-wrapper-token sensitive search", request=request)
        if failure == "network":
            raise httpx.ConnectError("test-wrapper-token sensitive search", request=request)
        if failure == "redirect":
            return httpx.Response(307, headers={"Location": "http://elsewhere.test"})
        if failure == "html":
            return httpx.Response(500, text="test-wrapper-token sensitive search")
        if failure == "json":
            return httpx.Response(
                200, content="invalid secret response", headers={"Content-Type": "application/json"}
            )
        if failure == "large":
            return httpx.Response(200, json={"content": "x" * 101})
        return httpx.Response(200, json=["unexpected array"])

    connect_mock(monkeypatch, tool_module, handler)
    result = asyncio.run(
        operation(tool, "insert_markdown")("page", {"markdown": "Example"})
        if write
        else operation(tool, "list_documents")()
    )
    error = result["response"]["error"]
    assert error["code"] == {
        "timeout": "tool_wrapper_timeout",
        "network": "tool_wrapper_unavailable",
        "large": "tool_response_too_large",
    }.get(failure, "tool_invalid_response")
    if write:
        assert error["outcomeUnknown"] is True
    else:
        assert "outcomeUnknown" not in error
    assert len(calls) == 1
    assert "test-wrapper-token" not in json.dumps(result)
    assert "sensitive search" not in json.dumps(result)


def test_overall_deadline(tool_module, tool, monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={})

    connect_mock(monkeypatch, tool_module, handler)
    tool.valves.TIMEOUT_SECONDS = 0.01
    result = asyncio.run(operation(tool, "insert_markdown")("page", {"markdown": "Example"}))
    assert result["response"]["error"]["code"] == "tool_wrapper_timeout"
    assert result["response"]["error"]["outcomeUnknown"] is True
    assert len(calls) == 1


def test_missing_token_and_complex_query_make_no_request(tool_module, tool, monkeypatch):
    def unexpected(**kwargs):
        pytest.fail("Invalid configuration/arguments must not send a request")

    monkeypatch.setattr(tool_module.httpx, "AsyncClient", unexpected)
    tool.valves.WRAPPER_API_TOKEN = ""
    result = asyncio.run(operation(tool, "list_documents")())
    assert result["response"]["error"]["code"] == "tool_configuration_error"
    tool.valves.WRAPPER_API_TOKEN = "test-wrapper-token"
    result = asyncio.run(operation(tool, "list_documents")({"folderId": ["unexpected"]}))
    assert result["response"]["error"]["code"] == "tool_invalid_arguments"


@pytest.mark.parametrize(
    "origin",
    [
        "https://connect.craft.do",
        "https://mcp.craft.do",
        "https://user:secret@wrapper.test",
        "http://wrapper.test/path",
        "http://wrapper.test?token=secret",
        "ftp://wrapper.test",
        "http://wrapper.test/#fragment",
    ],
)
def test_valves_reject_connection_urls(tool_module, origin):
    with pytest.raises(ValidationError):
        tool_module.Tools.Valves(WRAPPER_URL=origin)


def test_private_request_logging_suppressed_and_filter_removed(
    tool_module, tool, monkeypatch, caplog
):
    connect_mock(monkeypatch, tool_module, lambda request: httpx.Response(200, json={"items": []}))
    logger = logging.getLogger("httpx")
    before = list(logger.filters)
    with caplog.at_level(logging.INFO, logger="httpx"):
        asyncio.run(operation(tool, "search_documents")({"query": "private-search-text"}))
    assert "private-search-text" not in caplog.text
    assert "test-wrapper-token" not in caplog.text
    assert logger.filters == before


def test_expected_public_tools_and_nested_argument_schema(tool):
    methods = inspect.getmembers(type(tool), predicate=inspect.iscoroutinefunction)
    public = [(name, method) for name, method in methods if not name.startswith("_")]
    assert len(public) == {"space": 21, "documents": 15, "daily": 21}[adapter(tool)]
    assert all(name.startswith("craft_" + adapter(tool) + "_") for name, _ in public)
    method = operation(tool, "list_documents")
    hints = get_type_hints(method)
    parameter = inspect.signature(method).parameters["parameters"]
    model = create_model("DocumentArguments", parameters=(hints["parameters"], parameter.default))
    parsed = model.model_validate({"parameters": {"documentId": "unsupported"}})
    assert parsed.model_dump() == {"parameters": {"documentId": "unsupported"}}
    schema = model.model_json_schema()
    assert schema["properties"]["parameters"]["anyOf"][0]["additionalProperties"] is True


def test_mocked_document_and_collection_workflows(tool_module, tool, settings, monkeypatch):
    calls = []
    text = "Original"
    properties = {"status": "Todo"}

    def upstream(request):
        nonlocal text, properties
        calls.append(request)
        path = request.url.path.split("/api/v1/")[1]
        if path == "documents":
            return httpx.Response(
                200, json={"items": [{"id": "root", "title": "Example", "isDeleted": False}]}
            )
        if path == "blocks" and request.method == "GET":
            assert dict(request.url.params) == (
                {"date": "today", "maxDepth": "1"}
                if "date" in request.url.params
                else {"id": "root", "maxDepth": "1"}
            )
            return httpx.Response(
                200,
                json={
                    "id": "root",
                    "type": "page",
                    "content": [{"id": "text", "type": "text", "markdown": text}],
                },
            )
        if path == "blocks":
            body = json.loads(request.content)
            if request.method == "POST":
                assert body == {
                    "markdown": "Inserted",
                    "position": {"pageId": "root", "position": "end"},
                }
                return httpx.Response(
                    200,
                    json={"items": [{"id": "new-text", "type": "text", "markdown": "Inserted"}]},
                )
            assert body == {"blocks": [{"id": "new-text", "markdown": "Updated"}]}
            text = body["blocks"][0]["markdown"]
            return httpx.Response(
                200, json={"items": [{"id": "new-text", "type": "text", "markdown": text}]}
            )
        if path == "collections":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "collection",
                            "name": "Example",
                            **(
                                {"dailyNoteDate": "2026-10-03"}
                                if adapter(tool) == "daily"
                                else {"documentId": "root"}
                            ),
                            "itemCount": 0,
                        }
                    ]
                },
            )
        if path.endswith("/schema"):
            return httpx.Response(
                200,
                json={
                    "name": "Example",
                    "properties": [
                        {
                            "key": "status",
                            "name": "Status",
                            "type": "select",
                            "options": ["Todo", "Done"],
                        }
                    ],
                },
            )
        assert path == "collections/collection/items"
        body = json.loads(request.content)
        if request.method == "POST":
            assert body == {"items": [{"title": "Example", "properties": {"status": "Todo"}}]}
        else:
            assert body == {"itemsToUpdate": [{"id": "row", "properties": {"status": "Done"}}]}
            properties = body["itemsToUpdate"][0]["properties"]
        return httpx.Response(200, json={"items": [{"id": "row", "properties": properties}]})

    original = httpx.AsyncClient
    app = tool_app(settings, tool, upstream)

    async def run():
        async with app.router.lifespan_context(app):
            monkeypatch.setattr(
                tool_module.httpx,
                "AsyncClient",
                lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs),
            )
            documents = await operation(tool, "list_documents")()
            root = (
                documents["response"]["id"]
                if adapter(tool) == "daily"
                else documents["response"]["items"][0]["id"]
            )
            content = await operation(tool, "get_block")(root)
            assert content["response"]["content"][0]["id"] == "text"
            inserted = await operation(tool, "insert_markdown")(root, {"markdown": "Inserted"})
            assert inserted["statusCode"] == 201
            new_id = inserted["response"]["items"][0]["id"]
            updated = await operation(tool, "update_block_markdown")(
                new_id, {"markdown": "Updated"}
            )
            assert updated["response"]["markdown"] == "Updated"
            collections = await operation(tool, "list_collections")(
                {"startDate": "today"} if adapter(tool) == "daily" else {"documentId": root}
            )
            collection = collections["response"]["items"][0]["id"]
            schema = await operation(tool, "get_collection_schema")(collection)
            key = schema["response"]["properties"][0]["key"]
            row = await operation(tool, "add_collection_item")(
                collection, {"title": "Example", "properties": {key: "Todo"}}
            )
            assert row["statusCode"] == 201
            updated_row = await operation(tool, "update_collection_item_properties")(
                collection, row["response"]["id"], {"properties": {key: "Done"}}
            )
            assert updated_row["response"]["properties"] == {"status": "Done"}

    asyncio.run(run())
    assert len(calls) == 10


@pytest.mark.parametrize("tool_module", ["daily"], indirect=True)
@pytest.mark.parametrize(
    "name,arguments,method,path,query,body",
    [
        ("get_note", {}, "GET", "/notes", {}, None),
        (
            "read_note_markdown",
            {"parameters": {"date": "yesterday", "maxDepth": -1}},
            "GET",
            "/notes/markdown",
            {"date": "yesterday", "maxDepth": "-1"},
            None,
        ),
        (
            "insert_note_markdown",
            {"body": {"markdown": "New"}, "parameters": {"date": "tomorrow"}},
            "POST",
            "/notes/content",
            {"date": "tomorrow"},
            {"markdown": "New"},
        ),
        (
            "search_notes",
            {"parameters": {"query": "a & b", "fetchBlocks": True}},
            "GET",
            "/notes/search",
            {"query": "a & b", "fetchBlocks": "true"},
            None,
        ),
        (
            "list_collections",
            {"parameters": {"startDate": "today"}},
            "GET",
            "/collections",
            {"startDate": "today"},
            None,
        ),
        (
            "list_tasks",
            {"parameters": {"scope": "logbook"}},
            "GET",
            "/tasks",
            {"scope": "logbook"},
            None,
        ),
        (
            "add_task",
            {"body": {"markdown": "Task", "target": "daily_note"}},
            "POST",
            "/tasks",
            {},
            {"markdown": "Task", "target": "daily_note"},
        ),
        (
            "update_task",
            {"taskId": "task", "body": {"state": "done"}},
            "PATCH",
            "/tasks/task",
            {},
            {"state": "done"},
        ),
        ("delete_task", {"taskId": "task"}, "DELETE", "/tasks/task", {}, None),
    ],
)
def test_daily_specific_tool_mappings(
    tool_module, tool, monkeypatch, name, arguments, method, path, query, body
):
    test_all_operation_mappings(
        tool_module, tool, monkeypatch, name, arguments, method, path, query, body
    )


@pytest.mark.parametrize("tool_module", ["daily"], indirect=True)
def test_daily_date_content_and_task_workflows(tool_module, tool, settings, monkeypatch):
    calls = []
    task = None
    text = "Original"

    def upstream(request):
        nonlocal task, text
        calls.append(request)
        path = request.url.path.split("/api/v1/")[1]
        body = json.loads(request.content) if request.content else {}
        if path == "blocks":
            if request.method == "GET":
                if "id" in request.url.params:
                    assert dict(request.url.params) == {"id": "native-task", "maxDepth": "0"}
                    return httpx.Response(
                        200, json={"id": "native-task", "type": "text", "markdown": "Example"}
                    )
                assert dict(request.url.params) == {"date": "today", "maxDepth": "1"}
                return httpx.Response(200, json={"id": "daily-root", "type": "page", "content": []})
            if request.method == "POST":
                assert body == {
                    "markdown": "Inserted",
                    "position": {"date": "today", "position": "end"},
                }
                text = body["markdown"]
            else:
                assert body == {"blocks": [{"id": "new-text", "markdown": "Updated"}]}
                text = body["blocks"][0]["markdown"]
            return httpx.Response(
                200, json={"items": [{"id": "new-text", "type": "text", "markdown": text}]}
            )
        assert path == "tasks"
        if request.method == "POST":
            assert body == {
                "tasks": [
                    {
                        "markdown": "Example",
                        "location": {"type": "dailyNote", "date": "today"},
                        "taskInfo": {"scheduleDate": "tomorrow"},
                    }
                ]
            }
            task = {"id": "native-task", "markdown": "Example", "taskInfo": {"state": "todo"}}
            return httpx.Response(200, json={"items": [task]})
        if request.method == "PUT":
            assert body == {"tasksToUpdate": [{"id": "native-task", "taskInfo": {"state": "done"}}]}
            assert task is not None
            task["taskInfo"] = {"state": "done"}
            return httpx.Response(
                200, json={"items": [{"id": "native-task", "taskInfo": {"state": "done"}}]}
            )
        if request.method == "DELETE":
            assert body == {"idsToDelete": ["native-task"]}
            task = None
            return httpx.Response(200, json={"items": [{"id": "native-task"}]})
        return httpx.Response(200, json={"items": [] if task is None else [task]})

    original = httpx.AsyncClient
    app = tool_app(settings, tool, upstream)

    async def run():
        async with app.router.lifespan_context(app):
            monkeypatch.setattr(
                tool_module.httpx,
                "AsyncClient",
                lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs),
            )
            note = await tool.craft_daily_get_note()
            assert note["response"]["id"] == "daily-root"
            inserted = await tool.craft_daily_insert_note_markdown({"markdown": "Inserted"})
            assert inserted["statusCode"] == 201
            updated = await tool.craft_daily_update_block_markdown(
                inserted["response"]["items"][0]["id"], {"markdown": "Updated"}
            )
            assert updated["response"]["markdown"] == "Updated"
            created = await tool.craft_daily_add_task(
                {"markdown": "Example", "target": "daily_note", "scheduleDate": "tomorrow"}
            )
            assert created["statusCode"] == 201
            task_id = created["response"]["id"]
            updated_task = await tool.craft_daily_update_task(task_id, {"state": "done"})
            assert updated_task["response"] == {"id": "native-task", "taskInfo": {"state": "done"}}
            listed = await tool.craft_daily_list_tasks({"scope": "logbook"})
            assert listed["response"]["items"][0]["taskInfo"]["state"] == "done"

            async def confirm(event):
                assert event["type"] == "confirmation"
                return True

            deleted = await tool.craft_daily_delete_task(task_id, __event_call__=confirm)
            assert deleted["response"] == {"id": "native-task"}
            empty = await tool.craft_daily_list_tasks({"scope": "inbox"})
            assert empty["response"]["items"] == []
            invalid = await tool.craft_daily_update_task(task_id, {"scheduleDate": None})
            assert invalid["statusCode"] == 422
            assert "body" not in invalid["request"]

    asyncio.run(run())
    assert len(calls) == 9

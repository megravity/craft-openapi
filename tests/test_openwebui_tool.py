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


@pytest.fixture
def tool_module() -> Any:
    path = Path(__file__).parents[1] / "integrations/openwebui/craft_wrapper_tool.py"
    spec = importlib.util.spec_from_file_location("craft_owui_test", path)
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
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == method
        assert request.url.host == "wrapper.test"
        assert request.url.path == "/v1/space" + path
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
    result = asyncio.run(getattr(tool, "craft_space_" + name)(**arguments))
    assert result == {
        "request": {"method": method, "path": "/v1/space" + path, "query": query},
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
        assert json.loads(request.content) == {
            "itemsToUpdate": [{"id": "row", "properties": {"due": "2026-10-02"}}]
        }
        return httpx.Response(
            200, json={"items": [{"id": "row", "properties": {"due": "2026-10-02"}}]}
        )

    original = httpx.AsyncClient
    app = create_app(settings, upstream_transport=httpx.MockTransport(upstream))

    async def run():
        async with app.router.lifespan_context(app):
            monkeypatch.setattr(
                tool_module.httpx,
                "AsyncClient",
                lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs),
            )
            invalid = await tool.craft_space_list_documents({"documentId": "unsupported"})
            assert invalid["statusCode"] == 422
            assert invalid["request"]["query"] == {"documentId": "unsupported"}
            assert invalid["response"]["error"]["code"] == "validation_error"
            empty = await tool.craft_space_search_documents({"query": ""})
            assert empty["statusCode"] == 422
            complex_value = await tool.craft_space_update_collection_item_properties(
                "collection", "row", {"properties": {"due": ["bad"]}}
            )
            assert complex_value["statusCode"] == 422
            assert not upstream_calls
            valid = await tool.craft_space_update_collection_item_properties(
                "collection", "row", {"properties": {"due": "2026-10-02"}}
            )
            assert valid["statusCode"] == 200
            assert valid["response"]["properties"] == {"due": "2026-10-02"}

    asyncio.run(run())
    assert len(upstream_calls) == 1


def test_read_only_wrapper_still_controls_writes(tool_module, tool, monkeypatch, settings):
    settings.wrapper_enabled_operations = "read_only"
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={"items": []})

    app = create_app(settings, upstream_transport=httpx.MockTransport(upstream))
    original = httpx.AsyncClient

    async def run():
        async with app.router.lifespan_context(app):
            monkeypatch.setattr(
                tool_module.httpx,
                "AsyncClient",
                lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs),
            )
            result = await tool.craft_space_create_document({"title": "Example"})
            assert result["statusCode"] == 404
            assert result["response"]["error"]["code"] == "not_found"
            assert not calls

    asyncio.run(run())


def test_encoded_identifiers(tool_module, tool, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.raw_path == b"/v1/space/blocks/id%2F%3F%23%20%25/markdown"
        return httpx.Response(200, json={"markdown": "Example"})

    connect_mock(monkeypatch, tool_module, handler)
    asyncio.run(tool.craft_space_read_markdown("id/?# %"))
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
    result = asyncio.run(tool.craft_space_create_document({"title": "Example"}))
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
        tool.craft_space_create_document({"title": "Example"})
        if write
        else tool.craft_space_list_folders()
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
    result = asyncio.run(tool.craft_space_create_document({"title": "Example"}))
    assert result["response"]["error"]["code"] == "tool_wrapper_timeout"
    assert result["response"]["error"]["outcomeUnknown"] is True
    assert len(calls) == 1


def test_missing_token_and_complex_query_make_no_request(tool_module, tool, monkeypatch):
    def unexpected(**kwargs):
        pytest.fail("Invalid configuration/arguments must not send a request")

    monkeypatch.setattr(tool_module.httpx, "AsyncClient", unexpected)
    tool.valves.WRAPPER_API_TOKEN = ""
    result = asyncio.run(tool.craft_space_list_folders())
    assert result["response"]["error"]["code"] == "tool_configuration_error"
    tool.valves.WRAPPER_API_TOKEN = "test-wrapper-token"
    result = asyncio.run(tool.craft_space_list_documents({"folderId": ["unexpected"]}))
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
        asyncio.run(tool.craft_space_search_documents({"query": "private-search-text"}))
    assert "private-search-text" not in caplog.text
    assert "test-wrapper-token" not in caplog.text
    assert logger.filters == before


def test_only_thirteen_public_tools_and_nested_argument_schema(tool):
    methods = inspect.getmembers(type(tool), predicate=inspect.iscoroutinefunction)
    public = [(name, method) for name, method in methods if not name.startswith("_")]
    assert len(public) == 13
    assert all(name.startswith("craft_space_") for name, _ in public)
    method = tool.craft_space_list_documents
    hints = get_type_hints(method)
    parameter = inspect.signature(method).parameters["parameters"]
    model = create_model("DocumentArguments", parameters=(hints["parameters"], parameter.default))
    parsed = model.model_validate({"parameters": {"documentId": "unsupported"}})
    assert parsed.model_dump() == {"parameters": {"documentId": "unsupported"}}
    schema = model.model_json_schema()
    assert schema["properties"]["parameters"]["anyOf"][0]["additionalProperties"] is True

import json
import logging
from itertools import product
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from pydantic import SecretStr, ValidationError

from craft_wrapper.config import (
    DAILY_OPERATION_IDS,
    DAILY_READ_OPERATION_IDS,
    DOCUMENTS_OPERATION_IDS,
    DOCUMENTS_READ_OPERATION_IDS,
    SPACE_OPERATION_IDS,
    SPACE_READ_OPERATION_IDS,
    Settings,
)
from craft_wrapper.main import create_app

AUTH = {"Authorization": "Bearer test-wrapper-token"}
DAILY_URL = "https://connect.craft.do/links/daily-test-secret/api/v1"


@pytest.fixture
def daily_settings():
    return Settings(
        _env_file=None,
        craft_space_base_url=None,
        craft_documents_base_url=None,
        craft_daily_base_url=DAILY_URL,
        wrapper_api_token="test-wrapper-token",
    )


@pytest.fixture
def daily_fixtures():
    return json.loads((Path(__file__).parent / "fixtures/daily.json").read_text())


def unexpected(request):
    pytest.fail("Request must not reach another Craft connection")


# Public method/path/query/body -> upstream method/path/query/body, with payload fixture.
@pytest.mark.parametrize(
    "method,path,query,body,upstream_method,upstream_path,upstream_query,upstream_body,payload",
    [
        (
            "GET",
            "/notes",
            {},
            None,
            "GET",
            "blocks",
            {"date": "today", "maxDepth": "1"},
            None,
            "block",
        ),
        (
            "GET",
            "/notes",
            {"date": "yesterday", "maxDepth": -1},
            None,
            "GET",
            "blocks",
            {"date": "yesterday", "maxDepth": "-1"},
            None,
            "block",
        ),
        (
            "GET",
            "/notes/markdown",
            {"date": "tomorrow"},
            None,
            "GET",
            "blocks",
            {"date": "tomorrow", "maxDepth": "1"},
            None,
            "markdown",
        ),
        (
            "POST",
            "/notes/content",
            {},
            {"markdown": "Hello"},
            "POST",
            "blocks",
            {},
            {"markdown": "Hello", "position": {"date": "today", "position": "end"}},
            "blocks",
        ),
        (
            "POST",
            "/notes/content",
            {"date": "2026-10-03"},
            {"markdown": "Hello", "position": "start"},
            "POST",
            "blocks",
            {},
            {"markdown": "Hello", "position": {"date": "2026-10-03", "position": "start"}},
            "blocks",
        ),
        (
            "GET",
            "/blocks/root &?",
            {},
            None,
            "GET",
            "blocks",
            {"id": "root &?", "maxDepth": "1"},
            None,
            "block",
        ),
        (
            "GET",
            "/blocks/daily-root/markdown",
            {"maxDepth": -1},
            None,
            "GET",
            "blocks",
            {"id": "daily-root", "maxDepth": "-1"},
            None,
            "markdown",
        ),
        (
            "POST",
            "/blocks/daily-root/content",
            {},
            {"markdown": "Hello"},
            "POST",
            "blocks",
            {},
            {"markdown": "Hello", "position": {"pageId": "daily-root", "position": "end"}},
            "blocks",
        ),
        (
            "PATCH",
            "/blocks/daily-text",
            {},
            {"markdown": ""},
            "PUT",
            "blocks",
            {},
            {"blocks": [{"id": "daily-text", "markdown": ""}]},
            "block_update",
        ),
        (
            "GET",
            "/notes/search",
            {"query": "a & b", "startDate": "yesterday", "endDate": "today", "fetchBlocks": True},
            None,
            "GET",
            "daily-notes/search",
            {
                "include": "a & b",
                "startDate": "yesterday",
                "endDate": "today",
                "fetchBlocks": "true",
            },
            None,
            "search",
        ),
        (
            "GET",
            "/notes/search",
            {"query": "a"},
            None,
            "GET",
            "daily-notes/search",
            {"include": "a", "fetchBlocks": "false"},
            None,
            "search",
        ),
        ("GET", "/collections", {}, None, "GET", "collections", {}, None, "collections"),
        (
            "GET",
            "/collections",
            {"startDate": "today", "endDate": "tomorrow"},
            None,
            "GET",
            "collections",
            {"startDate": "today", "endDate": "tomorrow"},
            None,
            "collections",
        ),
        (
            "GET",
            "/collections/daily-collection/schema",
            {},
            None,
            "GET",
            "collections/daily-collection/schema",
            {"format": "schema"},
            None,
            "schema",
        ),
        (
            "GET",
            "/collections/daily-collection/items",
            {},
            None,
            "GET",
            "collections/daily-collection/items",
            {"maxDepth": "0"},
            None,
            "items",
        ),
        (
            "POST",
            "/collections/daily-collection/items",
            {},
            {"title": "Example"},
            "POST",
            "collections/daily-collection/items",
            {},
            {"items": [{"title": "Example", "properties": {}}]},
            "items",
        ),
        (
            "PATCH",
            "/collections/daily-collection/items/row",
            {},
            {"properties": {"status": "Done"}},
            "PUT",
            "collections/daily-collection/items",
            {},
            {"itemsToUpdate": [{"id": "row", "properties": {"status": "Done"}}]},
            "items",
        ),
        (
            "GET",
            "/tasks",
            {"scope": "inbox"},
            None,
            "GET",
            "tasks",
            {"scope": "inbox"},
            None,
            "tasks",
        ),
        (
            "POST",
            "/tasks",
            {},
            {"markdown": "Example"},
            "POST",
            "tasks",
            {},
            {"tasks": [{"markdown": "Example", "location": {"type": "inbox"}}]},
            "tasks",
        ),
        (
            "POST",
            "/tasks",
            {},
            {"markdown": "Example", "target": "daily_note"},
            "POST",
            "tasks",
            {},
            {
                "tasks": [
                    {"markdown": "Example", "location": {"type": "dailyNote", "date": "today"}}
                ]
            },
            "tasks",
        ),
        (
            "POST",
            "/tasks",
            {},
            {
                "markdown": "Example",
                "target": "daily_note",
                "date": "yesterday",
                "scheduleDate": "tomorrow",
                "deadlineDate": "2026-10-05",
            },
            "POST",
            "tasks",
            {},
            {
                "tasks": [
                    {
                        "markdown": "Example",
                        "location": {"type": "dailyNote", "date": "yesterday"},
                        "taskInfo": {"scheduleDate": "tomorrow", "deadlineDate": "2026-10-05"},
                    }
                ]
            },
            "tasks",
        ),
        (
            "PATCH",
            "/tasks/task-slug",
            {},
            {"state": "done"},
            "PUT",
            "tasks",
            {},
            {"tasksToUpdate": [{"id": "task-slug", "taskInfo": {"state": "done"}}]},
            "partial_task",
        ),
        (
            "PATCH",
            "/tasks/task-slug",
            {},
            {
                "markdown": "Updated",
                "state": "canceled",
                "scheduleDate": "tomorrow",
                "deadlineDate": "2026-10-05",
            },
            "PUT",
            "tasks",
            {},
            {
                "tasksToUpdate": [
                    {
                        "id": "task-slug",
                        "markdown": "Updated",
                        "taskInfo": {
                            "state": "canceled",
                            "scheduleDate": "tomorrow",
                            "deadlineDate": "2026-10-05",
                        },
                    }
                ]
            },
            "partial_task",
        ),
        (
            "DELETE",
            "/tasks/task-slug",
            {},
            None,
            "DELETE",
            "tasks",
            {},
            {"idsToDelete": ["task-slug"]},
            "deleted_task",
        ),
    ],
)
def test_daily_operation_contracts(
    daily_settings,
    daily_fixtures,
    method,
    path,
    query,
    body,
    upstream_method,
    upstream_path,
    upstream_query,
    upstream_body,
    payload,
):
    values = daily_fixtures | {
        "markdown": "[Scoped](invalid:out_of_scope)",
        "blocks": {"items": [daily_fixtures["block"], {"id": "new", "type": "text"}]},
        "block_update": {"items": [{"id": "daily-text", "type": "text", "markdown": ""}]},
        "items": {"items": [daily_fixtures["item"]]},
        "tasks": {"items": [daily_fixtures["task"]]},
        "partial_task": {"items": [{"id": "task-slug", "taskInfo": {"state": "future-state"}}]},
        "deleted_task": {"items": [{"id": "task-slug"}]},
    }
    response = values[payload]
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == upstream_method
        assert request.url.path == "/links/daily-test-secret/api/v1/" + upstream_path
        assert dict(request.url.params) == upstream_query
        assert "authorization" not in request.headers
        assert request.headers["accept"] == (
            "text/markdown" if payload == "markdown" else "application/json"
        )
        assert (json.loads(request.content) if request.content else None) == upstream_body
        if upstream_body:
            assert request.headers["content-type"] == "application/json"
        if payload == "markdown":
            return httpx.Response(200, text=response, headers={"content-type": "text/markdown"})
        return httpx.Response(200, json=response)

    app = create_app(
        daily_settings,
        daily_upstream_transport=httpx.MockTransport(handler),
        upstream_transport=httpx.MockTransport(unexpected),
        documents_upstream_transport=httpx.MockTransport(unexpected),
    )
    # Let HTTPX encode a query-bearing opaque path ID without treating it as a URL.
    if path == "/blocks/root &?":
        path = "/blocks/root%20%26%3F"
    with TestClient(app) as client:
        result = client.request(method, "/v1/daily" + path, params=query, json=body, headers=AUTH)
    assert result.status_code == (201 if method == "POST" else 200), result.text
    if payload == "markdown":
        expected = (
            {"date": query.get("date", "today")}
            if path.startswith("/notes")
            else {"blockId": "daily-root"}
        ) | {"markdown": response}
    elif (
        payload in {"block_update", "partial_task", "deleted_task"}
        or method in {"POST", "PATCH"}
        and "/collections/" in path
    ):
        expected = response["items"][0]
    elif method == "POST" and path == "/tasks":
        expected = response["items"][0]
    else:
        expected = response
    assert result.json() == expected
    assert len(calls) == 1


@pytest.mark.parametrize(
    "path,query",
    [
        ("/notes", {"id": "root"}),
        ("/notes", {"date": "2026-02-30"}),
        ("/notes", {"date": "next week"}),
        ("/notes", {"maxDepth": -2}),
        ("/notes", {"maxDepth": "1.5"}),
        ("/notes/markdown", {"fetchMetadata": True}),
        ("/blocks/root", {"date": "today"}),
        ("/collections", {"documentId": "root"}),
        ("/collections", {"startDate": "2026-10-05", "endDate": "2026-10-03"}),
        ("/notes/search", {"query": ""}),
        ("/notes/search", {"query": "x", "location": "daily_notes"}),
        ("/notes/search", {"query": "x", "folderId": "folder"}),
        ("/notes/search", {"query": "x", "dailyNoteDateGte": "today"}),
        ("/notes/search", {"query": "x", "startDate": "2026-10-05", "endDate": "2026-10-03"}),
        ("/notes/search", {"query": "x", "regexps": "x"}),
        ("/tasks", {}),
        ("/tasks", {"scope": "all"}),
        ("/tasks", {"scope": "document"}),
        ("/tasks", {"scope": "active", "date": "today"}),
    ],
)
def test_invalid_queries_never_reach_craft(daily_settings, path, query):
    with TestClient(
        create_app(daily_settings, daily_upstream_transport=httpx.MockTransport(unexpected))
    ) as client:
        response = client.get("/v1/daily" + path, params=query, headers=AUTH)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/notes/content", {"markdown": ""}),
        ("POST", "/tasks", {"markdown": ""}),
        ("POST", "/tasks", {"markdown": "Task", "date": "today"}),
        ("POST", "/tasks", {"markdown": "Task", "target": "document"}),
        ("POST", "/tasks", {"markdown": "Task", "date": None}),
        ("POST", "/tasks", {"markdown": "Task", "scheduleDate": None}),
        ("POST", "/tasks", {"markdown": "Task", "deadlineDate": "2026-02-30"}),
        ("PATCH", "/tasks/task", {}),
        ("PATCH", "/tasks/task", {"markdown": ""}),
        ("PATCH", "/tasks/task", {"markdown": None}),
        ("PATCH", "/tasks/task", {"state": None}),
        ("PATCH", "/tasks/task", {"scheduleDate": None}),
        ("PATCH", "/tasks/task", {"deadlineDate": None}),
        ("PATCH", "/tasks/task", {"state": "cancelled"}),
        ("PATCH", "/tasks/task", {"target": "inbox"}),
        ("PATCH", "/tasks/task", {"taskInfo": {"state": "done"}}),
        (
            "POST",
            "/collections/col/items",
            {"title": "Example", "properties": {"status": ["Todo"]}},
        ),
        ("PATCH", "/collections/col/items/row", {"properties": {"status": None}}),
        ("PATCH", "/collections/col/items/row", {"properties": {}}),
    ],
)
def test_invalid_writes_never_reach_craft(daily_settings, method, path, body):
    with TestClient(
        create_app(daily_settings, daily_upstream_transport=httpx.MockTransport(unexpected))
    ) as client:
        response = client.request(method, "/v1/daily" + path, json=body, headers=AUTH)
    assert response.status_code == 422


CONNECTION_MODES = [mode for mode in product((False, True), repeat=3) if any(mode)]


@pytest.mark.parametrize("space,documents,daily", CONNECTION_MODES)
@pytest.mark.parametrize("preset", ["full", "read_only"])
def test_all_connection_modes_and_openapi(space, documents, daily, preset):
    settings = Settings(
        _env_file=None,
        craft_space_base_url="https://connect.craft.do/links/space-test-secret/api/v1"
        if space
        else None,
        craft_documents_base_url="https://connect.craft.do/links/documents-test-secret/api/v1"
        if documents
        else None,
        craft_daily_base_url=DAILY_URL if daily else None,
        wrapper_api_token="test-wrapper-token",
        wrapper_enabled_operations=preset,
    )
    full = (
        (SPACE_OPERATION_IDS if space else frozenset())
        | (DOCUMENTS_OPERATION_IDS if documents else frozenset())
        | (DAILY_OPERATION_IDS if daily else frozenset())
    )
    reads = SPACE_READ_OPERATION_IDS | DOCUMENTS_READ_OPERATION_IDS | DAILY_READ_OPERATION_IDS
    expected = full if preset == "full" else full & reads
    app = create_app(
        settings,
        upstream_transport=httpx.MockTransport(unexpected),
        documents_upstream_transport=httpx.MockTransport(unexpected),
        daily_upstream_transport=httpx.MockTransport(unexpected),
    )
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        spec = client.get("/openapi.json").json()
        for present, path in (
            (space, "/v1/space/documents"),
            (documents, "/v1/documents/documents"),
            (daily, "/v1/daily/notes"),
        ):
            assert client.get(path).status_code == (401 if present else 404)
        if preset == "read_only" or not daily:
            assert client.delete("/v1/daily/tasks/task", headers=AUTH).status_code == 404
            assert (
                client.post(
                    "/v1/daily/notes/content", json={"markdown": "New"}, headers=AUTH
                ).status_code
                == 404
            )
    validate(spec)
    ops = [op for path in spec["paths"].values() for op in path.values()]
    assert len(ops) == len(expected)
    assert {op["operationId"] for op in ops} == expected
    assert all(op["security"] == [{"WrapperBearer": []}] for op in ops)
    assert all(op["description"] and op["summary"] for op in ops)
    assert spec["openapi"] == "3.1.0"
    for op in ops:
        for status in ("400", "401", "404", "409", "413", "422", "429", "500", "502", "503", "504"):
            assert op["responses"][status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
    assert all(secret not in json.dumps(spec) for secret in settings.secrets)
    if daily:
        schemas = spec["components"]["schemas"]
        assert schemas["DailyCollectionSummary"]["required"] == [
            "id",
            "name",
            "itemCount",
            "dailyNoteDate",
        ]
        if preset == "full":
            assert schemas["UpdateTask"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://example.com/api/v1",
        "http://connect.craft.do/links/secret/api/v1",
        "https://connect.craft.do/links/REPLACE_ME/api/v1",
        "https://connect.craft.do/links/secret/api/v1?token=x",
    ],
)
def test_daily_url_validation(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, craft_daily_base_url=url, wrapper_api_token="test-wrapper-token")


def test_explicit_allowlist_requires_daily_connection_and_limits_routes(daily_settings):
    with pytest.raises(ValidationError, match="configured Craft connection"):
        Settings(
            _env_file=None,
            craft_space_base_url="https://connect.craft.do/links/space/api/v1",
            wrapper_api_token="test-wrapper-token",
            wrapper_enabled_operations="craft_daily_get_note",
        )
    daily_settings.wrapper_enabled_operations = "craft_daily_list_tasks"
    with TestClient(
        create_app(daily_settings, daily_upstream_transport=httpx.MockTransport(unexpected))
    ) as client:
        assert client.get("/v1/daily/notes", headers=AUTH).status_code == 404
        assert (
            client.post("/v1/daily/tasks", json={"markdown": "Example"}, headers=AUTH).status_code
            == 404
        )
        assert client.get("/v1/daily/tasks", params={"scope": "inbox"}).status_code == 401


@pytest.mark.parametrize("scope", ["active", "upcoming", "inbox", "logbook"])
def test_task_scopes_forwarded(daily_settings, scope):
    def handler(request):
        assert dict(request.url.params) == {"scope": scope}
        return httpx.Response(200, json={"items": []})

    with TestClient(
        create_app(daily_settings, daily_upstream_transport=httpx.MockTransport(handler))
    ) as client:
        assert client.get("/v1/daily/tasks", params={"scope": scope}, headers=AUTH).json() == {
            "items": []
        }


@pytest.mark.parametrize(
    "upstream,status,code",
    [
        (400, 400, "craft_rejected_request"),
        (422, 400, "craft_rejected_request"),
        (401, 502, "craft_access_error"),
        (403, 502, "craft_access_error"),
        (404, 404, "craft_not_found"),
        (409, 409, "craft_conflict"),
        (429, 429, "craft_rate_limited"),
        (503, 502, "craft_upstream_error"),
        (302, 502, "craft_upstream_error"),
    ],
)
@pytest.mark.parametrize("write", [False, True])
def test_errors_and_redaction_never_fall_back(
    daily_settings, upstream, status, code, write, caplog
):
    daily_settings.craft_space_base_url = SecretStr(DAILY_URL.replace("daily-test", "space-test"))
    daily_settings.craft_documents_base_url = SecretStr(
        DAILY_URL.replace("daily-test", "documents-test")
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            upstream,
            json={"error": {"code": "EXAMPLE", "message": " ".join(daily_settings.secrets)}},
            headers={"Retry-After": "60"},
        )

    caplog.set_level(logging.INFO)
    with TestClient(
        create_app(
            daily_settings,
            daily_upstream_transport=httpx.MockTransport(handler),
            upstream_transport=httpx.MockTransport(unexpected),
            documents_upstream_transport=httpx.MockTransport(unexpected),
        )
    ) as client:
        response = (
            client.delete("/v1/daily/tasks/task", headers=AUTH)
            if write
            else client.get("/v1/daily/notes", headers=AUTH)
        )
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert error["upstreamStatus"] == upstream
    assert error["upstreamCode"] == "EXAMPLE"
    assert error["retryAfterSeconds"] == 60
    assert error.get("outcomeUnknown", False) == write
    assert all(secret not in response.text + caplog.text for secret in daily_settings.secrets)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/tasks", {"markdown": "Example"}),
        ("PATCH", "/tasks/task", {"state": "done"}),
        ("DELETE", "/tasks/task", None),
        ("POST", "/collections/col/items", {"title": "Example"}),
        ("PATCH", "/collections/col/items/row", {"properties": {"status": "Done"}}),
        ("PATCH", "/blocks/text", {"markdown": "Updated"}),
    ],
)
@pytest.mark.parametrize(
    "items", [[], [{"id": "one", "type": "text"}, {"id": "two", "type": "text"}]]
)
def test_uncertain_singleton_results(daily_settings, method, path, body, items):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"items": items})

    with TestClient(
        create_app(daily_settings, daily_upstream_transport=httpx.MockTransport(handler))
    ) as client:
        response = client.request(method, "/v1/daily" + path, json=body, headers=AUTH)
    assert response.status_code == 502
    assert response.json()["error"]["outcomeUnknown"] is True
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure,status,code",
    [
        ("timeout", 504, "craft_timeout"),
        ("network", 503, "craft_unavailable"),
        ("malformed", 502, "craft_upstream_error"),
        ("non_json", 502, "craft_upstream_error"),
        ("shape", 502, "craft_upstream_error"),
        ("oversize", 502, "craft_response_too_large"),
        ("internal", 500, "internal_error"),
    ],
)
@pytest.mark.parametrize("write", [False, True])
def test_daily_failure_bounds_and_no_retries(daily_settings, failure, status, code, write):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout(DAILY_URL)
        if failure == "network":
            raise httpx.ConnectError(DAILY_URL)
        if failure == "internal":
            raise RuntimeError(DAILY_URL)
        if failure == "malformed":
            return httpx.Response(200, content=b"{", headers={"content-type": "application/json"})
        if failure == "non_json":
            return httpx.Response(200, text="Private content")
        if failure == "shape":
            return httpx.Response(200, json={"unexpected": "shape"})
        return httpx.Response(200, json={"id": "root", "type": "page"})

    app = create_app(daily_settings, daily_upstream_transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        if failure == "oversize":
            app.state.daily_client.transport.max_response_bytes = 4
        response = (
            client.delete("/v1/daily/tasks/task", headers=AUTH)
            if write
            else client.get("/v1/daily/notes", headers=AUTH)
        )
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    if write and failure != "internal":
        assert error["outcomeUnknown"] is True
    assert DAILY_URL not in response.text
    assert len(calls) == 1


def test_incoming_limit_and_independent_lifecycles(daily_settings):
    daily_settings.craft_space_base_url = SecretStr(DAILY_URL.replace("daily-test", "space-test"))
    daily_settings.craft_documents_base_url = SecretStr(
        DAILY_URL.replace("daily-test", "documents-test")
    )
    app = create_app(
        daily_settings,
        daily_upstream_transport=httpx.MockTransport(unexpected),
        upstream_transport=httpx.MockTransport(unexpected),
        documents_upstream_transport=httpx.MockTransport(unexpected),
    )
    with TestClient(app) as client:
        clients = [
            app.state.space_client.transport.client,
            app.state.documents_client.transport.client,
            app.state.daily_client.transport.client,
        ]
        assert len({id(c) for c in clients}) == 3
        assert not any(c.is_closed for c in clients)
        response = client.post(
            "/v1/daily/tasks",
            content='{"markdown":"' + "a" * (1024 * 1024) + '"}',
            headers=AUTH | {"Content-Type": "application/json"},
        )
        assert response.status_code == 413
    assert all(c.is_closed for c in clients)

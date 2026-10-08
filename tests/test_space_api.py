import asyncio
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from craft_wrapper.api.space import get_client
from craft_wrapper.main import create_app

AUTH = {"Authorization": "Bearer test-wrapper-token"}
PREFIX = "/v1/space"


def test_live_schema_shape_and_select_value_cardinality(settings):
    schema = {
        "name": "Example collection",
        "properties": [
            {
                "key": "decision",
                "name": "Decision",
                "type": "singleSelect",
                "options": [{"name": "Yes", "color": "green"}, {"name": "No"}],
            }
        ],
    }
    items = {"items": [{"id": "example-item", "properties": {"decision": "Yes", "tags": ["A"]}}]}
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json=schema)
        assert request.url.path.endswith("/items")
        return httpx.Response(200, json=items)

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        path = PREFIX + "/collections/example-collection"
        response = client.get(path + "/schema", headers=AUTH)
        assert response.status_code == 200
        assert response.json() == schema
        response = client.get(path + "/items", headers=AUTH)
        assert response.status_code == 200
        assert response.json() == items
    assert len(calls) == 3


@pytest.mark.parametrize(
    "depth,payload",
    [
        (
            0,
            {
                "id": "root",
                "type": "text",
                "markdown": "# Example page",
                "contentPreviewMd": "Nested content preview",
            },
        ),
        (
            0,
            {
                "id": "root",
                "type": "collection",
                "markdown": "Example collection",
                "itemsPreviewMd": "Collection rows preview",
            },
        ),
        (
            -1,
            {
                "id": "root",
                "type": "text",
                "content": [
                    {
                        "id": "collection",
                        "type": "collection",
                        "items": [
                            {
                                "id": "row",
                                "type": "collectionItem",
                                "title": "Example row",
                                "markdown": "Example row Markdown",
                                "properties": {"status": "Yes", "tags": ["A"], "number": 2.5},
                                "content": [
                                    {"id": "row-text", "type": "text", "markdown": "Row content"}
                                ],
                            },
                            {"id": "untitled-row", "properties": {}},
                        ],
                    }
                ],
            },
        ),
    ],
)
def test_structured_reads_preserve_collection_rows_and_previews(settings, depth, payload):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path == "/links/testing-link-secret/api/v1/blocks"
        assert dict(request.url.params) == {"id": "root", "maxDepth": str(depth)}
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(200, json=payload)

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        response = client.get(PREFIX + f"/blocks/root?maxDepth={depth}", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == payload
    assert len(calls) == 1


@pytest.mark.parametrize("endpoint", ["/documents", "/documents/search"])
@pytest.mark.parametrize(
    "bounds", [{"dailyNoteDateGte": "yesterday"}, {"dailyNoteDateLte": "today"}]
)
def test_daily_note_bounds_forwarded_with_endpoint_specific_scope(settings, endpoint, bounds):
    calls = []
    listing = endpoint == "/documents"
    params = {**bounds, **({"location": "daily_notes"} if listing else {"query": "e"})}

    def handler(request):
        calls.append(request)
        expected = {
            **bounds,
            **(
                {"location": "daily_notes", "fetchMetadata": "false"}
                if listing
                else {"include": "e", "fetchBlocks": "false"}
            ),
        }
        assert dict(request.url.params) == expected
        return httpx.Response(200, json={"items": []})

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        response = client.get(PREFIX + endpoint, params=params, headers=AUTH)
    assert response.status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize(
    "scope", [None, "folderId=folder", "location=unsorted", "location=trash", "location=templates"]
)
@pytest.mark.parametrize("bound", ["dailyNoteDateGte", "dailyNoteDateLte"])
def test_listing_daily_note_bounds_reject_incompatible_scopes(settings, scope, bound):
    def handler(request):
        pytest.fail("Invalid daily-note scope must not reach Craft")

    query = f"{bound}=today" + (f"&{scope}" if scope else "")
    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        response = client.get(PREFIX + "/documents?" + query, headers=AUTH)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any("require location=daily_notes" in d["message"] for d in error["details"])


# Independent public/upstream contracts: no implementation metadata drives these cases.
CASES = [
    ("GET", "/folders", None, "GET /folders", {}, None, 200),
    (
        "GET",
        "/documents?location=unsorted&fetchMetadata=true&createdDateGte=today",
        None,
        "GET /documents",
        {"location": "unsorted", "fetchMetadata": "true", "createdDateGte": "today"},
        None,
        200,
    ),
    (
        "GET",
        "/documents/search?query=API&documentId=doc-123",
        None,
        "GET /documents/search",
        {"include": "API", "documentIds": "doc-123", "fetchBlocks": "false"},
        None,
        200,
    ),
    (
        "POST",
        "/documents",
        {"title": "New Document 1", "folderId": "f"},
        "POST /documents",
        {},
        {"documents": [{"title": "New Document 1"}], "destination": {"folderId": "f"}},
        201,
    ),
    ("GET", "/blocks/0", None, "GET /blocks", {"id": "0", "maxDepth": "1"}, None, 200),
    (
        "GET",
        "/blocks/0/markdown?maxDepth=-1",
        None,
        "GET /blocks",
        {"id": "0", "maxDepth": "-1"},
        None,
        200,
    ),
    (
        "POST",
        "/blocks/0/content",
        {"markdown": "Hello", "position": "start"},
        "POST /blocks",
        {},
        {"markdown": "Hello", "position": {"pageId": "0", "position": "start"}},
        201,
    ),
    (
        "PATCH",
        "/blocks/5",
        {"markdown": "Updated"},
        "PUT /blocks",
        {},
        {"blocks": [{"id": "5", "markdown": "Updated"}]},
        200,
    ),
    (
        "GET",
        "/collections?documentId=doc1",
        None,
        "GET /collections",
        {"documentIds": "doc1"},
        None,
        200,
    ),
    (
        "GET",
        "/collections/col1/schema",
        None,
        "GET /collections/{collectionId}/schema",
        {"format": "schema"},
        None,
        200,
    ),
    (
        "GET",
        "/collections/col1/items",
        None,
        "GET /collections/{collectionId}/items",
        {"maxDepth": "0"},
        None,
        200,
    ),
    (
        "POST",
        "/collections/col1/items",
        {"title": "New Task", "properties": {"status": "Todo"}},
        "POST /collections/{collectionId}/items",
        {},
        {"items": [{"title": "New Task", "properties": {"status": "Todo"}}]},
        201,
    ),
    (
        "PATCH",
        "/collections/col1/items/item1",
        {"properties": {"status": "Done"}},
        "PUT /collections/{collectionId}/items",
        {},
        {"itemsToUpdate": [{"id": "item1", "properties": {"status": "Done"}}]},
        200,
    ),
]


@pytest.mark.parametrize("method,path,body,operation,params,upstream_body,status", CASES)
def test_all_endpoint_contracts(
    settings, fixtures, method, path, body, operation, params, upstream_body, status
):
    calls = []

    def handler(request):
        calls.append(request)
        expected_method, expected_path = operation.split(" ")
        if expected_path.endswith("/items") and request.url.path.endswith("/schema"):
            assert request.method == "GET"
            assert dict(request.url.params) == {"format": "schema"}
            return httpx.Response(200, json=fixtures["GET /collections/{collectionId}/schema"])
        assert request.method == expected_method
        assert request.url.path == "/links/testing-link-secret/api/v1" + expected_path.replace(
            "{collectionId}", "col1"
        )
        assert dict(request.url.params) == params
        assert "authorization" not in request.headers
        assert (
            json.loads(request.content) == upstream_body
            if upstream_body is not None
            else not request.content
        )
        if "/markdown" in path:
            assert request.headers["Accept"] == "text/markdown"
            return httpx.Response(
                200, text="# Root\nContent", headers={"Content-Type": "text/markdown"}
            )
        assert request.headers["Accept"] == "application/json"
        payload = fixtures[operation]
        if operation in {"POST /documents", "PUT /blocks"}:
            payload = {"items": payload["items"][:1]}
        return httpx.Response(200, json=payload)

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        response = client.request(method, PREFIX + path, json=body, headers=AUTH)
    assert response.status_code == status, response.text
    assert len(calls) == (2 if operation.endswith("/items") else 1)
    payload = response.json()
    if "/markdown" in path:
        assert payload == {"blockId": "0", "markdown": "# Root\nContent"}
    elif method in {"POST", "PATCH"} and "/content" not in path:
        assert "id" in payload
        assert "items" not in payload
    elif operation.endswith("/schema"):
        assert payload["properties"][0]["type"] == "select"
        assert "propertyDetails" not in payload


INVALID = [
    ("GET", "/documents?location=trash&folderId=f", None),
    ("GET", "/documents?location=nowhere", None),
    ("GET", "/documents?folderId=", None),
    ("GET", "/documents?createdDateGte=2025-02-30", None),
    ("GET", "/documents?createdDateGte=2025-03-01&createdDateLte=2025-02-01", None),
    ("GET", "/documents?offset=5", None),
    ("GET", "/documents?fetchMetadata=maybe", None),
    ("GET", "/documents/search?query=x&folderId=f&documentId=d", None),
    ("GET", "/documents/search?query=x&location=trash&documentId=d", None),
    ("GET", "/documents/search?query=x&regexps=x", None),
    ("GET", "/documents/search", None),
    ("GET", "/documents/search?query=", None),
    ("GET", "/blocks/p?maxDepth=-2", None),
    ("GET", "/blocks/p?maxDepth=1.5", None),
    ("GET", "/collections/c/items?maxDepth=-2", None),
    ("GET", "/collections?documentIds=a,b", None),
    ("POST", "/documents", {"title": "x", "location": "trash"}),
    ("POST", "/documents", {"title": "x", "location": "unsorted", "folderId": "f"}),
    ("POST", "/documents", {"title": 1}),
    ("POST", "/documents", {"title": ""}),
    ("POST", "/documents", {"title": "x", "extra": "test-wrapper-token"}),
    ("POST", "/blocks/p/content", {"markdown": "x", "position": "before"}),
    ("POST", "/blocks/p/content", {"markdown": ""}),
    ("PATCH", "/blocks/b", {"markdown": 3}),
    ("PATCH", "/blocks/b", {"markdown": "x", "font": "serif"}),
    ("POST", "/collections/c/items", {"title": "x", "properties": {"priority": 2}}),
    ("POST", "/collections/c/items", {"title": "x", "properties": {"flag": True}}),
    ("POST", "/collections/c/items", {"title": "x", "properties": {"relation": ["i"]}}),
    ("PATCH", "/collections/c/items/i", {"properties": {"status": None}}),
    ("PATCH", "/collections/c/items/i", {"properties": {}}),
    ("PATCH", "/collections/c/items/i", {"properties": {"": "value"}}),
    ("PATCH", "/collections/c/items/i", {"properties": {"status": "Todo"}, "title": "x"}),
]


@pytest.mark.parametrize("method,path,body", INVALID)
def test_validation_never_calls_craft(settings, method, path, body):
    def handler(request):
        pytest.fail("Invalid requests must not reach Craft")

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        response = client.request(method, PREFIX + path, json=body, headers=AUTH)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["requestId"] == response.headers["X-Request-Id"]
    assert "test-wrapper-token" not in response.text


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic dXNlcjpwYXNz"}]
)
def test_authentication(settings, headers):
    def handler(request):
        pytest.fail("Unauthenticated requests must not reach Craft")

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        response = client.get(PREFIX + "/documents", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"


def test_health_schema_and_docs_no_upstream(settings):
    def handler(request):
        pytest.fail("Infrastructure endpoints must not reach Craft")

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200


@pytest.mark.parametrize("path", ["/collections/example/items", "/blocks/example?maxDepth=-1"])
def test_collection_date_strings_preserved_in_item_and_block_reads(settings, path):
    row = {
        "id": "example-row",
        "type": "collectionItem",
        "title": "Example row",
        "properties": {"due": "2025-01-15"},
    }
    payload = (
        {"items": [row]}
        if path.startswith("/collections/")
        else {"id": "example", "type": "collection", "items": [row]}
    )

    def handler(request):
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json={"name": "Example", "properties": []})
        assert request.method == "GET"
        return httpx.Response(200, json=payload)

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        response = client.get(PREFIX + path, headers=AUTH)
    assert response.status_code == 200
    assert response.json() == payload


def test_collection_date_update_and_restore_round_trip(settings):
    properties = {"due": "2025-01-15", "status": "Done"}
    expected_dates = iter(["2025-01-16", "2025-01-15"])
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.url.path.endswith("/schema"):
            assert dict(request.url.params) == {"format": "schema"}
            return httpx.Response(200, json={"name": "Example", "properties": []})
        assert request.url.path.endswith("/collections/example/items")
        if request.method == "PUT":
            target_date = next(expected_dates)
            assert json.loads(request.content) == {
                "itemsToUpdate": [{"id": "example-row", "properties": {"due": target_date}}]
            }
            properties["due"] = target_date
        else:
            assert request.method == "GET"
            assert dict(request.url.params) == {"maxDepth": "0"}
        return httpx.Response(
            200, json={"items": [{"id": "example-row", "properties": properties}]}
        )

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        path = PREFIX + "/collections/example/items"
        for target_date in ("2025-01-16", "2025-01-15"):
            response = client.patch(
                path + "/example-row", headers=AUTH, json={"properties": {"due": target_date}}
            )
            assert response.status_code == 200
            expected = {"id": "example-row", "properties": {"due": target_date, "status": "Done"}}
            assert response.json() == expected
            response = client.get(path, headers=AUTH)
            assert response.status_code == 200
            assert response.json() == {"items": [expected]}
    assert calls == ["GET", "PUT", "GET", "GET", "GET", "PUT", "GET", "GET"]


def test_dynamic_collection_values_and_sparse_update(settings):
    def handler(request):
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json={"name": "Example", "properties": []})
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "i",
                            "properties": {
                                "number": 2,
                                "bool": True,
                                "empty": None,
                                "nested": {"ids": ["a", "b"]},
                            },
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"items": [{"id": "i", "properties": {"status": "Done"}}]})

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        properties = client.get(PREFIX + "/collections/c/items", headers=AUTH).json()["items"][0][
            "properties"
        ]
        assert properties == {
            "number": 2,
            "bool": True,
            "empty": None,
            "nested": {"ids": ["a", "b"]},
        }
        response = client.patch(
            PREFIX + "/collections/c/items/i", headers=AUTH, json={"properties": {"status": "Done"}}
        )
        assert response.json() == {"id": "i", "properties": {"status": "Done"}}


def test_default_writes_and_nested_blocks_workflow(settings):
    steps = []

    def handler(request):
        steps.append((request.method, request.url.path.rsplit("/", 1)[-1]))
        if len(steps) == 1:
            return httpx.Response(200, json={"items": [{"id": "doc", "title": "Doc"}]})
        if len(steps) == 2:
            assert request.url.params["maxDepth"] == "1"
            return httpx.Response(
                200,
                json={
                    "id": "doc",
                    "type": "page",
                    "content": [
                        {
                            "id": "nested",
                            "type": "page",
                            "content": [
                                {
                                    "id": "old",
                                    "type": "text",
                                    "markdown": "[Hidden](invalid:out_of_scope)",
                                }
                            ],
                        }
                    ],
                },
            )
        if len(steps) == 3:
            assert json.loads(request.content)["position"] == {"position": "end", "pageId": "doc"}
            return httpx.Response(
                200, json={"items": [{"id": "new", "type": "text", "markdown": "Added"}]}
            )
        assert json.loads(request.content) == {"blocks": [{"id": "new", "markdown": "Edited"}]}
        return httpx.Response(
            200, json={"items": [{"id": "new", "type": "text", "markdown": "Edited"}]}
        )

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        document = client.get(PREFIX + "/documents", headers=AUTH).json()["items"][0]
        block = client.get(PREFIX + "/blocks/" + document["id"], headers=AUTH).json()
        assert block["content"][0]["content"][0]["markdown"] == "[Hidden](invalid:out_of_scope)"
        inserted = client.post(
            PREFIX + "/blocks/doc/content", headers=AUTH, json={"markdown": "Added"}
        )
        identifier = inserted.json()["items"][0]["id"]
        updated = client.patch(
            PREFIX + "/blocks/" + identifier, headers=AUTH, json={"markdown": "Edited"}
        )
        assert updated.json()["markdown"] == "Edited"
    assert len(steps) == 4


def test_collection_workflow(settings, fixtures):
    steps = []

    def handler(request):
        steps.append(request)
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json=fixtures["GET /collections/{collectionId}/schema"])
        if len(steps) == 1:
            return httpx.Response(200, json=fixtures["GET /collections"])
        if len(steps) == 2:
            return httpx.Response(200, json=fixtures["GET /collections/{collectionId}/schema"])
        if request.method == "POST":
            assert json.loads(request.content) == {
                "items": [{"title": "Task", "properties": {"status": "Not Started"}}]
            }
            return httpx.Response(200, json={"items": [{"id": "new", "title": "Task"}]})
        assert json.loads(request.content) == {
            "itemsToUpdate": [{"id": "new", "properties": {"status": "Completed"}}]
        }
        return httpx.Response(200, json={"items": [{"id": "new"}]})

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        collection = client.get(PREFIX + "/collections", headers=AUTH).json()["items"][0]["id"]
        path = PREFIX + "/collections/" + collection
        schema = client.get(path + "/schema", headers=AUTH).json()
        prop = schema["properties"][0]
        added = client.post(
            path + "/items",
            headers=AUTH,
            json={"title": "Task", "properties": {prop["key"]: prop["options"][0]}},
        )
        updated = client.patch(
            path + "/items/" + added.json()["id"],
            headers=AUTH,
            json={"properties": {prop["key"]: prop["options"][-1]}},
        )
        assert updated.json() == {"id": "new"}
    assert len(steps) == 6


def test_rate_error_envelope_and_safe_logs(settings, caplog):
    def handler(request):
        return httpx.Response(
            429,
            json={
                "error": {
                    "code": "LIMIT",
                    "message": "testing-link-secret test-wrapper-token "
                    "Authorization: Bearer extra-secret",
                }
            },
            headers={"Retry-After": "4"},
        )

    caplog.set_level(logging.INFO)
    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        response = client.post(
            PREFIX + "/documents", headers=AUTH, json={"title": "private document content"}
        )
    error = response.json()["error"]
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "4"
    assert error["upstreamStatus"] == 429
    assert error["upstreamCode"] == "LIMIT"
    assert error["retryAfterSeconds"] == 4
    assert error["outcomeUnknown"]
    for value in (
        "testing-link-secret",
        "test-wrapper-token",
        "extra-secret",
        "private document content",
    ):
        assert value not in response.text + caplog.text
    assert "craft_space_create_document" in caplog.text
    assert "upstreamStatus=429" in caplog.text


def test_oversized_and_malformed_body(settings):
    with TestClient(create_app(settings)) as client:
        oversized = client.post(
            PREFIX + "/documents", headers=AUTH, content=b"x" * (1024 * 1024 + 1)
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "request_too_large"
        malformed = client.post(
            PREFIX + "/documents",
            headers={**AUTH, "Content-Type": "application/json"},
            content="{broken}",
        )
        assert malformed.status_code == 422


def test_chunked_request_size_cannot_bypass_limit(settings):
    app = create_app(settings)
    messages = [
        {"type": "http.request", "body": b"x" * (600 * 1024), "more_body": True},
        {"type": "http.request", "body": b"x" * (600 * 1024), "more_body": False},
    ]
    responses = []

    async def run():
        async def receive():
            return messages.pop(0)

        async def send(message):
            responses.append(message)

        await app(
            {
                "type": "http",
                "method": "POST",
                "path": PREFIX + "/documents",
                "headers": [],
                "query_string": b"",
                "scheme": "http",
                "server": ("test", 80),
                "client": ("test", 1),
                "root_path": "",
                "http_version": "1.1",
            },
            receive,
            send,
        )

    asyncio.run(run())
    assert responses[0]["status"] == 413


def test_internal_exception_is_sanitized(settings, caplog):
    def explode():
        raise RuntimeError("test-wrapper-token private payload")

    app = create_app(settings)
    app.dependency_overrides[get_client] = explode
    with TestClient(app) as client:
        response = client.get(PREFIX + "/documents", headers=AUTH)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "test-wrapper-token" not in response.text + caplog.text
    assert "private payload" not in response.text + caplog.text


def test_upstream_client_closes_at_shutdown(settings):
    app = create_app(settings)
    with TestClient(app):
        http = app.state.space_client.transport.client
        assert not http.is_closed
    assert http.is_closed

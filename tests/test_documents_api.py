import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from pydantic import ValidationError

from craft_wrapper.config import (
    DOCUMENTS_OPERATION_IDS,
    DOCUMENTS_READ_OPERATION_IDS,
    SPACE_OPERATION_IDS,
    SPACE_READ_OPERATION_IDS,
    Settings,
)
from craft_wrapper.main import create_app

AUTH = {"Authorization": "Bearer test-wrapper-token"}
PREFIX = "/v1/documents"
DOCS_URL = "https://connect.craft.do/links/documents-test-secret/api/v1"
DOCUMENTS = {
    "items": [
        {
            "id": "root-slug",
            "title": "Example",
            "isDeleted": False,
            "createdAt": "2026-10-01T12:00:00Z",
            "clickableLink": "craftdocs://open?documentId=app-only-id",
        },
        {"id": "deleted-slug", "title": "[Deleted Document]", "isDeleted": True},
    ]
}
BLOCK = {
    "id": "root-slug",
    "type": "page",
    "content": [
        {
            "id": "text-slug",
            "type": "text",
            "markdown": "[Scoped](invalid:out_of_scope)",
            "content": [{"id": "nested", "type": "text", "markdown": "Nested"}],
        },
    ],
}
SCHEMA = {
    "name": "Example",
    "properties": [
        {
            "key": "status",
            "name": "Status",
            "type": "select",
            "options": ["Todo", {"name": "Done", "color": "green"}],
        },
    ],
}
ITEM = {
    "id": "row-slug",
    "title": "Example",
    "properties": {
        "status": "Todo",
        "tags": ["A"],
        "number": 2.5,
        "relation": {"url": "invalid:out_of_scope"},
    },
    "content": [{"id": "row-text", "type": "text", "markdown": "Details"}],
}


@pytest.fixture
def documents_settings():
    return Settings(
        _env_file=None,
        craft_space_base_url=None,
        craft_documents_base_url=DOCS_URL,
        wrapper_api_token="test-wrapper-token",
    )


def unexpected(request):
    pytest.fail("Request must not reach this Craft connection")


# Verify both the public adaptation and exact upstream contract for every operation.
@pytest.mark.parametrize(
    "method,path,query,body,upstream_method,upstream_path,upstream_query,upstream_body,payload,expected",
    [
        (
            "GET",
            "/documents",
            {},
            None,
            "GET",
            "documents",
            {"fetchMetadata": "false"},
            None,
            DOCUMENTS,
            DOCUMENTS,
        ),
        (
            "GET",
            "/documents",
            {"fetchMetadata": True},
            None,
            "GET",
            "documents",
            {"fetchMetadata": "true"},
            None,
            DOCUMENTS,
            DOCUMENTS,
        ),
        (
            "GET",
            "/documents/search",
            {
                "query": "a & b",
                "documentId": "root-slug",
                "documentFilterMode": "exclude",
                "fetchBlocks": True,
            },
            None,
            "GET",
            "documents/search",
            {
                "include": "a & b",
                "documentIds": "root-slug",
                "documentFilterMode": "exclude",
                "fetchBlocks": "true",
            },
            None,
            {
                "items": [
                    {
                        "documentId": "root-slug",
                        "markdown": "Match",
                        "blockIds": ["text-slug"],
                        "blocks": [BLOCK],
                    }
                ]
            },
            {
                "items": [
                    {
                        "documentId": "root-slug",
                        "markdown": "Match",
                        "blockIds": ["text-slug"],
                        "blocks": [BLOCK],
                    }
                ]
            },
        ),
        (
            "GET",
            "/documents/search",
            {"query": "match", "documentId": "root-slug"},
            None,
            "GET",
            "documents/search",
            {
                "include": "match",
                "documentIds": "root-slug",
                "documentFilterMode": "include",
                "fetchBlocks": "false",
            },
            None,
            {"items": []},
            {"items": []},
        ),
        (
            "GET",
            "/blocks/root-slug",
            {},
            None,
            "GET",
            "blocks",
            {"id": "root-slug", "maxDepth": "1"},
            None,
            BLOCK,
            BLOCK,
        ),
        (
            "GET",
            "/blocks/root-slug/markdown",
            {"maxDepth": -1},
            None,
            "GET",
            "blocks",
            {"id": "root-slug", "maxDepth": "-1"},
            None,
            "[Scoped](invalid:out_of_scope)",
            {"blockId": "root-slug", "markdown": "[Scoped](invalid:out_of_scope)"},
        ),
        (
            "POST",
            "/blocks/root-slug/content",
            {},
            {"markdown": "Hello"},
            "POST",
            "blocks",
            {},
            {"markdown": "Hello", "position": {"pageId": "root-slug", "position": "end"}},
            {"items": [BLOCK]},
            {"items": [BLOCK]},
        ),
        (
            "PATCH",
            "/blocks/text-slug",
            {},
            {"markdown": ""},
            "PUT",
            "blocks",
            {},
            {"blocks": [{"id": "text-slug", "markdown": ""}]},
            {"items": [BLOCK]},
            BLOCK,
        ),
        (
            "GET",
            "/collections",
            {"documentId": "root-slug"},
            None,
            "GET",
            "collections",
            {"documentIds": "root-slug", "documentFilterMode": "include"},
            None,
            {
                "items": [
                    {
                        "id": "collection-slug",
                        "name": "Example",
                        "itemCount": 1,
                        "documentId": "root-slug",
                    }
                ]
            },
            {
                "items": [
                    {
                        "id": "collection-slug",
                        "name": "Example",
                        "itemCount": 1,
                        "documentId": "root-slug",
                    }
                ]
            },
        ),
        (
            "GET",
            "/collections/collection-slug/schema",
            {},
            None,
            "GET",
            "collections/collection-slug/schema",
            {"format": "schema"},
            None,
            SCHEMA,
            SCHEMA,
        ),
        (
            "GET",
            "/collections/collection-slug/items",
            {},
            None,
            "GET",
            "collections/collection-slug/items",
            {"maxDepth": "0"},
            None,
            {"items": [ITEM]},
            {"items": [ITEM]},
        ),
        (
            "POST",
            "/collections/collection-slug/items",
            {},
            {"title": "Example"},
            "POST",
            "collections/collection-slug/items",
            {},
            {"items": [{"title": "Example", "properties": {}}]},
            {"items": [ITEM]},
            ITEM,
        ),
        (
            "PATCH",
            "/collections/collection-slug/items/row-slug",
            {},
            {"properties": {"status": "Done"}},
            "PUT",
            "collections/collection-slug/items",
            {},
            {"itemsToUpdate": [{"id": "row-slug", "properties": {"status": "Done"}}]},
            {"items": [ITEM]},
            ITEM,
        ),
    ],
)
def test_operation_contracts(
    documents_settings,
    method,
    path,
    query,
    body,
    upstream_method,
    upstream_path,
    upstream_query,
    upstream_body,
    payload,
    expected,
):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/links/documents-test-secret/api/v1/" + upstream_path
        assert request.method == upstream_method
        assert dict(request.url.params) == upstream_query
        assert "authorization" not in request.headers
        assert (json.loads(request.content) if request.content else None) == upstream_body
        if isinstance(payload, str):
            assert request.headers["accept"] == "text/markdown"
            return httpx.Response(200, text=payload, headers={"Content-Type": "text/markdown"})
        assert request.headers["accept"] == "application/json"
        return httpx.Response(200, json=payload)

    with TestClient(
        create_app(
            documents_settings,
            upstream_transport=httpx.MockTransport(unexpected),
            documents_upstream_transport=httpx.MockTransport(handler),
        )
    ) as client:
        response = client.request(method, PREFIX + path, params=query, json=body, headers=AUTH)
    assert response.status_code == (201 if method == "POST" else 200)
    assert response.json() == expected
    assert len(calls) == 1


@pytest.mark.parametrize(
    "path,params",
    [
        ("/documents", {"documentId": "root"}),
        ("/documents", {"folderId": "folder"}),
        ("/documents", {"location": "unsorted"}),
        ("/documents", {"createdDateGte": "today"}),
        ("/documents/search", {"query": "q", "dailyNoteDateGte": "today"}),
        ("/documents/search", {"query": "q", "folderId": "folder"}),
        ("/documents/search", {"query": "q", "location": "unsorted"}),
        ("/documents/search", {"query": "q", "regexps": "q"}),
        ("/documents/search", {"query": ""}),
        ("/documents/search", {}),
        ("/documents/search", {"query": "q", "documentFilterMode": "exclude"}),
        ("/collections", {"documentFilterMode": "include"}),
        ("/collections", {"documentId": "root", "documentFilterMode": "other"}),
        ("/collections", {"documentId": ""}),
        ("/blocks/root", {"maxDepth": -2}),
        ("/blocks/root", {"maxDepth": "deep"}),
        ("/collections/c/items", {"maxDepth": -2}),
    ],
)
def test_invalid_filters_never_reach_craft(documents_settings, path, params):
    with TestClient(
        create_app(documents_settings, documents_upstream_transport=httpx.MockTransport(unexpected))
    ) as client:
        response = client.get(PREFIX + path, params=params, headers=AUTH)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "body",
    [
        {"properties": {}},
        {"properties": {"p": None}},
        {"properties": {"p": ["A"]}},
        {"properties": {"p": 1}},
        {"properties": {"p": {"id": "r"}}},
        {"title": "unsupported", "properties": {"p": "A"}},
    ],
)
def test_string_write_boundary(documents_settings, body):
    with TestClient(
        create_app(documents_settings, documents_upstream_transport=httpx.MockTransport(unexpected))
    ) as client:
        response = client.patch(PREFIX + "/collections/c/items/i", json=body, headers=AUTH)
    assert response.status_code == 422


@pytest.mark.parametrize("space,documents", [(True, False), (False, True), (True, True)])
@pytest.mark.parametrize("preset", [None, "full", "read_only"])
def test_connection_modes_openapi_and_route_availability(space, documents, preset):
    settings = Settings(
        _env_file=None,
        craft_space_base_url="https://connect.craft.do/links/space-test-secret/api/v1"
        if space
        else None,
        craft_documents_base_url=DOCS_URL if documents else None,
        wrapper_api_token="test-wrapper-token",
        wrapper_enabled_operations=preset,
    )
    expected = set()
    if space:
        expected.update(SPACE_READ_OPERATION_IDS if preset == "read_only" else SPACE_OPERATION_IDS)
    if documents:
        expected.update(
            DOCUMENTS_READ_OPERATION_IDS if preset == "read_only" else DOCUMENTS_OPERATION_IDS
        )
    app = create_app(
        settings,
        upstream_transport=httpx.MockTransport(unexpected),
        documents_upstream_transport=httpx.MockTransport(unexpected),
    )
    spec = app.openapi()
    validate(spec)
    ops = [op for path in spec["paths"].values() for op in path.values()]
    assert spec["openapi"] == "3.1.0"
    assert len(ops) == len(expected)
    assert {op["operationId"] for op in ops} == expected
    assert all(op["security"] == [{"WrapperBearer": []}] for op in ops)
    for op in ops:
        for status in ("400", "401", "404", "409", "413", "422", "429", "500", "502", "503", "504"):
            assert op["responses"][status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
    assert all(secret not in json.dumps(spec) for secret in settings.secrets)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/openapi.json").status_code == 200
        for prefix, present in [("/v1/space", space), (PREFIX, documents)]:
            if not present:
                assert client.get(prefix + "/documents", headers=AUTH).status_code == 404
                assert (
                    client.post(
                        prefix + "/documents", json={"title": "X"}, headers=AUTH
                    ).status_code
                    == 404
                )
            else:
                assert client.get(prefix + "/documents").status_code == 401
                assert (
                    client.get(
                        prefix + "/documents", headers={"Authorization": "Bearer wrong"}
                    ).status_code
                    == 401
                )
        if documents and preset == "read_only":
            for method, path, body in [
                ("PATCH", "/blocks/text", {"markdown": "X"}),
                ("POST", "/blocks/root/content", {"markdown": "X"}),
                ("POST", "/collections/c/items", {"title": "X"}),
                ("PATCH", "/collections/c/items/i", {"properties": {"p": "X"}}),
            ]:
                assert (
                    client.request(method, PREFIX + path, json=body, headers=AUTH).status_code
                    == 404
                )


@pytest.mark.parametrize("payload", [{"items": []}, {"items": [ITEM, ITEM]}, {"unexpected": []}])
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("PATCH", "/blocks/text", {"markdown": "X"}),
        ("PATCH", "/collections/c/items/i", {"properties": {"p": "X"}}),
        ("POST", "/collections/c/items", {"title": "X"}),
    ],
)
def test_uncertain_singleton_write_results(documents_settings, payload, method, path, body):
    if path.startswith("/blocks") and payload.get("items"):
        payload = {"items": [BLOCK, BLOCK]}
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)

    with TestClient(
        create_app(documents_settings, documents_upstream_transport=httpx.MockTransport(handler))
    ) as client:
        response = client.request(method, PREFIX + path, json=body, headers=AUTH)
    assert response.status_code == 502
    assert response.json()["error"]["outcomeUnknown"] is True
    assert len(calls) == 1


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
        (502, 502, "craft_upstream_error"),
        (307, 502, "craft_upstream_error"),
    ],
)
def test_errors_stay_on_scoped_connection(settings, upstream, status, code, caplog):
    settings = settings.model_copy(
        update={
            "craft_documents_base_url": Settings(
                _env_file=None,
                craft_documents_base_url=DOCS_URL,
                craft_space_base_url=None,
                wrapper_api_token="test-wrapper-token",
            ).craft_documents_base_url
        }
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            upstream,
            json={"error": {"code": "SCOPE_ERROR", "message": " ".join(settings.secrets)}},
            headers={"Retry-After": "60"},
        )

    with (
        caplog.at_level(logging.INFO),
        TestClient(
            create_app(
                settings,
                upstream_transport=httpx.MockTransport(unexpected),
                documents_upstream_transport=httpx.MockTransport(handler),
            )
        ) as client,
    ):
        response = client.get(PREFIX + "/blocks/root", headers=AUTH)
    error = response.json()["error"]
    assert response.status_code == status
    assert error["code"] == code
    assert error["upstreamStatus"] == upstream
    assert error["retryAfterSeconds"] == 60
    assert error["requestId"] == response.headers["X-Request-Id"]
    assert all(secret not in response.text + caplog.text for secret in settings.secrets)
    assert len(calls) == 1


def test_configuration_requires_connection_and_rejects_absent_allowlist():
    with pytest.raises(ValidationError, match="At least one"):
        Settings(
            _env_file=None,
            craft_space_base_url=None,
            craft_documents_base_url=None,
            wrapper_api_token="token",
        )
    with pytest.raises(ValidationError, match="configured Craft connection"):
        Settings(
            _env_file=None,
            craft_space_base_url=None,
            craft_documents_base_url=DOCS_URL,
            wrapper_api_token="token",
            wrapper_enabled_operations="craft_space_get_block",
        )
    settings = Settings(
        _env_file=None,
        craft_space_base_url=None,
        craft_documents_base_url=DOCS_URL,
        wrapper_api_token="token",
        wrapper_enabled_operations="craft_documents_get_block",
    )
    assert settings.enabled_operations == {"craft_documents_get_block"}


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://connect.craft.do/links/secret/api/v1",
        "https://example.test/links/secret/api/v1",
        DOCS_URL + "?secret=value",
        "https://connect.craft.do/links/REPLACE_ME/api/v1",
        "https://connect.craft.do/wrong",
    ],
)
def test_documents_url_validation(url):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            craft_space_base_url=None,
            craft_documents_base_url=url,
            wrapper_api_token="token",
        )


@pytest.mark.parametrize(
    "failure,status,code",
    [
        ("network", 503, "craft_unavailable"),
        ("timeout", 504, "craft_timeout"),
        ("deadline", 504, "craft_timeout"),
        ("json", 502, "craft_upstream_error"),
        ("html", 502, "craft_upstream_error"),
        ("large", 502, "craft_response_too_large"),
    ],
)
@pytest.mark.parametrize("write", [False, True])
def test_transport_failures_never_fall_back(
    settings, documents_settings, failure, status, code, write
):
    import asyncio

    settings = documents_settings.model_copy(
        update={"craft_space_base_url": settings.craft_space_base_url}
    )
    calls = []

    async def handler(request):
        calls.append(request)
        if failure == "network":
            raise httpx.ConnectError("documents-test-secret", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("documents-test-secret", request=request)
        if failure == "deadline":
            await asyncio.sleep(0.1)
            return httpx.Response(200, json=BLOCK)
        if failure == "html":
            return httpx.Response(200, text="documents-test-secret")
        if failure == "json":
            return httpx.Response(
                200, content="{documents-test-secret}", headers={"Content-Type": "application/json"}
            )
        return httpx.Response(200, json={"content": "x" * 200})

    app = create_app(
        settings,
        upstream_transport=httpx.MockTransport(unexpected),
        documents_upstream_transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        app.state.documents_client.transport.max_response_bytes = 100
        if failure == "deadline":
            app.state.documents_client.transport.deadline_seconds = 0.01
        response = (
            client.patch(PREFIX + "/blocks/text", json={"markdown": "X"}, headers=AUTH)
            if write
            else client.get(PREFIX + "/blocks/root", headers=AUTH)
        )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"].get("outcomeUnknown", False) is write
    assert "documents-test-secret" not in response.text
    assert len(calls) == 1


def test_both_clients_have_independent_lifecycles(settings, documents_settings):
    settings = documents_settings.model_copy(
        update={"craft_space_base_url": settings.craft_space_base_url}
    )
    app = create_app(
        settings,
        upstream_transport=httpx.MockTransport(unexpected),
        documents_upstream_transport=httpx.MockTransport(unexpected),
    )
    with TestClient(app):
        space = app.state.space_client.transport.client
        documents = app.state.documents_client.transport.client
        assert space is not documents
        assert not space.is_closed and not documents.is_closed
    assert space.is_closed and documents.is_closed


def test_request_limits_and_internal_failures(documents_settings, caplog):
    from craft_wrapper.api.documents import get_client

    app = create_app(
        documents_settings, documents_upstream_transport=httpx.MockTransport(unexpected)
    )
    with TestClient(app) as client:
        response = client.post(
            PREFIX + "/blocks/root/content", headers=AUTH, content=b"x" * (1024 * 1024 + 1)
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"
        response = client.post(
            PREFIX + "/blocks/root/content",
            headers={**AUTH, "Content-Type": "application/json"},
            content="{bad}",
        )
        assert response.status_code == 422

        def explode():
            raise RuntimeError("documents-test-secret test-wrapper-token private-content")

        app.dependency_overrides[get_client] = explode
        response = client.get(PREFIX + "/documents", headers=AUTH)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        for private in ("documents-test-secret", "test-wrapper-token", "private-content"):
            assert private not in response.text + caplog.text

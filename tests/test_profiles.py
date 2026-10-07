import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from craft_wrapper.config import Settings
from craft_wrapper.main import create_app

SPACE_URL = "https://connect.craft.do/links/space-fixture-secret/api/v1"
DAILY_URL = "https://connect.craft.do/links/daily-fixture-secret/api/v1"


def profile_settings(profiles, **kwargs):
    return Settings(
        _env_file=None,
        craft_space_base_url=SPACE_URL,
        craft_daily_base_url=DAILY_URL,
        wrapper_api_token="legacy-fixture-token",
        wrapper_read_only_token="read-fixture-token",
        wrapper_planner_token="planner-fixture-token",
        wrapper_migration_token="migration-fixture-token",
        wrapper_profiles_json=json.dumps(profiles),
        **kwargs,
    )


def unexpected(request):
    pytest.fail("This request must not contact Craft")


def test_read_only_profile_mount_auth_schema_and_capabilities():
    settings = profile_settings({"read-only": {"adapters": ["space", "daily"]}})
    app = create_app(
        settings,
        upstream_transport=httpx.MockTransport(unexpected),
        daily_upstream_transport=httpx.MockTransport(unexpected),
    )
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/openapi.json").json()["paths"] == {}
        assert (
            client.get(
                "/v1/space/documents", headers={"Authorization": "Bearer legacy-fixture-token"}
            ).status_code
            == 404
        )
        schema = client.get("/profiles/read-only/openapi.json").json()
        assert len([op for path in schema["paths"].values() for op in path.values()]) == 18
        assert "/capabilities" not in schema["paths"]
        for secret in settings.secrets:
            assert secret not in json.dumps(schema)
        path = "/profiles/read-only/v1/space/documents"
        for token in ("legacy-fixture-token", "planner-fixture-token", None):
            headers = {} if token is None else {"Authorization": f"Bearer {token}"}
            assert client.get(path, headers=headers).status_code == 401
        headers = {"Authorization": "Bearer read-fixture-token"}
        result = client.get("/profiles/read-only/capabilities", headers=headers)
        assert result.status_code == 200
        assert result.json()["writeTargets"] == {}
        denied = client.post(
            "/profiles/read-only/v1/space/documents", json={"title": "Example"}, headers=headers
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "permission_denied"
        assert client.post("/profiles/read-only/v1/space/documents", json={}).status_code == 401
        assert client.get("/profiles/planner/openapi.json").status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"other": {"adapters": ["space"]}},
        {"read-only": {"adapters": []}},
        {"read-only": {"adapters": ["space"], "token": "accidental-secret"}},
        {"read-only": {"adapters": ["documents"]}},
        {"read-only": {"adapters": ["space"], "writeTargets": {"space": {"collectionIds": ["c"]}}}},
        {"planner": {"adapters": ["space"], "writeTargets": {"space": {"documentIds": [".."]}}}},
        {"planner": {"adapters": ["space"], "operations": ["craft_space_create_document"]}},
        {"migration": {"adapters": ["space"], "writeTargets": {"space": {"collectionIds": ["c"]}}}},
        {
            "migration": {
                "adapters": ["space"],
                "expiresAt": "2026-10-06T12:00:00",
                "writeTargets": {"space": {"collectionIds": ["c"]}},
            }
        },
    ],
)
def test_invalid_profiles_sanitized(bad):
    with pytest.raises(ValidationError):
        profile_settings(bad)


def test_profile_expiry_and_global_upper_bound():
    settings = profile_settings(
        {
            "migration": {
                "adapters": ["space"],
                "expiresAt": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                "writeTargets": {"space": {"collectionIds": ["c"]}},
            }
        }
    )
    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(unexpected))
    ) as client:
        result = client.get(
            "/profiles/migration/capabilities",
            headers={"Authorization": "Bearer migration-fixture-token"},
        )
        assert result.status_code == 403
        assert result.json()["error"]["code"] == "profile_expired"
        assert client.get("/profiles/migration/openapi.json").status_code == 403
    settings = profile_settings(
        {"read-only": {"adapters": ["space"]}},
        wrapper_enabled_operations="craft_space_list_documents",
    )
    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(unexpected))
    ) as client:
        assert set(client.get("/profiles/read-only/openapi.json").json()["paths"]) == {
            "/v1/space/documents"
        }
        assert client.get("/profiles/read-only/v1/space/folders").status_code == 404


PLANNER = {
    "adapters": ["space", "daily"],
    "writeTargets": {
        "space": {"documentIds": ["root"], "collectionIds": ["backlog"]},
        "daily": {"collectionIds": ["daily-backlog"]},
    },
}
ROOT = {
    "id": "root",
    "type": "page",
    "content": [
        {"id": "text", "type": "text", "markdown": "Original"},
        {"id": "nested", "type": "page", "content": [{"id": "child", "type": "text"}]},
        {
            "id": "collection",
            "type": "collection",
            "items": [
                {"id": "row-block", "type": "page", "content": [{"id": "row-text", "type": "text"}]}
            ],
        },
        {"id": "link", "type": "text", "markdown": "block://foreign"},
    ],
}


@pytest.mark.parametrize(
    "method,path,query,body,status",
    [
        ("POST", "/collections/backlog/items", {}, {"title": "Example"}, 201),
        ("PATCH", "/collections/backlog/items/row", {}, {"properties": {"status": "Done"}}, 200),
        ("DELETE", "/collections/backlog/items/row", {}, None, 200),
        ("POST", "/blocks/root/content", {"documentId": "root"}, {"markdown": "New"}, 201),
        ("PATCH", "/blocks/child", {"documentId": "root"}, {"markdown": "New"}, 200),
        ("DELETE", "/blocks/text", {"documentId": "root"}, None, 200),
    ],
)
def test_planner_allowed_writes_and_exact_preflights(method, path, query, body, status):
    calls = []

    def upstream(request):
        calls.append(request)
        if request.method == "GET" and request.url.path.endswith("/schema"):
            return httpx.Response(
                200,
                json={
                    "name": "Backlog",
                    "properties": [{"key": "status", "name": "Status", "type": "select"}],
                },
            )
        if request.method == "GET" and request.url.path.endswith("/blocks"):
            assert dict(request.url.params) == {"id": "root", "maxDepth": "-1"}
            return httpx.Response(200, json=ROOT)
        if request.method == "GET":
            assert dict(request.url.params) == {"maxDepth": "0"}
            return httpx.Response(
                200, json={"items": [{"id": "row", "properties": {"status": "Todo"}}]}
            )
        payload = json.loads(request.content)
        if request.method == "DELETE":
            expected = {"idsToDelete": ["row"]} if "collections" in path else {"blockIds": ["text"]}
            assert payload == expected
            result = {"id": "row" if "collections" in path else "text"}
        elif request.method == "POST" and "collections" in path:
            assert payload == {"items": [{"title": "Example", "properties": {}}]}
            result = {"id": "created", "title": "Example"}
        elif request.method == "PUT" and "collections" in path:
            assert payload == {"itemsToUpdate": [{"id": "row", "properties": {"status": "Done"}}]}
            result = {"id": "row", "properties": {"status": "Done"}}
        elif request.method == "PUT":
            assert payload == {"blocks": [{"id": "child", "markdown": "New"}]}
            result = {"id": "child", "type": "text", "markdown": "New"}
        else:
            assert payload == {"markdown": "New", "position": {"pageId": "root", "position": "end"}}
            result = {"id": "new", "type": "text"}
        return httpx.Response(200, json={"items": [result]})

    settings = profile_settings({"planner": PLANNER})
    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(upstream))
    ) as client:
        response = client.request(
            method,
            "/profiles/planner/v1/space" + path,
            params=query,
            json=body,
            headers={"Authorization": "Bearer planner-fixture-token"},
        )
        assert response.status_code == status, response.text
    assert len([r for r in calls if r.method != "GET"]) == 1
    assert len(calls) == (
        1
        if method == "POST" and "collections" in path
        else 3
        if method == "PATCH" and "collections" in path
        else 2
    )


@pytest.mark.parametrize(
    "method,path,query,body,status",
    [
        ("POST", "/collections/foreign/items", {}, {"title": "Example"}, 403),
        (
            "PATCH",
            "/collections/backlog/items/foreign",
            {},
            {"properties": {"status": "Done"}},
            403,
        ),
        ("PATCH", "/blocks/foreign", {"documentId": "root"}, {"markdown": "New"}, 403),
        ("PATCH", "/blocks/row-text", {"documentId": "root"}, {"markdown": "New"}, 403),
        ("PATCH", "/blocks/row-block", {"documentId": "root"}, {"markdown": "New"}, 403),
        ("PATCH", "/blocks/text", {"documentId": "foreign"}, {"markdown": "New"}, 403),
        ("PATCH", "/blocks/text", {}, {"markdown": "New"}, 422),
        ("DELETE", "/blocks/root", {"documentId": "root"}, None, 403),
        ("DELETE", "/blocks/nested", {"documentId": "root"}, None, 403),
        ("DELETE", "/blocks/collection", {"documentId": "root"}, None, 403),
        ("POST", "/documents", {}, {"title": "Example"}, 403),
    ],
)
def test_planner_denies_foreign_targets_and_protected_structure(method, path, query, body, status):
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/schema"):
            return httpx.Response(
                200,
                json={
                    "name": "Backlog",
                    "properties": [
                        {"key": "status", "name": "Status", "type": "select"},
                    ],
                },
            )
        return httpx.Response(
            200, json=ROOT if request.url.path.endswith("/blocks") else {"items": [{"id": "row"}]}
        )

    with TestClient(
        create_app(
            profile_settings({"planner": PLANNER}), upstream_transport=httpx.MockTransport(upstream)
        )
    ) as client:
        response = client.request(
            method,
            "/profiles/planner/v1/space" + path,
            params=query,
            json=body,
            headers={"Authorization": "Bearer planner-fixture-token"},
        )
        assert response.status_code == status, response.text
        assert "outcomeUnknown" not in response.json()["error"]
    assert all(r.method == "GET" for r in calls)


@pytest.mark.parametrize(
    "root",
    [
        {"id": "root", "type": "page", "contentPreviewMd": "omitted"},
        {"id": "wrong", "type": "page", "content": [{"id": "text", "type": "text"}]},
        {"id": "root", "type": "page", "content": [{"id": "text"}]},
        {
            "id": "root",
            "type": "page",
            "content": [{"id": "text", "type": "text"}, {"id": "text", "type": "text"}],
        },
    ],
)
def test_incomplete_or_malformed_verification_prevents_submission(root):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        return httpx.Response(200, json=root)

    with TestClient(
        create_app(
            profile_settings({"planner": PLANNER}), upstream_transport=httpx.MockTransport(handler)
        )
    ) as client:
        response = client.patch(
            "/profiles/planner/v1/space/blocks/text?documentId=root",
            json={"markdown": "New"},
            headers={"Authorization": "Bearer planner-fixture-token"},
        )
        assert response.status_code == 502
        assert "outcomeUnknown" not in response.json()["error"]
    assert len(calls) == 1


def test_migration_is_copy_only_and_legacy_credentials_cannot_bypass():
    profile = {
        "adapters": ["space"],
        "expiresAt": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "writeTargets": {"space": {"collectionIds": ["backlog"]}},
    }
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            assert request.url.path.endswith("/schema")
            return httpx.Response(
                200,
                json={
                    "name": "Backlog",
                    "properties": [
                        {"key": "source_task_id", "name": "Source task ID", "type": "text"}
                    ],
                },
            )
        assert request.method == "POST" and request.url.path.endswith("/collections/backlog/items")
        return httpx.Response(200, json={"items": [{"id": "new", "title": "Copied"}]})

    settings = profile_settings({"migration": profile})
    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        headers = {"Authorization": "Bearer migration-fixture-token"}
        assert (
            client.post(
                "/profiles/migration/v1/space/collections/backlog/items",
                json={"title": "Copied", "properties": {"source_task_id": "source"}},
                headers=headers,
            ).status_code
            == 201
        )
        for method, path, body in [
            ("PATCH", "/collections/backlog/items/new", {"properties": {"status": "Done"}}),
            ("DELETE", "/collections/backlog/items/new", None),
            ("PATCH", "/blocks/source", {"markdown": "Changed"}),
            ("POST", "/collections/foreign/items", {"title": "No"}),
        ]:
            response = client.request(
                method, "/profiles/migration/v1/space" + path, json=body, headers=headers
            )
            assert response.status_code == 403
        assert (
            client.post(
                "/v1/space/collections/backlog/items",
                json={"title": "No"},
                headers={"Authorization": "Bearer legacy-fixture-token"},
            ).status_code
            == 404
        )
    assert [r.method for r in calls] == ["GET", "POST"]


@pytest.mark.parametrize("stage", ["verification", "submission"])
def test_overall_write_deadline_distinguishes_unknown_outcomes(stage):
    import asyncio

    calls = []

    async def handler(request):
        calls.append(request)
        if (request.method == "GET") == (stage == "verification"):
            await asyncio.sleep(0.1)
        return httpx.Response(
            200,
            json=ROOT if request.method == "GET" else {"items": [{"id": "text", "type": "text"}]},
        )

    settings = profile_settings({"planner": PLANNER}, craft_timeout_seconds=0.03)
    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        response = client.patch(
            "/profiles/planner/v1/space/blocks/text?documentId=root",
            json={"markdown": "New"},
            headers={"Authorization": "Bearer planner-fixture-token"},
        )
        assert response.status_code == 504, response.text
        assert response.json()["error"].get("outcomeUnknown", False) == (stage == "submission")
    assert len(calls) == (1 if stage == "verification" else 2)


def test_expiration_during_preflight_prevents_mutation():
    settings = profile_settings({"planner": PLANNER})

    def handler(request):
        assert request.method == "GET"
        settings.profiles["planner"].expiresAt = datetime.now(UTC) - timedelta(seconds=1)
        return httpx.Response(200, json=ROOT)

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        result = client.patch(
            "/profiles/planner/v1/space/blocks/text?documentId=root",
            json={"markdown": "New"},
            headers={"Authorization": "Bearer planner-fixture-token"},
        )
        assert result.status_code == 403
        assert result.json()["error"]["code"] == "profile_expired"


@pytest.mark.parametrize("adapter", ["documents", "daily"])
def test_profile_write_verification_stays_on_selected_connection(adapter):
    definitions = {
        "planner": {
            "adapters": [adapter],
            "writeTargets": {
                adapter: {
                    "collectionIds": ["backlog"],
                    **({"documentIds": ["root"]} if adapter == "documents" else {}),
                }
            },
        }
    }
    kwargs = (
        {
            "craft_documents_base_url": "https://connect.craft.do/links/documents-fixture-secret/api/v1"
        }
        if adapter == "documents"
        else {}
    )
    settings = profile_settings(definitions, **kwargs)
    calls = []

    def handler(request):
        calls.append(request)
        assert f"/links/{adapter}-fixture-secret/" in request.url.path
        if request.method == "GET":
            assert dict(request.url.params) == (
                {"date": "yesterday", "maxDepth": "-1"}
                if adapter == "daily"
                else {"id": "root", "maxDepth": "-1"}
            )
            return httpx.Response(200, json=ROOT)
        assert json.loads(request.content) == {"blocks": [{"id": "text", "markdown": "Updated"}]}
        return httpx.Response(
            200, json={"items": [{"id": "text", "type": "text", "markdown": "Updated"}]}
        )

    transport = f"{adapter}_upstream_transport"
    app = create_app(
        settings,
        upstream_transport=httpx.MockTransport(unexpected),
        **{transport: httpx.MockTransport(handler)},
    )
    with TestClient(app) as client:
        query = {"date": "yesterday"} if adapter == "daily" else {"documentId": "root"}
        response = client.patch(
            f"/profiles/planner/v1/{adapter}/blocks/text",
            params=query,
            json={"markdown": "Updated"},
            headers={"Authorization": "Bearer planner-fixture-token"},
        )
        assert response.status_code == 200, response.text
    assert len(calls) == 2


@pytest.mark.parametrize("kind", ["relation", "blockLink", "unknownComplex"])
def test_string_properties_cannot_bypass_profile_scope_through_relations(kind):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path.endswith("/schema")
        return httpx.Response(
            200,
            json={
                "name": "Backlog",
                "properties": [{"key": "project", "name": "Project", "type": kind}],
            },
        )

    with TestClient(
        create_app(
            profile_settings({"planner": PLANNER}), upstream_transport=httpx.MockTransport(handler)
        )
    ) as client:
        result = client.post(
            "/profiles/planner/v1/space/collections/backlog/items",
            json={"title": "Example", "properties": {"project": "foreign-id"}},
            headers={"Authorization": "Bearer planner-fixture-token"},
        )
        assert result.status_code == 403
    assert len(calls) == 1


def test_duplicate_tokens_missing_tokens_blank_json_and_disabled_profiles():
    for values in [
        {"wrapper_read_only_token": "planner-fixture-token"},
        {"wrapper_read_only_token": None},
    ]:
        kwargs = dict(
            _env_file=None,
            craft_space_base_url=SPACE_URL,
            wrapper_profiles_json=json.dumps(
                {"read-only": {"adapters": ["space"]}, "planner": {"adapters": ["space"]}}
            ),
            wrapper_read_only_token="read-fixture-token",
            wrapper_planner_token="planner-fixture-token",
        )
        kwargs.update(values)
        with pytest.raises(ValidationError):
            Settings(**kwargs)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, craft_space_base_url=SPACE_URL, wrapper_profiles_json="")
    settings = Settings(
        _env_file=None,
        craft_space_base_url=SPACE_URL,
        wrapper_profiles_json='{"read-only":{"enabled":false,"adapters":["space"]}}',
    )
    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(unexpected))
    ) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/profiles/read-only/openapi.json").status_code == 404


@pytest.mark.parametrize(
    "adapters",
    [
        ["space"],
        ["documents"],
        ["daily"],
        ["space", "documents"],
        ["space", "daily"],
        ["documents", "daily"],
        ["space", "documents", "daily"],
    ],
)
def test_read_profile_all_connection_combinations_and_schema_security(adapters):
    from openapi_spec_validator import validate

    from craft_wrapper.config import OPERATION_PRESETS

    kwargs = {
        f"craft_{adapter}_base_url": f"https://connect.craft.do/links/{adapter}-fixture/api/v1"
        for adapter in adapters
    }
    settings = Settings(
        _env_file=None,
        wrapper_profiles_json=json.dumps({"read-only": {"adapters": adapters}}),
        wrapper_read_only_token="read-fixture-token",
        **kwargs,
    )
    app = create_app(
        settings,
        **{
            "upstream_transport"
            if a == "space"
            else f"{a}_upstream_transport": httpx.MockTransport(unexpected)
            for a in adapters
        },
    )
    with TestClient(app) as client:
        spec = client.get("/profiles/read-only/openapi.json").json()
        validate(spec)
        operations = [op for path in spec["paths"].values() for op in path.values()]
        assert {op["operationId"] for op in operations} == {
            op for op in OPERATION_PRESETS["read_only"] if op.split("_")[1] in adapters
        }
        assert all(op["security"] == [{"WrapperBearer": []}] for op in operations)
        assert all("403" in op["responses"] for op in operations)
        for secret in settings.secrets:
            assert secret not in json.dumps(spec)


def test_profile_secrets_do_not_leak_in_validation_logs_or_schema(caplog):
    settings = profile_settings({"planner": PLANNER})
    assert settings.wrapper_planner_token is not None
    assert settings.craft_space_base_url is not None
    planner_secret = settings.wrapper_planner_token.get_secret_value()
    connection_secret = settings.craft_space_base_url.get_secret_value()

    def handler(request):
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": planner_secret,
                    "message": connection_secret,
                }
            },
        )

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(handler))
    ) as client:
        result = client.get(
            "/profiles/planner/v1/space/folders",
            headers={"Authorization": "Bearer planner-fixture-token"},
        )
        schema = client.get("/profiles/planner/openapi.json").json()
        invalid = client.post(
            "/profiles/planner/v1/space/collections/backlog/items",
            json={"title": {"secret": planner_secret}},
            headers={"Authorization": "Bearer planner-fixture-token"},
        )
    output = json.dumps([result.json(), invalid.json(), schema]) + caplog.text
    for secret in settings.secrets:
        assert secret not in output
    assert "backlog" not in json.dumps(schema)


def test_upstream_request_logs_do_not_expose_private_search_terms(caplog):
    import logging

    settings = profile_settings({"read-only": {"adapters": ["space"]}})

    def handler(request):
        return httpx.Response(200, json={"items": []})

    with (
        caplog.at_level(logging.INFO),
        TestClient(create_app(settings, upstream_transport=httpx.MockTransport(handler))) as client,
    ):
        result = client.get(
            "/profiles/read-only/v1/space/documents/search",
            params={"query": "private-search-content"},
            headers={"Authorization": "Bearer read-fixture-token"},
        )
        assert result.status_code == 200
    assert "private-search-content" not in caplog.text
    assert "profileId=read-only" in caplog.text


def test_legacy_placeholder_token_is_ignored_in_profile_mode():
    settings = Settings(
        _env_file=None,
        craft_space_base_url=SPACE_URL,
        wrapper_api_token="REPLACE_ME",
        wrapper_read_only_token="read-fixture-token",
        wrapper_profiles_json='{"read-only":{"adapters":["space"]}}',
    )
    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(unexpected))
    ) as client:
        assert (
            client.get(
                "/profiles/read-only/capabilities",
                headers={"Authorization": "Bearer read-fixture-token"},
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/profiles/read-only/capabilities", headers={"Authorization": "Bearer REPLACE_ME"}
            ).status_code
            == 401
        )


def test_global_read_only_mask_removes_effective_capability_write_targets():
    settings = profile_settings({"planner": PLANNER}, wrapper_enabled_operations="read_only")
    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(unexpected))
    ) as client:
        result = client.get(
            "/profiles/planner/capabilities",
            headers={"Authorization": "Bearer planner-fixture-token"},
        )
        assert result.status_code == 200
        assert result.json()["writeTargets"] == {}
        assert not any("_delete_" in op or "_add_" in op for op in result.json()["operations"])

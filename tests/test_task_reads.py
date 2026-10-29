import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate

from craft_wrapper.config import Settings
from craft_wrapper.main import create_app

AUTH = {"Authorization": "Bearer test-read-token"}
TASK = {
    "id": "native/task &?",
    "type": "text",
    "listStyle": "task",
    "markdown": "Parent task",
    "taskInfo": {"state": "todo", "scheduleDate": "2026-01-02", "deadlineDate": "2026-01-03"},
    "metadata": {
        "createdAt": "2026-01-01T08:00:00Z",
        "lastModifiedAt": "2026-01-02T09:00:00+01:00",
        "createdBy": "synthetic-private-actor",
        "clickableLink": "private-navigation",
    },
    "content": [
        {
            "id": "child",
            "type": "text",
            "listStyle": "task",
            "markdown": "Child task",
            "taskInfo": {"state": "done"},
            "metadata": {"createdAt": "2026-01-01T08:01:00Z"},
        }
    ],
}
CONNECTION = {
    "space": {
        "id": "synthetic-space",
        "name": "synthetic-private-name",
        "timezone": "Europe/Berlin",
        "time": "2026-01-02T10:00:00+01:00",
        "friendlyDate": "Friday, January 2, 2026",
    },
    "utc": {"time": "2026-01-02T09:00:00Z"},
    "urlTemplates": {"app": "craftdocs://open?spaceId=synthetic-space&blockId={blockId}"},
}


def settings(**overrides):
    return Settings(
        _env_file=None,
        wrapper_api_token="test-read-token",
        craft_space_base_url="https://connect.craft.do/links/test-space-secret/api/v1",
        craft_daily_base_url="https://connect.craft.do/links/test-daily-secret/api/v1",
        **overrides,
    )


def app(handler, **overrides):
    transport = httpx.MockTransport(handler)
    return create_app(
        settings(**overrides), upstream_transport=transport, daily_upstream_transport=transport
    )


@pytest.mark.parametrize("adapter", ["space", "daily"])
def test_task_details_metadata_hierarchy_validation_and_exact_mapping(adapter: str):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path.endswith("/blocks")
        assert request.headers["accept"] == "application/json"
        assert adapter in request.url.path
        assert request.url.params["id"] == TASK["id"]
        assert "date" not in request.url.params
        result = copy.deepcopy(TASK)
        if "fetchMetadata" not in request.url.params:
            result.pop("metadata")
        return httpx.Response(200, json=result)

    path = f"/v1/{adapter}/tasks/native%2Ftask%20%26%3F"
    with TestClient(app(handler)) as client:
        assert client.get(path).status_code == 401
        assert not calls
        response = client.get(path, headers=AUTH)
        assert response.status_code == 200
        data = response.json()
        assert data["taskInfo"] == TASK["taskInfo"]
        assert data["content"][0]["taskInfo"]["state"] == "done"
        assert data["metadata"]["createdAt"] == TASK["metadata"]["createdAt"]
        assert "createdBy" not in data["metadata"] and "clickableLink" not in data["metadata"]
        assert dict(calls[-1].url.params) == {
            "id": TASK["id"],
            "maxDepth": "1",
            "fetchMetadata": "true",
        }
        assert (
            client.get(
                path, params={"maxDepth": -1, "fetchMetadata": False}, headers=AUTH
            ).status_code
            == 200
        )
        assert dict(calls[-1].url.params) == {"id": TASK["id"], "maxDepth": "-1"}
        before = len(calls)
        assert client.get(path, params={"date": "today"}, headers=AUTH).status_code == 422
        assert len(calls) == before


@pytest.mark.parametrize("adapter", ["space", "daily"])
def test_connection_info_is_authenticated_sanitized_and_validates_payloads(adapter: str):
    payload = copy.deepcopy(CONNECTION)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path.endswith("/connection")
        assert adapter in request.url.path and not request.url.params
        return httpx.Response(200, json=payload)

    path = f"/v1/{adapter}/connection"
    with TestClient(app(handler)) as client:
        assert client.get(path).status_code == 401 and not calls
        data = client.get(path, headers=AUTH).json()
        assert data["space"]["timezone"] == "Europe/Berlin"
        assert "name" not in data["space"]
        assert data["urlTemplates"] == CONNECTION["urlTemplates"]
        for invalid in (
            "https://connect.craft.do/links/test-space-secret/api/v1",
            "craftdocs://open?spaceId=x",
        ):
            payload["urlTemplates"]["app"] = invalid
            response = client.get(path, headers=AUTH)
            assert response.status_code == 502
            assert "test-space-secret" not in response.text
        payload.update(copy.deepcopy(CONNECTION))
        payload["space"]["id"] = "test-read-token"
        response = client.get(path, headers=AUTH)
        assert response.status_code == 502 and "test-read-token" not in response.text
        assert len(calls) == 4


def test_task_identity_wrong_resource_missing_age_and_malformed_metadata():
    payload = copy.deepcopy(TASK)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)

    with TestClient(app(handler)) as client:
        path = "/v1/space/tasks/native%2Ftask%20%26%3F"
        cases = [
            ({"id": "different"}, 502),
            ({"listStyle": "none", "taskInfo": None, "markdown": "- [x] Looks like a task"}, 404),
            ({"listStyle": "none"}, 502),
            ({"metadata": {"createdAt": "2026-01-01T08:00:00"}}, 502),
        ]
        for change, status in cases:
            payload.clear()
            payload.update(copy.deepcopy(TASK) | change)
            response = client.get(path, headers=AUTH)
            assert response.status_code == status
            assert response.json()["error"].get("outcomeUnknown") is not True
        payload.pop("metadata")
        payload["taskInfo"] = {"state": "future-state"}
        response = client.get(path, headers=AUTH)
        assert response.status_code == 200
        assert "metadata" not in response.json()
        assert response.json()["taskInfo"]["state"] == "future-state"
        assert len(calls) == 5


def test_structured_note_and_block_selectors_preserve_defaults():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "root", "type": "page", "content": [TASK]})

    with TestClient(app(handler)) as client:
        for path, selector in (
            ("/v1/space/blocks/root", {"id": "root"}),
            ("/v1/daily/blocks/root", {"id": "root"}),
            ("/v1/daily/notes", {"date": "today"}),
        ):
            assert client.get(path, headers=AUTH).status_code == 200
            assert dict(calls[-1].url.params) == selector | {"maxDepth": "1"}
            response = client.get(
                path, params={"fetchMetadata": True, "maxDepth": -1}, headers=AUTH
            )
            assert response.status_code == 200
            assert dict(calls[-1].url.params) == selector | {
                "maxDepth": "-1",
                "fetchMetadata": "true",
            }
            assert (
                response.json()["content"][0]["metadata"]["createdAt"]
                == TASK["metadata"]["createdAt"]
            )


def test_read_only_profile_schemas_disabled_routes_and_connection_isolation():
    profiles = json.dumps({"read-only": {"adapters": ["space", "daily"]}})
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200, json=CONNECTION if request.url.path.endswith("/connection") else TASK
        )

    configured = settings(
        wrapper_profiles_json=profiles, wrapper_read_only_token="profile-read-token"
    )
    transport = httpx.MockTransport(handler)
    with TestClient(
        create_app(configured, upstream_transport=transport, daily_upstream_transport=transport)
    ) as client:
        spec = client.get("/profiles/read-only/openapi.json").json()
        validate(spec)
        ids = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
        assert {
            f"craft_{a}_{op}"
            for a in ("space", "daily")
            for op in ("get_task", "get_connection_info")
        } <= ids
        for adapter in ("space", "daily"):
            response = client.get(
                f"/profiles/read-only/v1/{adapter}/connection",
                headers={"Authorization": "Bearer profile-read-token"},
            )
            assert response.status_code == 200 and adapter in seen[-1].url.path
        assert client.get("/v1/space/connection", headers=AUTH).status_code == 404
    with TestClient(app(handler, wrapper_enabled_operations="craft_space_list_folders")) as client:
        assert client.get("/v1/space/connection", headers=AUTH).status_code == 404
        assert client.get("/v1/space/tasks/anything", headers=AUTH).status_code == 404

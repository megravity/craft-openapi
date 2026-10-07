import json

import httpx
import pytest
from fastapi.testclient import TestClient

from craft_wrapper.config import Settings
from craft_wrapper.main import create_app

AUTH = {"Authorization": "Bearer operation-fixture-token"}


def app_for(adapter, handler):
    settings = Settings(
        _env_file=None,
        wrapper_api_token="operation-fixture-token",
        **{f"craft_{adapter}_base_url": f"https://connect.craft.do/links/{adapter}-fixture/api/v1"},
    )
    transport = "upstream_transport" if adapter == "space" else f"{adapter}_upstream_transport"
    return create_app(settings, **{transport: httpx.MockTransport(handler)})


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize("kind", ["collection", "block"])
def test_deletion_exact_contract_and_context(adapter, kind):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path.startswith(f"/links/{adapter}-fixture/api/v1/")
        assert request.headers["accept"] == "application/json"
        if request.method == "GET":
            if kind == "collection":
                assert dict(request.url.params) == {"maxDepth": "0"}
                return httpx.Response(200, json={"items": [{"id": "target", "title": "Example"}]})
            assert dict(request.url.params) == (
                {"date": "yesterday", "maxDepth": "-1"}
                if adapter == "daily"
                else {"id": "root", "maxDepth": "-1"}
            )
            return httpx.Response(
                200,
                json={
                    "id": "root",
                    "type": "page",
                    "content": [{"id": "target", "type": "text", "markdown": "Example"}],
                },
            )
        assert request.method == "DELETE"
        assert not request.url.params
        expected = {"idsToDelete": ["target"]} if kind == "collection" else {"blockIds": ["target"]}
        assert json.loads(request.content) == expected
        return httpx.Response(200, json={"items": [{"id": "target"}]})

    path = "/collections/collection/items/target" if kind == "collection" else "/blocks/target"
    params = (
        {}
        if kind == "collection"
        else ({"date": "yesterday"} if adapter == "daily" else {"documentId": "root"})
    )
    with TestClient(app_for(adapter, handler)) as client:
        response = client.delete(f"/v1/{adapter}" + path, params=params, headers=AUTH)
        assert response.status_code == 200, response.text
        assert response.json() == {"id": "target"}
    assert [r.method for r in calls] == ["GET", "DELETE"]


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize(
    "items", [[], [{"id": "wrong"}], [{"id": "target"}, {"id": "other"}], [{}]]
)
def test_deleted_results_are_not_fabricated_or_retried(adapter, items):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={"items": [{"id": "target"}] if request.method == "GET" else items}
        )

    with TestClient(app_for(adapter, handler)) as client:
        response = client.delete(f"/v1/{adapter}/collections/c/items/target", headers=AUTH)
        assert response.status_code == 502
        assert response.json()["error"]["outcomeUnknown"] is True
    assert [r.method for r in calls] == ["GET", "DELETE"]


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize(
    "target",
    [
        {"id": "target", "type": "page"},
        {"id": "target", "type": "collection"},
        {"id": "target", "type": "image"},
        {"id": "target", "type": "whiteboard"},
        {"id": "target", "type": "text", "content": [{"id": "child", "type": "text"}]},
        {"id": "target", "type": "text", "contentPreviewMd": "omitted"},
    ],
)
def test_leaf_deletion_protects_other_shapes_in_legacy_mode(adapter, target):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        return httpx.Response(200, json={"id": "root", "type": "page", "content": [target]})

    params = {"date": "today"} if adapter == "daily" else {"documentId": "root"}
    with TestClient(app_for(adapter, handler)) as client:
        response = client.delete(f"/v1/{adapter}/blocks/target", params=params, headers=AUTH)
        assert response.status_code in {403, 502}
        assert "outcomeUnknown" not in response.json()["error"]
    assert len(calls) == 1


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_new_leaf_deletion_requires_context_before_upstream(adapter):
    def handler(request):
        pytest.fail("Missing context must not contact Craft")

    with TestClient(app_for(adapter, handler)) as client:
        response = client.delete(f"/v1/{adapter}/blocks/target", headers=AUTH)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("scope", ["active", "upcoming", "inbox", "logbook", "document", "all"])
def test_space_tasks_preserve_location_and_dates(scope):
    def handler(request):
        assert request.method == "GET" and request.url.path.endswith("/tasks")
        expected = {"scope": scope, **({"documentId": "root/?#"} if scope == "document" else {})}
        assert dict(request.url.params) == expected
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "task",
                        "markdown": "Example",
                        "taskInfo": {
                            "state": "future-state",
                            "scheduleDate": "tomorrow",
                            "deadlineDate": "2030-01-01",
                        },
                        "location": {"type": "document", "title": "Project", "documentId": "root"},
                        "completedAt": "2030-01-02T00:00:00Z",
                        "canceledAt": "2030-01-03T00:00:00Z",
                    }
                ]
            },
        )

    with TestClient(app_for("space", handler)) as client:
        response = client.get(
            "/v1/space/tasks",
            params={"scope": scope, **({"documentId": "root/?#"} if scope == "document" else {})},
            headers=AUTH,
        )
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["taskInfo"]["state"] == "future-state"
        assert item["location"]["documentId"] == "root"
        assert item["completedAt"] and item["canceledAt"]


@pytest.mark.parametrize(
    "params",
    [{}, {"scope": "document"}, {"scope": "all", "documentId": "root"}, {"scope": "unknown"}],
)
def test_invalid_space_task_filters_make_no_upstream_call(params):
    def handler(request):
        pytest.fail("Invalid filters must not contact Craft")

    with TestClient(app_for("space", handler)) as client:
        assert client.get("/v1/space/tasks", params=params, headers=AUTH).status_code == 422


def test_unverified_title_editing_is_not_advertised_or_callable():
    from pathlib import Path

    evidence = json.loads(
        (Path(__file__).parent / "fixtures" / "title-write-probe.json").read_text()
    )
    assert evidence["gatePassed"] is False
    for adapter in ("space", "documents", "daily"):
        with TestClient(
            app_for(adapter, lambda request: pytest.fail("Title editing must not contact Craft"))
        ) as client:
            schema = client.get("/openapi.json").json()
            assert not any(
                "update_collection_item_title" in op["operationId"]
                for path in schema["paths"].values()
                for op in path.values()
            )
            assert (
                client.patch(
                    f"/v1/{adapter}/collections/c/items/row/title",
                    json={"title": "New"},
                    headers=AUTH,
                ).status_code
                == 404
            )

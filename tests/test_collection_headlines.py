import asyncio
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from craft_wrapper.config import Settings
from craft_wrapper.main import create_app

AUTH = {"Authorization": "Bearer headline-fixture-token"}


def configuration(adapter, profile=None, **kwargs):
    connections: dict[str, str | None] = {
        f"craft_{name}_base_url": None for name in ("space", "documents", "daily")
    }
    connections[f"craft_{adapter}_base_url"] = (
        f"https://connect.craft.do/links/{adapter}-headline-fixture/api/v1"
    )
    rules = None
    if profile is not None:
        rule: dict[str, Any] = {"adapters": [adapter]}
        if profile == "planner":
            rule["writeTargets"] = {adapter: {"collectionIds": ["rows"]}}
        elif profile == "migration":
            connections["craft_space_base_url"] = (
                "https://connect.craft.do/links/space-headline-fixture/api/v1"
            )
            rule.update(
                adapters=sorted({"space", adapter}),
                expiresAt=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                writeTargets={"space": {"collectionIds": ["rows"]}},
            )
        rules = json.dumps({profile: rule})
    return Settings(
        _env_file=None,
        **connections,
        wrapper_api_token="headline-fixture-token",
        wrapper_planner_token="headline-fixture-token",
        wrapper_read_only_token="headline-fixture-token",
        wrapper_migration_token="headline-fixture-token",
        wrapper_profiles_json=rules,
        **kwargs,
    )


def app_for(adapter, handler, settings=None):
    setting = settings or configuration(adapter)
    key = "upstream_transport" if adapter == "space" else f"{adapter}_upstream_transport"
    return create_app(setting, **{key: httpx.MockTransport(handler)})


def schema_for(key):
    return {
        "name": "Rows",
        "properties": [{"key": "probe", "name": "Probe", "type": "text"}],
        **({"contentPropDetails": {"key": key, "name": "Headline"}} if key is not None else {}),
    }


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize("key", [None, "title", "task", "work"])
def test_schema_maps_creation_reads_properties_and_title_without_changing_content(adapter, key):
    native = key or "title"
    row: dict[str, Any] = {
        "id": "row",
        native: "Original",
        "properties": {
            "probe": "Keep",
            "title": "Regular property",
            "links": ["invalid:out_of_scope"],
        },
        "content": [{"id": "child", "type": "text", "markdown": "Keep nested content"}],
        "extra": {"future": "ignored"},
    }
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.url.path.startswith(f"/links/{adapter}-headline-fixture/api/v1/")
        assert "authorization" not in request.headers
        assert request.headers["accept"] == "application/json"
        if request.url.path.endswith("/schema"):
            assert request.method == "GET" and dict(request.url.params) == {"format": "schema"}
            return httpx.Response(200, json=schema_for(key))
        if request.method == "GET":
            assert dict(request.url.params) in ({"maxDepth": "-1"}, {"maxDepth": "0"})
        else:
            assert not request.url.params
            payload = json.loads(request.content)
            if request.method == "POST":
                assert payload == {"items": [{native: "Created", "properties": {}}]}
                row[native] = "Created"
            else:
                change = payload["itemsToUpdate"][0]
                assert change["id"] == "row"
                if "properties" in change:
                    assert change == {"id": "row", "properties": {"probe": "Updated"}}
                    row["properties"]["probe"] = "Updated"
                else:
                    assert change == {"id": "row", native: "Renamed"}
                    row[native] = "Renamed"
        return httpx.Response(200, json={"items": [row]})

    path = f"/v1/{adapter}/collections/rows/items"
    with TestClient(app_for(adapter, upstream)) as client:
        listed = client.get(path, params={"maxDepth": -1}, headers=AUTH)
        assert listed.status_code == 200
        assert listed.json()["items"][0]["title"] == "Original"
        assert "extra" not in listed.json()["items"][0]
        if native != "title":
            assert native not in listed.json()["items"][0]
        created = client.post(path, json={"title": "Created"}, headers=AUTH)
        assert created.status_code == 201 and created.json()["title"] == "Created"
        changed = client.patch(
            path + "/row", json={"properties": {"probe": "Updated"}}, headers=AUTH
        )
        assert changed.status_code == 200 and changed.json()["title"] == "Created"
        renamed = client.patch(path + "/row/title", json={"title": "Renamed"}, headers=AUTH)
        assert renamed.status_code == 200 and renamed.json()["title"] == "Renamed"
        assert renamed.json()["properties"] == {
            "probe": "Updated",
            "title": "Regular property",
            "links": ["invalid:out_of_scope"],
        }
        assert renamed.json()["content"] == [
            {"id": "child", "type": "text", "markdown": "Keep nested content"}
        ]
    assert [r.method for r in calls] == [
        "GET",
        "GET",
        "GET",
        "POST",
        "GET",
        "PUT",
        "GET",
        "GET",
        "PUT",
    ]


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize("profile", ["planner", "read-only", "migration"])
def test_rename_profile_permissions_and_exact_preflights(adapter, profile):
    calls = []

    def upstream(request):
        calls.append(request)
        assert profile == "planner"
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json=schema_for("task"))
        if request.method == "GET":
            return httpx.Response(200, json={"items": [{"id": "row", "task": "Original"}]})
        assert json.loads(request.content) == {"itemsToUpdate": [{"id": "row", "task": "Renamed"}]}
        return httpx.Response(200, json={"items": [{"id": "row", "task": "Renamed"}]})

    with TestClient(app_for(adapter, upstream, configuration(adapter, profile))) as client:
        response = client.patch(
            f"/profiles/{profile}/v1/{adapter}/collections/rows/items/row/title",
            headers=AUTH,
            json={"title": "Renamed"},
        )
        assert response.status_code == (200 if profile == "planner" else 403)
    assert [r.method for r in calls] == (["GET", "GET", "PUT"] if profile == "planner" else [])


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize("failure", ["collection", "item", "duplicate"])
def test_foreign_and_ambiguous_targets_never_mutate(adapter, failure):
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json=schema_for("task"))
        return httpx.Response(
            200,
            json={
                "items": [{"id": "row", "task": "Original"}] * 2
                if failure == "duplicate"
                else [{"id": "other", "task": "Other"}]
            },
        )

    with TestClient(app_for(adapter, upstream, configuration(adapter, "planner"))) as client:
        collection = "foreign" if failure == "collection" else "rows"
        response = client.patch(
            f"/profiles/planner/v1/{adapter}/collections/{collection}/items/row/title",
            headers=AUTH,
            json={"title": "Changed"},
        )
        assert response.status_code == (502 if failure == "duplicate" else 403)
        assert "outcomeUnknown" not in response.json()["error"]
    assert len(calls) == (0 if failure == "collection" else 2)


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": ""},
        {"title": None},
        {"title": 2},
        {"title": "New", "properties": {}},
        {"properties": {"task": "New"}},
    ],
)
def test_strict_title_body_never_contacts_craft(adapter, body):
    with TestClient(
        app_for(adapter, lambda request: pytest.fail("Invalid title must not contact Craft"))
    ) as client:
        result = client.patch(
            f"/v1/{adapter}/collections/rows/items/row/title", headers=AUTH, json=body
        )
        assert result.status_code == 422


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize(
    "key", ["id", "properties", "content", "markdown", "type", "contentPreviewMd", ""]
)
def test_reserved_or_empty_schema_keys_fail_before_submission(adapter, key):
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path.endswith("/schema")
        return httpx.Response(200, json=schema_for(key))

    with TestClient(app_for(adapter, upstream)) as client:
        result = client.post(
            f"/v1/{adapter}/collections/rows/items", headers=AUTH, json={"title": "New"}
        )
        assert result.status_code == 502
        assert "outcomeUnknown" not in result.json()["error"]
    assert len(calls) == 1


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize(
    "result",
    [
        {"items": []},
        {"items": [{}]},
        {"items": [{"id": "other"}]},
        {"items": [{"id": "row"}, {"id": "other"}]},
        {"items": [{"id": "row", "task": 1}]},
        {"items": [{"id": "row", "task": "Old"}]},
        {"items": [{"id": "row", "task": "New", "title": "Conflicting"}]},
    ],
)
def test_bad_rename_results_are_uncertain_and_not_retried(adapter, result):
    calls = []

    def upstream(request):
        calls.append(request)
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json=schema_for("task"))
        if request.method == "GET":
            return httpx.Response(200, json={"items": [{"id": "row", "task": "Original"}]})
        return httpx.Response(200, json=result)

    with TestClient(app_for(adapter, upstream)) as client:
        response = client.patch(
            f"/v1/{adapter}/collections/rows/items/row/title", headers=AUTH, json={"title": "New"}
        )
        assert response.status_code == 502
        assert response.json()["error"]["outcomeUnknown"] is True
    assert [r.method for r in calls] == ["GET", "GET", "PUT"]


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_partial_rename_response_does_not_fabricate_title(adapter):
    def upstream(request):
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json=schema_for("task"))
        return httpx.Response(200, json={"items": [{"id": "row"}]})

    with TestClient(app_for(adapter, upstream)) as client:
        response = client.patch(
            f"/v1/{adapter}/collections/rows/items/row/title", headers=AUTH, json={"title": "New"}
        )
        assert response.status_code == 200 and response.json() == {"id": "row"}


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_global_read_only_omits_rename(adapter):
    with TestClient(
        app_for(
            adapter,
            lambda request: pytest.fail("Disabled rename must not contact Craft"),
            configuration(adapter, "planner", wrapper_enabled_operations="read_only"),
        )
    ) as client:
        path = f"/v1/{adapter}/collections/rows/items/row/title"
        assert path not in client.get("/profiles/planner/openapi.json").json()["paths"]
        assert (
            client.patch(
                "/profiles/planner" + path, headers=AUTH, json={"title": "New"}
            ).status_code
            == 404
        )


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize("stage", ["schema", "membership", "mutation"])
def test_rename_deadline_distinguishes_submission(adapter, stage):
    calls = []

    async def upstream(request):
        calls.append(request)
        current = (
            "schema"
            if request.url.path.endswith("/schema")
            else "membership"
            if request.method == "GET"
            else "mutation"
        )
        if current == stage:
            await asyncio.sleep(3)
        return httpx.Response(
            200,
            json=schema_for("task")
            if current == "schema"
            else {"items": [{"id": "row", "task": "New"}]},
        )

    with TestClient(
        app_for(adapter, upstream, configuration(adapter, "planner", craft_timeout_seconds=1))
    ) as client:
        response = client.patch(
            f"/profiles/planner/v1/{adapter}/collections/rows/items/row/title",
            headers=AUTH,
            json={"title": "New"},
        )
        assert response.status_code == 504
        assert response.json()["error"].get("outcomeUnknown", False) is (stage == "mutation")
    assert len([r for r in calls if r.method != "GET"]) == (1 if stage == "mutation" else 0)


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_expiration_after_membership_prevents_rename(adapter):
    settings = configuration(adapter, "planner")

    def upstream(request):
        assert request.method == "GET"
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json=schema_for("task"))
        settings.profiles["planner"].expiresAt = datetime.now(UTC) - timedelta(seconds=1)
        return httpx.Response(200, json={"items": [{"id": "row", "task": "Original"}]})

    with TestClient(app_for(adapter, upstream, settings)) as client:
        response = client.patch(
            f"/profiles/planner/v1/{adapter}/collections/rows/items/row/title",
            headers=AUTH,
            json={"title": "New"},
        )
        assert response.status_code == 403 and response.json()["error"]["code"] == "profile_expired"


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_schema_and_row_read_share_one_overall_deadline(adapter):
    calls = []

    async def upstream(request):
        calls.append(request)
        await asyncio.sleep(0.7)
        return httpx.Response(
            200, json=schema_for("task") if request.url.path.endswith("/schema") else {"items": []}
        )

    with TestClient(
        app_for(adapter, upstream, configuration(adapter, craft_timeout_seconds=1))
    ) as client:
        response = client.get(f"/v1/{adapter}/collections/rows/items", headers=AUTH)
        assert response.status_code == 504
        assert "outcomeUnknown" not in response.json()["error"]
    assert len(calls) == 2 and all(r.method == "GET" for r in calls)


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_named_headline_workflow_through_standalone_tool(adapter, monkeypatch):
    path = Path(__file__).parents[1] / "integrations/openwebui" / f"craft_{adapter}_tool.py"
    spec = importlib.util.spec_from_file_location(f"headline_tool_{adapter}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tool = module.Tools()
    tool.valves.WRAPPER_URL = "http://wrapper.test"
    tool.valves.WRAPPER_PROFILE = "planner"
    tool.valves.WRAPPER_API_TOKEN = "headline-fixture-token"
    row: dict[str, Any] | None = None
    mutations = []

    def upstream(request):
        nonlocal row
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json=schema_for("task"))
        if request.method == "POST":
            change = json.loads(request.content)["items"][0]
            assert change == {"task": "Created", "properties": {"probe": "Keep"}}
            row = {
                "id": "row",
                **change,
                "content": [{"id": "child", "type": "text", "markdown": "Keep"}],
            }
            mutations.append("POST")
        elif request.method == "PUT":
            change = json.loads(request.content)["itemsToUpdate"][0]
            assert change == {"id": "row", "task": "Renamed"}
            assert row is not None
            row["task"] = change["task"]
            mutations.append("PUT")
        return httpx.Response(200, json={"items": [row] if row else []})

    app = app_for(adapter, upstream, configuration(adapter, "planner"))
    original = httpx.AsyncClient
    with TestClient(app):
        monkeypatch.setattr(
            module.httpx,
            "AsyncClient",
            lambda **kwargs: original(transport=httpx.ASGITransport(app), **kwargs),
        )

        async def run():
            created = await getattr(tool, f"craft_{adapter}_add_collection_item")(
                "rows", {"title": "Created", "properties": {"probe": "Keep"}}
            )
            assert created["statusCode"] == 201 and created["response"]["title"] == "Created"
            renamed = await getattr(tool, f"craft_{adapter}_update_collection_item_title")(
                "rows", "row", {"title": "Renamed"}
            )
            assert renamed["statusCode"] == 200 and renamed["response"]["title"] == "Renamed"
            listed = await getattr(tool, f"craft_{adapter}_list_collection_items")(
                "rows", {"maxDepth": -1}
            )
            assert listed["response"]["items"][0]["title"] == "Renamed"
            assert listed["response"]["items"][0]["properties"] == {"probe": "Keep"}
            assert listed["response"]["items"][0]["content"] == [
                {"id": "child", "type": "text", "markdown": "Keep"}
            ]

        asyncio.run(run())
    assert mutations == ["POST", "PUT"]

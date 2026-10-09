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

AUTH = {"Authorization": "Bearer content-fixture-token"}
ROOT: dict[str, Any] = {
    "id": "row",
    "type": "collectionItem",
    "markdown": "Headline",
    "content": [{"id": "body", "type": "text", "markdown": "Original context"}],
}
SCHEMA = {"name": "Rows", "contentPropDetails": {"key": "task", "name": "Task"}, "properties": []}


def configuration(adapter, profile="planner", **kwargs):
    urls: dict[str, str | None] = {
        f"craft_{a}_base_url": None for a in ("space", "documents", "daily")
    }
    urls[f"craft_{adapter}_base_url"] = (
        f"https://connect.craft.do/links/{adapter}-content-fixture/api/v1"
    )
    rules = None
    if profile:
        rule: dict[str, Any] = {"adapters": [adapter]}
        if profile == "planner":
            rule["writeTargets"] = {adapter: {"collectionIds": ["rows"]}}
        elif profile == "migration":
            urls["craft_space_base_url"] = (
                "https://connect.craft.do/links/space-content-fixture/api/v1"
            )
            rule.update(
                adapters=sorted({"space", adapter}),
                expiresAt=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                writeTargets={"space": {"collectionIds": ["rows"]}},
            )
        rules = json.dumps({profile: rule})
    return Settings(
        _env_file=None,
        **urls,
        wrapper_api_token="content-fixture-token",
        wrapper_planner_token="content-fixture-token",
        wrapper_read_only_token="content-fixture-token",
        wrapper_migration_token="content-fixture-token",
        wrapper_profiles_json=rules,
        **kwargs,
    )


def application(adapter, handler, settings=None):
    key = "upstream_transport" if adapter == "space" else f"{adapter}_upstream_transport"
    return create_app(settings or configuration(adapter), **{key: httpx.MockTransport(handler)})


def request(
    client,
    adapter,
    method,
    profile="planner",
    *,
    collection="rows",
    item="row",
    block="body",
    body=None,
):
    prefix = f"/profiles/{profile}" if profile else ""
    path = f"{prefix}/v1/{adapter}/collections/{collection}/items/{item}"
    path += "/content" if method == "POST" else f"/blocks/{block}"
    return client.request(method, path, headers=AUTH, json=body)


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize("profile", ["planner", None])
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_body_exact_mapping_and_full_verification(adapter, profile, method):
    calls = []

    def upstream(req):
        calls.append(req)
        assert req.url.path.startswith(f"/links/{adapter}-content-fixture/api/v1/")
        assert "authorization" not in req.headers
        assert req.headers["accept"] == "application/json"
        if req.url.path.endswith("/schema"):
            assert dict(req.url.params) == {"format": "schema"}
            return httpx.Response(200, json=SCHEMA)
        if req.url.path.endswith("/items"):
            assert dict(req.url.params) == {"maxDepth": "0"}
            return httpx.Response(
                200, json={"items": [{"id": "row", "task": "Headline", "properties": {}}]}
            )
        if req.method == "GET":
            assert dict(req.url.params) == {"id": "row", "maxDepth": "-1"}
            return httpx.Response(200, json=ROOT)
        assert not req.url.params
        assert req.method == ("PUT" if method == "PATCH" else method)
        expected = (
            {"markdown": "Context", "position": {"pageId": "row", "position": "start"}}
            if method == "POST"
            else {"blocks": [{"id": "body", "markdown": "Context"}]}
            if method == "PATCH"
            else {"blockIds": ["body"]}
        )
        assert json.loads(req.content) == expected
        return httpx.Response(
            200, json={"items": [{"id": "body", "type": "text", "markdown": "Context"}]}
        )

    settings = configuration(adapter, profile)
    with TestClient(application(adapter, upstream, settings)) as client:
        response = request(
            client,
            adapter,
            method,
            profile,
            body={"markdown": "Context", "position": "start"}
            if method == "POST"
            else {"markdown": "Context"}
            if method == "PATCH"
            else None,
        )
        assert response.status_code == (201 if method == "POST" else 200), response.text
        if method == "DELETE":
            assert response.json() == {"id": "body"}
        else:
            assert (response.json()["items"][0] if method == "POST" else response.json())[
                "id"
            ] == "body"
    assert [r.method for r in calls] == [
        "GET",
        "GET",
        "GET",
        "PUT" if method == "PATCH" else method,
    ]


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize("profile", ["read-only", "migration"])
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_read_only_and_migration_cannot_edit_bodies(adapter, profile, method):
    with TestClient(
        application(
            adapter,
            lambda req: pytest.fail("Excluded operation must not contact Craft"),
            configuration(adapter, profile),
        )
    ) as client:
        assert (
            request(
                client,
                adapter,
                method,
                profile,
                body={"markdown": "Context"} if method != "DELETE" else None,
            ).status_code
            == 403
        )


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_foreign_collection_denied_before_reads(adapter, method):
    with TestClient(
        application(adapter, lambda req: pytest.fail("Foreign collection must not contact Craft"))
    ) as client:
        assert (
            request(
                client,
                adapter,
                method,
                collection="foreign",
                body={"markdown": "Context"} if method != "DELETE" else None,
            ).status_code
            == 403
        )


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize(
    "failure",
    [
        "foreign-item",
        "duplicate-item",
        "wrong-root",
        "page-root",
        "missing-root-type",
        "preview",
        "empty-preview",
        "duplicate-block",
        "foreign-block",
        "linked-block",
        "property-id",
        "collection",
        "nested-item",
        "media",
        "descendants",
        "item-root",
    ],
)
def test_bad_membership_and_structure_never_delete(adapter, failure):
    root: dict[str, Any] = json.loads(json.dumps(ROOT))
    target = "row" if failure == "item-root" else "body"
    if failure == "wrong-root":
        root["id"] = "other"
    if failure == "page-root":
        root["type"] = "page"
    if failure == "missing-root-type":
        root.pop("type")
    if failure in ("preview", "empty-preview"):
        root["contentPreviewMd"] = "Omitted" if failure == "preview" else ""
    if failure == "duplicate-block":
        root["content"] *= 2
    if failure in ("foreign-block", "linked-block", "property-id"):
        root["content"] = [{"id": "other", "type": "text", "markdown": "[Context](block://body)"}]
        root["properties"] = {"relation": "body"}
    if failure == "collection":
        root["content"] = [{"id": "nested", "type": "collection", "content": ROOT["content"]}]
    if failure == "nested-item":
        root["content"] = [
            {"id": "nested-row", "type": "collectionItem", "content": ROOT["content"]}
        ]
    if failure == "media":
        root["content"] = [{"id": "body", "type": "image", "url": "https://media.example/image"}]
    if failure == "descendants":
        root["content"] = [
            {"id": "body", "type": "text", "content": [{"id": "child", "type": "text"}]}
        ]
    calls = []

    def upstream(req):
        calls.append(req)
        assert req.method == "GET"
        if req.url.path.endswith("/schema"):
            return httpx.Response(200, json=SCHEMA)
        if req.url.path.endswith("/items"):
            rows = (
                [{"id": "other"}]
                if failure == "foreign-item"
                else [{"id": "row"}] * 2
                if failure == "duplicate-item"
                else [{"id": "row"}]
            )
            return httpx.Response(200, json={"items": rows})
        return httpx.Response(200, json=root)

    with TestClient(application(adapter, upstream)) as client:
        response = request(client, adapter, "DELETE", block=target)
        assert response.status_code in (403, 502), response.text
        assert "outcomeUnknown" not in response.json()["error"]
    assert all(r.method == "GET" for r in calls)


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize(
    "method,body",
    [
        ("POST", {}),
        ("POST", {"markdown": ""}),
        ("POST", {"markdown": "Context", "properties": {}}),
        ("PATCH", {"markdown": None}),
        ("PATCH", {"markdown": "New", "title": "Changed"}),
    ],
)
def test_invalid_body_inputs_prevent_reads(adapter, method, body):
    with TestClient(
        application(adapter, lambda req: pytest.fail("Invalid body must not contact Craft"))
    ) as client:
        assert request(client, adapter, method, body=body).status_code == 422


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
@pytest.mark.parametrize(
    "items",
    [
        [],
        [{}],
        [{"id": "other", "type": "text"}],
        [{"id": "body", "type": "text"}, {"id": "other", "type": "text"}],
    ],
)
def test_bad_mutation_results_are_uncertain_and_not_retried(adapter, method, items):
    calls = []

    def upstream(req):
        calls.append(req)
        if req.url.path.endswith("/schema"):
            return httpx.Response(200, json=SCHEMA)
        if req.url.path.endswith("/items"):
            return httpx.Response(200, json={"items": [{"id": "row"}]})
        return httpx.Response(200, json=ROOT if req.method == "GET" else {"items": items})

    with TestClient(application(adapter, upstream)) as client:
        result = request(
            client, adapter, method, body={"markdown": "New"} if method == "PATCH" else None
        )
        assert result.status_code == 502
        assert result.json()["error"]["outcomeUnknown"] is True
    assert len([r for r in calls if r.method != "GET"]) == 1


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize("stage", ["structure", "submission"])
def test_combined_deadline_and_expiration_guard(adapter, stage):
    calls = []

    async def upstream(req):
        calls.append(req)
        if req.url.path.endswith("/schema"):
            return httpx.Response(200, json=SCHEMA)
        if req.url.path.endswith("/items"):
            return httpx.Response(200, json={"items": [{"id": "row"}]})
        if (req.method == "GET") == (stage == "structure"):
            await asyncio.sleep(3)
        return httpx.Response(
            200, json=ROOT if req.method == "GET" else {"items": [{"id": "body", "type": "text"}]}
        )

    with TestClient(
        application(adapter, upstream, configuration(adapter, craft_timeout_seconds=1))
    ) as client:
        result = request(client, adapter, "PATCH", body={"markdown": "New"})
        assert result.status_code == 504
        assert result.json()["error"].get("outcomeUnknown", False) == (stage == "submission")


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_expiration_after_structural_proof_prevents_mutation(adapter):
    settings = configuration(adapter)

    def upstream(req):
        assert req.method == "GET"
        if req.url.path.endswith("/schema"):
            return httpx.Response(200, json=SCHEMA)
        if req.url.path.endswith("/items"):
            return httpx.Response(200, json={"items": [{"id": "row"}]})
        settings.profiles["planner"].expiresAt = datetime.now(UTC) - timedelta(seconds=1)
        return httpx.Response(200, json=ROOT)

    with TestClient(application(adapter, upstream, settings)) as client:
        result = request(client, adapter, "PATCH", body={"markdown": "New"})
        assert result.status_code == 403 and result.json()["error"]["code"] == "profile_expired"


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_read_only_upper_bound_omits_body_routes(adapter):
    with TestClient(
        application(
            adapter,
            lambda req: pytest.fail("Disabled route must not contact Craft"),
            configuration(adapter, wrapper_enabled_operations="read_only"),
        )
    ) as client:
        for method in ("POST", "PATCH", "DELETE"):
            assert (
                request(
                    client,
                    adapter,
                    method,
                    body={"markdown": "New"} if method != "DELETE" else None,
                ).status_code
                == 404
            )


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_item_body_workflow_and_captured_confirmation_through_tool(adapter, monkeypatch):
    path = Path(__file__).parents[1] / "integrations" / "openwebui" / f"craft_{adapter}_tool.py"
    spec = importlib.util.spec_from_file_location(f"content_tool_{adapter}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tool = module.Tools()
    tool.valves.WRAPPER_URL = "http://wrapper.test"
    tool.valves.WRAPPER_PROFILE = "planner"
    tool.valves.WRAPPER_API_TOKEN = "content-fixture-token"
    text = "Context"
    exists = False
    mutations = []

    def upstream(req):
        nonlocal exists, text
        if req.url.path.endswith("/schema"):
            return httpx.Response(200, json=SCHEMA)
        if req.url.path.endswith("/items"):
            return httpx.Response(
                200,
                json={
                    "items": [{"id": "row", "task": "Headline", "properties": {"probe": "Keep"}}]
                },
            )
        if req.method == "GET":
            if req.url.params["id"] == "body":
                return httpx.Response(200, json={"id": "body", "type": "text", "markdown": text})
            if req.headers["accept"] == "text/markdown":
                return httpx.Response(
                    200, text=f"Headline\n\n{text}", headers={"content-type": "text/markdown"}
                )
            return httpx.Response(
                200,
                json={
                    "id": "row",
                    "type": "collectionItem",
                    "content": [{"id": "body", "type": "text", "markdown": text}] if exists else [],
                },
            )
        mutations.append(req.method)
        if req.method == "POST":
            exists = True
        elif req.method == "PUT":
            text = json.loads(req.content)["blocks"][0]["markdown"]
        else:
            exists = False
        return httpx.Response(
            200, json={"items": [{"id": "body", "type": "text", "markdown": text}]}
        )

    app = application(adapter, upstream)
    original = httpx.AsyncClient
    with TestClient(app):
        monkeypatch.setattr(
            module.httpx,
            "AsyncClient",
            lambda **kwargs: original(transport=httpx.ASGITransport(app), **kwargs),
        )

        async def run():
            inserted = await getattr(tool, f"craft_{adapter}_insert_collection_item_markdown")(
                "rows", "row", {"markdown": "Context"}
            )
            assert inserted["statusCode"] == 201
            edited = await getattr(tool, f"craft_{adapter}_update_collection_item_block_markdown")(
                "rows", "row", "body", {"markdown": "Updated context"}
            )
            assert edited["statusCode"] == 200
            read = await getattr(tool, f"craft_{adapter}_read_markdown")("row", {"maxDepth": -1})
            assert "Updated context" in read["response"]["markdown"]

            async def cancel(event):
                assert "Collection ID: rows" in event["data"]["message"]
                assert (
                    "Item ID: row" in event["data"]["message"]
                    and "Block ID: body" in event["data"]["message"]
                )
                assert "only the selected leaf body text block" in event["data"]["message"]
                assert "all nested item content" not in event["data"]["message"]
                return False

            delete = getattr(tool, f"craft_{adapter}_delete_collection_item_block")
            canceled = await delete("rows", "row", "body", __event_call__=cancel)
            assert canceled["response"]["error"]["code"] == "tool_confirmation_declined" and exists

            async def approve(event):
                return True

            result = await delete("rows", "row", "body", __event_call__=approve)
            assert result["statusCode"] == 200 and result["response"] == {"id": "body"}
            assert not exists

        asyncio.run(run())
    assert mutations == ["POST", "PUT", "DELETE"]


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
@pytest.mark.parametrize("malformed", ["root-id", "root-type"])
def test_body_deletion_preview_cannot_prompt_for_a_different_resource(
    adapter, monkeypatch, malformed
):
    path = Path(__file__).parents[1] / "integrations" / "openwebui" / f"craft_{adapter}_tool.py"
    spec = importlib.util.spec_from_file_location(f"content_preview_{adapter}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tool = module.Tools()
    tool.valves.WRAPPER_URL = "http://wrapper.test"
    tool.valves.WRAPPER_API_TOKEN = "preview-fixture-token"
    calls = []
    original = httpx.AsyncClient

    def upstream(req):
        calls.append(req)
        assert req.method == "GET" and req.url.path == f"/v1/{adapter}/blocks/body"
        assert dict(req.url.params) == {"maxDepth": "0"}
        return httpx.Response(
            200,
            json={
                "id": "wrong" if malformed == "root-id" else "body",
                "type": "page" if malformed == "root-type" else "text",
                "markdown": "Preview",
            },
        )

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(upstream), **kwargs),
    )

    async def confirm(event):
        pytest.fail("An unreadable or non-text body block must not prompt")

    result = asyncio.run(
        getattr(tool, f"craft_{adapter}_delete_collection_item_block")(
            "rows", "row", "body", __event_call__=confirm
        )
    )
    assert result["response"]["error"]["code"] == "tool_preview_unavailable"
    assert result["response"]["error"]["outcomeUnknown"] is False
    assert len(calls) == 1


@pytest.mark.parametrize("adapter", ["space", "documents", "daily"])
def test_new_body_permissions_do_not_enable_generic_document_bypass(adapter):
    settings = configuration(adapter)
    settings.profiles["planner"].writeTargets[adapter].documentIds = ["document"]

    def upstream(req):
        assert req.method == "GET"
        return httpx.Response(200, json={"id": "document", "type": "page", "content": [ROOT]})

    query = {"date": "today"} if adapter == "daily" else {"documentId": "document"}
    with TestClient(application(adapter, upstream, settings)) as client:
        result = client.patch(
            f"/profiles/planner/v1/{adapter}/blocks/body",
            params=query,
            headers=AUTH,
            json={"markdown": "Bypass"},
        )
        assert result.status_code == 403

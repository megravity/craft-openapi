import asyncio
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from pydantic import SecretStr

from craft_wrapper.config import Settings
from craft_wrapper.main import create_app

ROOT_ID = "planning-root"
ROOT: dict[str, Any] = {
    "id": ROOT_ID,
    "type": "page",
    "content": [{"id": "task", "type": "text", "markdown": "- [ ] Example task"}],
}
AUTH = {"Authorization": "Bearer task-fixture-token"}
PREFIX = "/profiles/planner/v1/space"


def settings_for(profile: str | None = "planner", **kwargs):
    profiles: dict[str, Any] = {}
    if profile is not None:
        profiles[profile] = {
            "adapters": ["space"],
            **(
                {"writeTargets": {"space": {"documentIds": [ROOT_ID]}}}
                if profile == "planner"
                else {}
            ),
        }
    if profile == "migration":
        profiles[profile].update(
            expiresAt=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            writeTargets={"space": {"collectionIds": ["backlog"]}},
        )
    return Settings(
        _env_file=None,
        craft_space_base_url="https://connect.craft.do/links/space-task-fixture/api/v1",
        wrapper_api_token="task-fixture-token",
        wrapper_planner_token="task-fixture-token",
        wrapper_read_only_token="task-fixture-token",
        wrapper_migration_token="task-fixture-token",
        wrapper_profiles_json=json.dumps(profiles) if profile else None,
        **kwargs,
    )


def call(client, method, *, prefix=PREFIX, target="task", body=None, document_id=ROOT_ID):
    path = prefix + "/tasks" + ("" if method == "POST" else f"/{target}")
    return client.request(
        method,
        path,
        headers=AUTH,
        params={} if method == "POST" or document_id is None else {"documentId": document_id},
        json=body,
    )


@pytest.mark.parametrize("profile", ["planner", None])
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_space_task_write_exact_contract_and_connection(profile, method):
    calls = []
    body = (
        {
            "documentId": ROOT_ID,
            "markdown": "Example",
            "scheduleDate": "tomorrow",
            "deadlineDate": "2026-11-01",
        }
        if method == "POST"
        else {"state": "done", "markdown": "Updated", "scheduleDate": "today"}
        if method == "PATCH"
        else None
    )

    def upstream(request):
        calls.append(request)
        assert request.url.path.startswith("/links/space-task-fixture/api/v1/")
        assert "authorization" not in request.headers
        assert request.headers["accept"] == "application/json"
        if request.url.path.endswith("/blocks"):
            assert dict(request.url.params) == {"id": ROOT_ID, "maxDepth": "-1"}
            return httpx.Response(200, json=ROOT)
        if request.method == "GET":
            assert dict(request.url.params) == {"scope": "document", "documentId": ROOT_ID}
            return httpx.Response(200, json={"items": [{"id": "task"}]})
        assert not request.url.params
        expected = (
            {
                "tasks": [
                    {
                        "markdown": "Example",
                        "location": {"type": "document", "documentId": ROOT_ID},
                        "taskInfo": {"scheduleDate": "tomorrow", "deadlineDate": "2026-11-01"},
                    }
                ]
            }
            if method == "POST"
            else {
                "tasksToUpdate": [
                    {
                        "id": "task",
                        "markdown": "Updated",
                        "taskInfo": {"state": "done", "scheduleDate": "today"},
                    }
                ]
            }
            if method == "PATCH"
            else {"idsToDelete": ["task"]}
        )
        assert json.loads(request.content) == expected
        assert request.method == ("PUT" if method == "PATCH" else method)
        return httpx.Response(200, json={"items": [{"id": "task"}]})

    settings = settings_for(profile)
    settings.craft_daily_base_url = SecretStr(
        "https://connect.craft.do/links/daily-task-fixture/api/v1"
    )

    def wrong_connection(request):
        pytest.fail("Space task operations must never use Daily")

    app = create_app(
        settings,
        upstream_transport=httpx.MockTransport(upstream),
        daily_upstream_transport=httpx.MockTransport(wrong_connection),
    )
    with TestClient(app) as client:
        result = call(client, method, prefix=PREFIX if profile else "/v1/space", body=body)
        assert result.status_code == (201 if method == "POST" else 200), result.text
        assert result.json() == {"id": "task"}
    assert [r.method for r in calls] == (
        ["GET", "POST"]
        if method == "POST"
        else ["GET", "GET", "PUT" if method == "PATCH" else "DELETE"]
    )


@pytest.mark.parametrize(
    "method,body,context",
    [
        ("POST", {"markdown": "Missing owner"}, ROOT_ID),
        ("POST", {"documentId": ROOT_ID, "markdown": ""}, ROOT_ID),
        ("POST", {"documentId": ROOT_ID, "markdown": "Task", "target": "inbox"}, ROOT_ID),
        ("POST", {"documentId": ROOT_ID, "markdown": "Task", "scheduleDate": None}, ROOT_ID),
        (
            "POST",
            {"documentId": ROOT_ID, "markdown": "Task", "deadlineDate": "2026-02-30"},
            ROOT_ID,
        ),
        ("PATCH", {}, ROOT_ID),
        ("PATCH", {"state": None}, ROOT_ID),
        ("PATCH", {"scheduleDate": None}, ROOT_ID),
        ("PATCH", {"markdown": ""}, ROOT_ID),
        ("PATCH", {"state": "done", "documentId": "foreign"}, ROOT_ID),
        ("PATCH", {"state": "unknown"}, ROOT_ID),
        ("PATCH", {"location": {"type": "inbox"}}, ROOT_ID),
        ("PATCH", {"state": "done"}, None),
        ("DELETE", None, None),
    ],
)
def test_invalid_inputs_never_contact_craft(method, body, context):
    def upstream(request):
        pytest.fail("Invalid requests must not contact Craft")

    with TestClient(
        create_app(settings_for(), upstream_transport=httpx.MockTransport(upstream))
    ) as client:
        result = call(client, method, body=body, document_id=context)
        assert result.status_code == 422
        assert result.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_unapproved_documents_denied_before_upstream(method):
    def upstream(request):
        pytest.fail("Foreign roots must not contact Craft")

    with TestClient(
        create_app(settings_for(), upstream_transport=httpx.MockTransport(upstream))
    ) as client:
        result = call(
            client,
            method,
            document_id="foreign",
            body={"documentId": "foreign", "markdown": "Task"}
            if method == "POST"
            else {"state": "done"}
            if method == "PATCH"
            else None,
        )
        assert result.status_code == 403


@pytest.mark.parametrize("profile", ["read-only", "migration"])
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_read_only_and_migration_cannot_write_tasks(profile, method):
    def upstream(request):
        pytest.fail("Excluded operations must not contact Craft")

    with TestClient(
        create_app(settings_for(profile), upstream_transport=httpx.MockTransport(upstream))
    ) as client:
        result = call(client, method, prefix=f"/profiles/{profile}/v1/space")
        assert result.status_code == 403
        assert result.json()["error"]["code"] == "permission_denied"


@pytest.mark.parametrize("case", ["foreign", "linked", "collection", "plain", "nested", "root"])
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_structural_and_native_task_membership_fail_closed(case, method):
    calls = []
    target = ROOT_ID if case == "root" else "task"
    root: dict[str, Any] = {"id": ROOT_ID, "type": "page", "content": []}
    if case == "linked":
        root["content"] = [{"id": "text", "type": "text", "markdown": "[Task](block://task)"}]
    elif case == "collection":
        root["content"] = [{"id": "c", "type": "collection", "content": ROOT["content"]}]
    elif case in {"plain", "nested"}:
        root["content"] = [
            {
                "id": "task",
                "type": "text",
                **({"content": [{"id": "child", "type": "text"}]} if case == "nested" else {}),
            }
        ]

    def upstream(request):
        calls.append(request)
        if request.method != "GET":
            if case == "nested" and method == "PATCH":
                assert json.loads(request.content) == {
                    "tasksToUpdate": [{"id": "task", "taskInfo": {"state": "done"}}]
                }
                return httpx.Response(200, json={"items": [{"id": "task"}]})
            pytest.fail("Denied tasks must not mutate")
        if request.url.path.endswith("/blocks"):
            return httpx.Response(200, json=root)
        return httpx.Response(200, json={"items": [] if case == "plain" else [{"id": "task"}]})

    with TestClient(
        create_app(settings_for(), upstream_transport=httpx.MockTransport(upstream))
    ) as client:
        result = call(
            client, method, target=target, body={"state": "done"} if method == "PATCH" else None
        )
        assert result.status_code == (200 if case == "nested" and method == "PATCH" else 403)
    assert calls
    assert len([r for r in calls if r.method != "GET"]) == (
        1 if case == "nested" and method == "PATCH" else 0
    )


@pytest.mark.parametrize(
    "root",
    [
        {"id": "wrong", "type": "page"},
        {"id": ROOT_ID, "type": "text"},
        {"id": ROOT_ID, "type": "page", "contentPreviewMd": "omitted"},
        {"id": ROOT_ID, "type": "page", "content": [{"id": "task"}]},
        {"id": ROOT_ID, "type": "page", "content": ROOT["content"] * 2},
    ],
)
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_malformed_root_prevents_mutation(root, method):
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.method == "GET"
        return httpx.Response(200, json=root)

    with TestClient(
        create_app(settings_for(), upstream_transport=httpx.MockTransport(upstream))
    ) as client:
        result = call(
            client,
            method,
            body={"documentId": ROOT_ID, "markdown": "Task"}
            if method == "POST"
            else {"state": "done"}
            if method == "PATCH"
            else None,
        )
        assert result.status_code == 502
        assert "outcomeUnknown" not in result.json()["error"]
    assert len(calls) == 1


@pytest.mark.parametrize("items", [[], [{}], [{"id": "wrong"}], [{"id": "task"}, {"id": "other"}]])
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_uncertain_mutation_results_never_fabricated_or_retried(items, method):
    calls = []

    def upstream(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=ROOT if request.url.path.endswith("/blocks") else {"items": [{"id": "task"}]},
            )
        return httpx.Response(200, json={"items": items})

    with TestClient(
        create_app(settings_for(), upstream_transport=httpx.MockTransport(upstream))
    ) as client:
        result = call(client, method, body={"state": "done"} if method == "PATCH" else None)
        assert result.status_code == 502
        assert result.json()["error"]["outcomeUnknown"] is True
    assert len([r for r in calls if r.method != "GET"]) == 1


@pytest.mark.parametrize("stage", ["structure", "tasks", "mutation"])
def test_overall_deadline_covers_all_task_write_phases(stage):
    calls = []

    async def upstream(request):
        calls.append(request)
        current = (
            "mutation"
            if request.method != "GET"
            else "structure"
            if request.url.path.endswith("/blocks")
            else "tasks"
        )
        if current == stage:
            await asyncio.sleep(3)
        return httpx.Response(
            200, json=ROOT if current == "structure" else {"items": [{"id": "task"}]}
        )

    with TestClient(
        create_app(
            settings_for(craft_timeout_seconds=1),
            upstream_transport=httpx.MockTransport(upstream),
        )
    ) as client:
        result = call(client, "PATCH", body={"state": "done"})
        assert result.status_code == 504
        assert result.json()["error"].get("outcomeUnknown", False) is (stage == "mutation")
    assert len([r for r in calls if r.method != "GET"]) == (1 if stage == "mutation" else 0)


def test_profile_expiration_after_proof_prevents_submission():
    settings = settings_for()

    def upstream(request):
        assert request.method == "GET"
        if request.url.path.endswith("/blocks"):
            return httpx.Response(200, json=ROOT)
        settings.profiles["planner"].expiresAt = datetime.now(UTC) - timedelta(seconds=1)
        return httpx.Response(200, json={"items": [{"id": "task"}]})

    with TestClient(
        create_app(settings, upstream_transport=httpx.MockTransport(upstream))
    ) as client:
        result = call(client, "PATCH", body={"state": "done"})
        assert result.status_code == 403
        assert result.json()["error"]["code"] == "profile_expired"


def test_task_only_profile_capabilities_and_schema():
    settings = settings_for(wrapper_enabled_operations="craft_space_update_task")
    app = create_app(settings)
    with TestClient(app) as client:
        capabilities = client.get("/profiles/planner/capabilities", headers=AUTH).json()
        assert capabilities["operations"] == ["craft_space_update_task"]
        assert capabilities["writeTargets"]["space"]["documentIds"] == [ROOT_ID]
        schema = client.get("/profiles/planner/openapi.json").json()
        validate(schema)
        assert ROOT_ID not in json.dumps(schema)
        assert set(schema["paths"]) == {"/v1/space/tasks/{taskId}"}
        parameters = schema["paths"]["/v1/space/tasks/{taskId}"]["patch"]["parameters"]
        assert next(p for p in parameters if p["name"] == "documentId")["required"] is True


@pytest.mark.parametrize(
    "value", [{"items": [{"id": "task"}, {"id": "task"}]}, {"items": [{}]}, {"items": "invalid"}]
)
def test_invalid_native_task_proof_prevents_mutation(value):
    calls = []

    def upstream(request):
        calls.append(request)
        assert request.method == "GET"
        return httpx.Response(200, json=ROOT if request.url.path.endswith("/blocks") else value)

    with TestClient(
        create_app(settings_for(), upstream_transport=httpx.MockTransport(upstream))
    ) as client:
        result = call(client, "PATCH", body={"state": "done"})
        assert result.status_code == 502
        assert "outcomeUnknown" not in result.json()["error"]
    assert len(calls) == 2


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_global_read_only_omits_task_writes(method):
    def upstream(request):
        pytest.fail("Globally disabled task writes must not contact Craft")

    with TestClient(
        create_app(
            settings_for(wrapper_enabled_operations="read_only"),
            upstream_transport=httpx.MockTransport(upstream),
        )
    ) as client:
        assert call(client, method).status_code == 404


def test_task_create_omits_unsupplied_dates_and_safely_encodes_root():
    root_id = "opaque root/?#"
    calls = []

    def upstream(request):
        calls.append(request)
        if request.method == "GET":
            assert dict(request.url.params) == {"id": root_id, "maxDepth": "-1"}
            return httpx.Response(200, json={"id": root_id, "type": "page"})
        assert json.loads(request.content) == {
            "tasks": [
                {"markdown": "Example", "location": {"type": "document", "documentId": root_id}}
            ]
        }
        return httpx.Response(200, json={"items": [{"id": "task"}]})

    with TestClient(
        create_app(settings_for(None), upstream_transport=httpx.MockTransport(upstream))
    ) as client:
        result = call(
            client, "POST", prefix="/v1/space", body={"documentId": root_id, "markdown": "Example"}
        )
        assert result.status_code == 201
    assert [r.method for r in calls] == ["GET", "POST"]


@pytest.mark.parametrize("items", [[], [{}], [{"id": ""}], [{"id": "a"}, {"id": "b"}]])
def test_create_uncertain_results_not_retried(items):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json=ROOT if request.method == "GET" else {"items": items})

    with TestClient(
        create_app(settings_for(), upstream_transport=httpx.MockTransport(upstream))
    ) as client:
        result = call(client, "POST", body={"documentId": ROOT_ID, "markdown": "Example"})
        assert result.status_code == 502
        assert result.json()["error"]["outcomeUnknown"] is True
    assert [r.method for r in calls] == ["GET", "POST"]


def test_task_workflow_through_profile_tool_and_confirmation(monkeypatch):
    path = Path(__file__).parents[1] / "integrations/openwebui/craft_space_tool.py"
    spec = importlib.util.spec_from_file_location("space_task_workflow_tool", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tool = module.Tools()
    tool.valves.WRAPPER_URL = "http://wrapper.test"
    tool.valves.WRAPPER_PROFILE = "planner"
    tool.valves.WRAPPER_API_TOKEN = "task-fixture-token"
    exists = False
    info = {"state": "todo", "scheduleDate": "tomorrow"}
    calls = []

    def upstream(request):
        nonlocal exists
        calls.append(request)
        if request.url.path.endswith("/blocks"):
            if request.url.params.get("id") == "task":
                return httpx.Response(200, json=ROOT["content"][0])
            return httpx.Response(200, json={**ROOT, "content": ROOT["content"] if exists else []})
        if request.method == "POST":
            exists = True
        elif request.method == "PUT":
            info.update(json.loads(request.content)["tasksToUpdate"][0]["taskInfo"])
        elif request.method == "DELETE":
            exists = False
            return httpx.Response(200, json={"items": [{"id": "task"}]})
        return httpx.Response(
            200, json={"items": [{"id": "task", "taskInfo": info}] if exists else []}
        )

    app = create_app(settings_for(), upstream_transport=httpx.MockTransport(upstream))
    original = httpx.AsyncClient
    with TestClient(app):
        monkeypatch.setattr(
            module.httpx,
            "AsyncClient",
            lambda **kwargs: original(transport=httpx.ASGITransport(app), **kwargs),
        )

        async def run():
            created = await tool.craft_space_add_task(
                {"documentId": ROOT_ID, "markdown": "Example", "scheduleDate": "tomorrow"}
            )
            assert created["statusCode"] == 201
            updated = await tool.craft_space_update_task(
                "task", {"state": "done"}, {"documentId": ROOT_ID}
            )
            assert updated["statusCode"] == 200
            assert updated["response"]["taskInfo"] == {"state": "done", "scheduleDate": "tomorrow"}

            async def cancel(event):
                assert ROOT_ID in event["data"]["message"]
                return False

            canceled = await tool.craft_space_delete_task(
                "task", {"documentId": ROOT_ID}, __event_call__=cancel
            )
            assert canceled["response"]["error"]["code"] == "tool_confirmation_declined"
            assert exists

            async def approve(event):
                return True

            deleted = await tool.craft_space_delete_task(
                "task", {"documentId": ROOT_ID}, __event_call__=approve
            )
            assert deleted["statusCode"] == 200 and deleted["response"] == {"id": "task"}
            assert not exists

        asyncio.run(run())
    assert [r.method for r in calls if r.method != "GET"] == ["POST", "PUT", "DELETE"]

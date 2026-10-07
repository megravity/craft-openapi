import json
import re
import tomllib
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from pydantic import ValidationError

from craft_wrapper.config import SPACE_OPERATION_IDS as OPERATION_IDS
from craft_wrapper.config import Settings, load_settings
from craft_wrapper.main import create_app


def operations(spec):
    return [
        operation
        for path in spec["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "patch", "put", "delete"}
    ]


def test_release_versions_match_package_schema_image_and_tool(settings):
    root = Path(__file__).parents[1]
    release = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", release)
    assert version("craft-openapi-wrapper") == release
    assert create_app(settings).openapi()["info"]["version"] == release
    assert (
        f'LABEL org.opencontainers.image.version="{release}"' in (root / "Dockerfile").read_text()
    )
    for filename in ("craft_space_tool.py", "craft_documents_tool.py", "craft_daily_tool.py"):
        tool_metadata = (root / "integrations/openwebui" / filename).read_text().split('"""')[1]
        assert f"version: {release}" in tool_metadata.splitlines()
    assert f"## {release} — " in (root / "CHANGELOG.md").read_text()


@pytest.mark.parametrize("preset", [None, "full"])
def test_openapi_valid_and_exact_operation_set(settings, preset):
    settings.wrapper_enabled_operations = preset
    spec = create_app(settings).openapi()
    validate(spec)
    assert spec["openapi"] == "3.1.0"
    ops = operations(spec)
    assert len(ops) == 16
    assert {op["operationId"] for op in ops} == OPERATION_IDS
    assert all(op["security"] == [{"WrapperBearer": []}] for op in ops)
    assert all(op["description"] and op["summary"] for op in ops)
    assert {"/health", "/docs", "/openapi.json"}.isdisjoint(spec["paths"])
    assert "servers" not in spec
    rendered = json.dumps(spec)
    assert "testing-link-secret" not in rendered
    assert "test-wrapper-token" not in rendered
    assert "connect.craft.do/links" not in rendered
    for op in ops:
        for status in ("400", "401", "404", "409", "413", "422", "429", "500", "502", "503", "504"):
            assert op["responses"][status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
    schema = spec["components"]["schemas"]
    assert schema["CreateDocument"]["additionalProperties"] is False
    assert schema["AddCollectionItem"]["properties"]["properties"]["additionalProperties"] == {
        "type": "string"
    }


READ_ONLY_IDS = {
    "craft_space_list_folders",
    "craft_space_list_tasks",
    "craft_space_list_documents",
    "craft_space_search_documents",
    "craft_space_get_block",
    "craft_space_read_markdown",
    "craft_space_list_collections",
    "craft_space_get_collection_schema",
    "craft_space_list_collection_items",
}


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, OPERATION_IDS),
        ("full", OPERATION_IDS),
        ("Full", OPERATION_IDS),
        (" FULL ", OPERATION_IDS),
        ("read_only", READ_ONLY_IDS),
        ("Read Only", READ_ONLY_IDS),
        ("read-only", READ_ONLY_IDS),
        (" READ_ONLY ", READ_ONLY_IDS),
        (
            "craft_space_list_documents, craft_space_get_block,craft_space_list_documents",
            {"craft_space_list_documents", "craft_space_get_block"},
        ),
    ],
)
def test_operation_presets_and_explicit_lists(value, expected):
    settings = Settings(
        _env_file=None,
        craft_space_base_url="https://connect.craft.do/links/private/api/v1",
        wrapper_api_token="token",
        wrapper_enabled_operations=value,
    )
    assert settings.enabled_operations == expected


def test_read_only_preset_removes_all_write_routes_and_schema(settings):
    settings.wrapper_enabled_operations = "read_only"
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        return httpx.Response(200, json={"items": []})

    app = create_app(settings, upstream_transport=httpx.MockTransport(handler))
    spec = app.openapi()
    assert {op["operationId"] for op in operations(spec)} == READ_ONLY_IDS
    assert all(set(path) == {"get"} for path in spec["paths"].values())
    validate(spec)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-wrapper-token"}
        assert client.get("/v1/space/documents", headers=headers).status_code == 200
        for method, path, body in [
            ("POST", "/documents", {"title": "Disabled"}),
            ("POST", "/blocks/page/content", {"markdown": "Disabled"}),
            ("PATCH", "/blocks/block", {"markdown": "Disabled"}),
            ("POST", "/collections/collection/items", {"title": "Disabled"}),
            (
                "PATCH",
                "/collections/collection/items/item",
                {"properties": {"status": "Disabled"}},
            ),
        ]:
            assert (
                client.request(method, "/v1/space" + path, json=body, headers=headers).status_code
                == 404
            )
        assert client.get("/health").status_code == 200
        assert client.get("/openapi.json").status_code == 200
    assert len(calls) == 1


def test_allowlist_removes_http_routes_and_schema(settings):
    settings.wrapper_enabled_operations = "craft_space_list_documents"

    def handler(request):
        return httpx.Response(200, json={"items": []})

    app = create_app(settings, upstream_transport=httpx.MockTransport(handler))
    assert [op["operationId"] for op in operations(app.openapi())] == ["craft_space_list_documents"]
    validate(app.openapi())
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-wrapper-token"}
        assert client.get("/v1/space/documents", headers=headers).status_code == 200
        assert client.get("/v1/space/collections", headers=headers).status_code == 404
        assert client.get("/v1/space/blocks/b", headers=headers).status_code == 404
        assert (
            client.post(
                "/v1/space/documents", headers=headers, json={"title": "Disabled"}
            ).status_code
            == 404
        )
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "url",
    [
        "http://connect.craft.do/links/private/api/v1",
        "https://evil.test/links/private/api/v1",
        "https://connect.craft.do/links/private/api/v1?token=secret",
        "https://connect.craft.do/links/private/api/v1#fragment",
        "https://name:secret@connect.craft.do/links/private/api/v1",
        "https://connect.craft.do/links/../api/v1",
        "https://connect.craft.do/links/REPLACE_ME/api/v1",
        "https://connect.craft.do/links/private/other",
        "secret-input",
    ],
)
def test_config_rejects_invalid_craft_urls_without_values(url):
    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None, craft_space_base_url=url, wrapper_api_token="private-token")
    assert url not in str(raised.value)
    assert "private-token" not in str(raised.value)


@pytest.mark.parametrize(
    "allowlist",
    [
        "",
        " ",
        "unknown",
        "craft_space_list_documents,",
        ",craft_space_list_documents",
        "full,craft_space_list_documents",
        "read_only,craft_space_create_document",
        "read_only,full",
        "read_only,",
        "CRAFT_SPACE_LIST_DOCUMENTS",
    ],
)
def test_invalid_allowlist(allowlist):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            craft_space_base_url="https://connect.craft.do/links/private/api/v1",
            wrapper_api_token="token",
            wrapper_enabled_operations=allowlist,
        )


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeouts(timeout):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            craft_space_base_url="https://connect.craft.do/links/private/api/v1",
            wrapper_api_token="token",
            craft_timeout_seconds=timeout,
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@wrapper.test",
        "https://wrapper.test/links/private",
        "https://wrapper.test?secret=private",
        "https://wrapper.test#secret",
        "https://wrapper.test?",
        "https://wrapper.test\n",
        "",
    ],
)
def test_public_origin_cannot_contain_credentials(url):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            craft_space_base_url="https://connect.craft.do/links/private/api/v1",
            wrapper_api_token="token",
            wrapper_public_url=url,
        )


def test_public_origin(settings):
    settings.wrapper_public_url = "https://wrapper.example"
    assert create_app(settings).openapi()["servers"] == [{"url": "https://wrapper.example"}]


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "CRAFT_SPACE_BASE_URL=https://connect.craft.do/links/file-secret/api/v1\nWRAPPER_API_TOKEN=file-token\n"
    )
    monkeypatch.setenv("WRAPPER_API_TOKEN", "environment-token")
    settings = Settings(_env_file=env)
    assert settings.wrapper_api_token is not None
    assert settings.wrapper_api_token.get_secret_value() == "environment-token"
    assert "file-secret" not in repr(settings)
    assert "environment-token" not in repr(settings)


def test_load_settings_resolves_required_values_from_sources(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CRAFT_SPACE_BASE_URL", raising=False)
    monkeypatch.delenv("CRAFT_DOCUMENTS_BASE_URL", raising=False)
    monkeypatch.delenv("WRAPPER_API_TOKEN", raising=False)
    (tmp_path / ".env").write_text(
        "CRAFT_SPACE_BASE_URL=https://connect.craft.do/links/file-secret/api/v1\n"
        "WRAPPER_API_TOKEN=file-token\n"
    )
    monkeypatch.setenv("WRAPPER_API_TOKEN", "environment-token")
    settings = load_settings()
    assert settings.craft_space_base_url is not None
    assert settings.craft_space_base_url.get_secret_value().endswith("/links/file-secret/api/v1")
    assert settings.wrapper_api_token is not None
    assert settings.wrapper_api_token.get_secret_value() == "environment-token"


def test_load_settings_still_requires_credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CRAFT_SPACE_BASE_URL", raising=False)
    monkeypatch.delenv("CRAFT_DOCUMENTS_BASE_URL", raising=False)
    monkeypatch.delenv("WRAPPER_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError) as raised:
        load_settings()
    assert str(raised.value) == "Invalid wrapper configuration: wrapper_api_token"


def test_startup_failure_is_sanitized(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CRAFT_SPACE_BASE_URL", "https://invalid.test/secret-input")
    monkeypatch.setenv("WRAPPER_API_TOKEN", "private-token")
    with pytest.raises(RuntimeError) as raised:
        load_settings()
    assert "secret-input" not in str(raised.value)
    assert "private-token" not in str(raised.value)

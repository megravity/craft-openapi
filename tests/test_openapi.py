import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from pydantic import ValidationError

from craft_wrapper.config import OPERATION_IDS, Settings, load_settings
from craft_wrapper.main import create_app


def operations(spec):
    return [
        operation
        for path in spec["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "patch", "put", "delete"}
    ]


def test_openapi_valid_and_exact_operation_set(settings):
    spec = create_app(settings).openapi()
    validate(spec)
    assert spec["openapi"] == "3.1.0"
    ops = operations(spec)
    assert len(ops) == 13
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
    "allowlist", ["", " ", "unknown", "craft_space_list_documents,", ",craft_space_list_documents"]
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
    assert settings.wrapper_api_token.get_secret_value() == "environment-token"
    assert "file-secret" not in repr(settings)
    assert "environment-token" not in repr(settings)


def test_startup_failure_is_sanitized(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CRAFT_SPACE_BASE_URL", "https://invalid.test/secret-input")
    monkeypatch.setenv("WRAPPER_API_TOKEN", "private-token")
    with pytest.raises(RuntimeError) as raised:
        load_settings()
    assert "secret-input" not in str(raised.value)
    assert "private-token" not in str(raised.value)

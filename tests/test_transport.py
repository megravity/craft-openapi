import asyncio
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from craft_wrapper.craft.errors import CraftError
from craft_wrapper.craft.transport import CraftTransport, retry_after_seconds


def run_request(
    handler, *, method="GET", max_bytes=8 * 1024 * 1024, deadline: float = 1, markdown=False
):
    async def run():
        async with httpx.AsyncClient(
            base_url="https://connect.craft.do/links/testing-link-secret/api/v1/",
            transport=httpx.MockTransport(handler),
        ) as client:
            transport = CraftTransport(
                client,
                deadline_seconds=deadline,
                max_response_bytes=max_bytes,
                secrets=("testing-link-secret", "test-wrapper-token"),
            )
            return await transport.request(
                method,
                "blocks",
                markdown=markdown,
                params={"id": "a &?/雪", "empty": None, "flag": False},
            )

    return asyncio.run(run())


def test_query_encoding_and_accept():
    def handler(request):
        assert request.url.params == httpx.QueryParams({"id": "a &?/雪", "flag": "false"})
        assert request.url.path == "/links/testing-link-secret/api/v1/blocks"
        assert request.headers["accept"] == "application/json"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"items": []})

    assert run_request(handler) == {"items": []}


def test_markdown_uses_upstream_rendering():
    content = '<page id="p">Title</page>\n[Hidden](invalid:out_of_scope)'

    def handler(request):
        assert request.headers["accept"] == "text/markdown"
        return httpx.Response(
            200, text=content, headers={"Content-Type": "text/markdown; charset=utf-8"}
        )

    assert run_request(handler, markdown=True) == content


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
        (500, 502, "craft_upstream_error"),
        (503, 502, "craft_upstream_error"),
        (418, 502, "craft_upstream_error"),
    ],
)
def test_status_mapping_no_retry(upstream, status, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            upstream,
            json={"error": {"code": "UPSTREAM", "message": "Useful detail"}},
            headers={"Retry-After": "12"},
        )

    with pytest.raises(CraftError) as raised:
        run_request(handler, method="POST")
    error = raised.value
    assert (error.status, error.code, error.upstream_status) == (status, code, upstream)
    assert error.upstream_code == "UPSTREAM"
    assert error.message == "Useful detail"
    assert error.retry_after_seconds == 12
    assert error.outcome_unknown
    assert len(calls) == 1


def test_redirect_is_not_followed_or_exposed():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            302,
            headers={"Location": "https://evil.example/"},
            json={"message": "secret redirect body"},
        )

    with pytest.raises(CraftError) as raised:
        run_request(handler)
    assert raised.value.status == 502
    assert "redirect body" not in raised.value.message
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"bad json", headers={"Content-Type": "application/json"}),
        httpx.Response(200, content=b'{"x":NaN}', headers={"Content-Type": "application/json"}),
        httpx.Response(200, content=b'{"x":1e999}', headers={"Content-Type": "application/json"}),
        httpx.Response(200, content=b"\xff", headers={"Content-Type": "application/json"}),
        httpx.Response(200, text="<html>oops</html>"),
    ],
)
def test_invalid_response_and_uncertain_write(response):
    with pytest.raises(CraftError) as raised:
        run_request(lambda request: response, method="PUT")
    assert raised.value.code == "craft_upstream_error"
    assert raised.value.upstream_status == 200
    assert raised.value.outcome_unknown


def test_wrong_markdown_content_type():
    with pytest.raises(CraftError):
        run_request(lambda request: httpx.Response(200, json={}), markdown=True)


def test_unknown_error_shape_uses_safe_fallback():
    with pytest.raises(CraftError) as raised:
        run_request(lambda request: httpx.Response(500, text="raw secret body"))
    assert raised.value.message == "Craft returned an upstream error."


def test_secret_redaction():
    message = (
        "testing-link-secret test-wrapper-token "
        "https://connect.craft.do/links/some-other-secret/api/v1 "
        "Authorization: Bearer another-secret"
        " Authorization: Basic dXNlcjpwYXNz"
    )
    with pytest.raises(CraftError) as raised:
        run_request(lambda request: httpx.Response(400, json={"code": message, "message": message}))
    rendered = json.dumps(vars(raised.value))
    for secret in (
        "testing-link-secret",
        "test-wrapper-token",
        "some-other-secret",
        "another-secret",
        "dXNlcjpwYXNz",
    ):
        assert secret not in rendered


class Chunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"123456"
        yield b"789012"


def test_streamed_response_limit():
    with pytest.raises(CraftError) as raised:
        run_request(
            lambda request: httpx.Response(200, stream=Chunks()), max_bytes=10, method="POST"
        )
    assert raised.value.code == "craft_response_too_large"
    assert raised.value.outcome_unknown


@pytest.mark.parametrize(
    "exception,status,code",
    [
        (httpx.ConnectError("secret URL"), 503, "craft_unavailable"),
        (httpx.ReadTimeout("secret URL"), 504, "craft_timeout"),
        (httpx.ConnectTimeout("secret URL"), 504, "craft_timeout"),
    ],
)
def test_network_failures(exception, status, code):
    calls = []

    def handler(request):
        calls.append(request)
        raise exception

    with pytest.raises(CraftError) as raised:
        run_request(handler, method="POST")
    assert (raised.value.status, raised.value.code) == (status, code)
    assert raised.value.outcome_unknown
    assert "secret URL" not in str(raised.value)
    assert len(calls) == 1


def test_overall_deadline():
    async def handler(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={})

    with pytest.raises(CraftError) as raised:
        run_request(handler, deadline=0.01, method="POST")
    assert raised.value.code == "craft_timeout"
    assert raised.value.outcome_unknown


def test_retry_after_formats():
    assert retry_after_seconds("12") == 12
    assert retry_after_seconds("0") == 0
    assert retry_after_seconds("99999999999999999999") is None
    for value in (None, "garbage", "-5", "NaN", "1.5", "１２"):
        assert retry_after_seconds(value) is None
    later = format_datetime(datetime.now(UTC) + timedelta(seconds=60), usegmt=True)
    seconds = retry_after_seconds(later)
    assert seconds is not None
    assert 59 <= seconds <= 60
    before = format_datetime(datetime.now(UTC) - timedelta(seconds=60), usegmt=True)
    assert retry_after_seconds(before) == 0

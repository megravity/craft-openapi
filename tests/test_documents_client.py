import asyncio

import httpx
import pytest

from craft_wrapper.craft.documents.client import DocumentsClient
from craft_wrapper.craft.errors import CraftError
from craft_wrapper.craft.transport import CraftTransport


def call(handler, operation):
    async def run():
        async with httpx.AsyncClient(
            base_url="https://example.test/api/v1/", transport=httpx.MockTransport(handler)
        ) as http:
            return await operation(DocumentsClient(CraftTransport(http)))

    return asyncio.run(run())


@pytest.mark.parametrize("mode", [None, "include", "exclude"])
@pytest.mark.parametrize("search", [True, False])
def test_document_filter_translation(mode, search):
    params = {"documentId": "opaque &/?#", "documentFilterMode": mode}
    if search:
        params.update(query="words & more", fetchBlocks=False)

    def handler(request):
        expected = {"documentIds": "opaque &/?#", "documentFilterMode": mode or "include"}
        if search:
            expected.update(include="words & more", fetchBlocks="false")
        assert dict(request.url.params) == expected
        return httpx.Response(200, json={"items": []})

    call(handler, lambda c: c.search_documents(params) if search else c.list_collections(params))


@pytest.mark.parametrize("search", [True, False])
def test_no_filter_omits_selector_and_mode(search):
    def handler(request):
        assert dict(request.url.params) == ({"include": "q"} if search else {})
        return httpx.Response(200, json={"items": []})

    call(
        handler, lambda c: c.search_documents({"query": "q"}) if search else c.list_collections({})
    )


def test_ids_and_metadata_remain_distinct_and_unknown_fields_are_ignored():
    payload = {
        "items": [
            {
                "id": "api-id",
                "title": "Example",
                "isDeleted": False,
                "clickableLink": "craftdocs://open?documentId=app-id",
                "unknown": "ignored",
            },
            {"id": "deleted", "title": "Deleted", "isDeleted": True},
        ]
    }
    result = call(lambda request: httpx.Response(200, json=payload), lambda c: c.list_documents({}))
    assert result.items[0].id == "api-id"
    assert result.items[0].clickableLink == "craftdocs://open?documentId=app-id"
    assert result.items[1].isDeleted
    assert "unknown" not in result.model_dump_json()


@pytest.mark.parametrize(
    "payload",
    [
        {"items": [{"id": "d", "title": "D"}]},
        {"items": [{"rootBlockId": "d", "title": "D", "isDeleted": False}]},
        {"items": [{"id": "d", "title": "D", "isDeleted": "false"}]},
    ],
)
def test_unexpected_document_contract_is_sanitized(payload):
    with pytest.raises(CraftError) as raised:
        call(lambda request: httpx.Response(200, json=payload), lambda c: c.list_documents({}))
    assert raised.value.code == "craft_upstream_error"
    assert not raised.value.outcome_unknown


def test_encoded_collection_id():
    def handler(request):
        assert request.url.raw_path == b"/api/v1/collections/a%2Fb%20%26%3F%23%25/items?maxDepth=0"
        return httpx.Response(200, json={"items": []})

    call(handler, lambda c: c.list_collection_items("a/b &?#%"))

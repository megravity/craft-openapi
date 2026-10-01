import asyncio
import json

import httpx
import pytest

from craft_wrapper.craft.errors import CraftError
from craft_wrapper.craft.space.client import SpaceClient
from craft_wrapper.craft.transport import CraftTransport


def call(handler, operation):
    async def run():
        async with httpx.AsyncClient(
            base_url="https://example.test/api/v1/", transport=httpx.MockTransport(handler)
        ) as http:
            return await operation(SpaceClient(CraftTransport(http)))

    return asyncio.run(run())


@pytest.mark.parametrize(
    "response",
    [
        {"items": []},
        {
            "items": [
                {"id": "a", "title": "A"},
                {"id": "b", "title": "B"},
            ]
        },
        {"wrong": []},
        {"items": [{"rootBlockId": "a", "title": "A"}]},
    ],
)
def test_singleton_and_response_contract(response):
    with pytest.raises(CraftError) as raised:
        call(lambda request: httpx.Response(200, json=response), lambda c: c.create_document("A"))
    assert raised.value.code == "craft_upstream_error"
    assert raised.value.outcome_unknown


@pytest.mark.parametrize(
    "folder,location,destination",
    [
        (None, None, None),
        ("f", None, {"folderId": "f"}),
        (None, "templates", {"destination": "templates"}),
        (None, "unsorted", {"destination": "unsorted"}),
    ],
)
def test_document_destination(folder, location, destination):
    def handler(request):
        expected = {"documents": [{"title": "Title"}]}
        if destination is not None:
            expected["destination"] = destination
        assert json.loads(request.content) == expected
        return httpx.Response(200, json={"items": [{"id": "d", "title": "Title"}]})

    assert (
        call(handler, lambda c: c.create_document("Title", folder_id=folder, location=location)).id
        == "d"
    )


def test_encoded_collection_path():
    def handler(request):
        assert request.url.raw_path == b"/api/v1/collections/a%2Fb%20%26%3F%23%25/items?maxDepth=0"
        return httpx.Response(200, json={"items": []})

    call(handler, lambda c: c.list_collection_items("a/b &?#%"))


@pytest.mark.parametrize("identifier", [".", ".."])
def test_dot_segments_cannot_escape_collection_path(identifier):
    def handler(request):
        pytest.fail("Must not send an unsafe path")

    with pytest.raises(CraftError):
        call(handler, lambda c: c.get_collection_schema(identifier))


def test_search_translation_and_dates_unchanged():
    def handler(request):
        assert dict(request.url.params) == {
            "include": "topic & words",
            "folderIds": "f",
            "createdDateGte": "yesterday",
            "fetchBlocks": "false",
        }
        return httpx.Response(200, json={"items": []})

    call(
        handler,
        lambda c: c.search_documents(
            {
                "query": "topic & words",
                "folderId": "f",
                "createdDateGte": "yesterday",
                "fetchBlocks": False,
            }
        ),
    )


def test_additional_upstream_fields_do_not_leak():
    result = call(
        lambda request: httpx.Response(
            200,
            json={
                "items": [{"id": "d", "title": "D", "unknown": {"secret": "not public"}}],
                "unknown": True,
            },
        ),
        lambda c: c.list_documents({}),
    )
    assert result.model_dump(exclude_none=True) == {"items": [{"id": "d", "title": "D"}]}

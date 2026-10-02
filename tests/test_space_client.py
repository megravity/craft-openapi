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


@pytest.mark.parametrize("title_metadata", [None, {"key": "title", "name": "Title"}])
@pytest.mark.parametrize("property_type", ["select", "singleSelect"])
def test_schema_accepts_object_options_and_optional_title_metadata(title_metadata, property_type):
    payload = {
        "name": "Example collection",
        "properties": [
            {
                "key": "decision",
                "name": "Decision",
                "type": property_type,
                "options": [
                    {"name": "Yes", "color": "green", "unmodeled": "ignored"},
                    {"name": "No"},
                    "Maybe",
                ],
            }
        ],
    }
    if title_metadata is not None:
        payload["contentPropDetails"] = title_metadata
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/v1/collections/example-collection/schema"
        assert dict(request.url.params) == {"format": "schema"}
        return httpx.Response(200, json=payload)

    result = call(handler, lambda c: c.get_collection_schema("example-collection"))
    serialized = result.model_dump(exclude_none=True)
    assert serialized["properties"][0]["type"] == property_type
    assert serialized["properties"][0]["options"] == [
        {"name": "Yes", "color": "green"},
        {"name": "No"},
        "Maybe",
    ]
    assert serialized.get("contentPropDetails") == title_metadata
    assert len(calls) == 1


@pytest.mark.parametrize("options", [[123], [{}], [{"name": 123}], [{"name": "Yes", "color": []}]])
def test_malformed_schema_options_are_not_fabricated(options):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "name": "Example collection",
                "properties": [
                    {"key": "status", "name": "Status", "type": "select", "options": options}
                ],
            },
        )

    with pytest.raises(CraftError) as raised:
        call(handler, lambda c: c.get_collection_schema("example-collection"))
    assert raised.value.code == "craft_upstream_error"
    assert len(calls) == 1


def test_document_api_id_is_independent_from_navigation_link():
    payload = {
        "items": [
            {
                "id": "api-root-slug",
                "title": "Example document",
                "clickableLink": "craftdocs://open?spaceId=example-space&documentId=app-only-id",
            }
        ]
    }
    documents = call(
        lambda request: httpx.Response(200, json=payload),
        lambda c: c.list_documents({"fetchMetadata": True}),
    )
    assert documents.items[0].id == "api-root-slug"
    assert documents.items[0].clickableLink == payload["items"][0]["clickableLink"]


@pytest.mark.parametrize(
    "fields",
    [
        {"items": [{"properties": {}}]},
        {"items": "wrong"},
        {"contentPreviewMd": {}},
        {"itemsPreviewMd": 123},
        {"items": [{"id": "row", "properties": [], "content": []}]},
    ],
)
def test_malformed_collection_rows_and_previews_fail_without_retries(fields):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "collection", "type": "collection", **fields})

    with pytest.raises(CraftError) as raised:
        call(handler, lambda c: c.get_block("collection", -1))
    assert raised.value.code == "craft_upstream_error"
    assert not raised.value.outcome_unknown
    assert len(calls) == 1


def test_collection_rows_keep_known_fields_and_drop_unknown_fields_recursively():
    payload = {
        "id": "collection",
        "type": "collection",
        "unmodeled": "ignored",
        "items": [
            {
                "id": "row",
                "properties": {},
                "unmodeled": "ignored",
                "contentPreviewMd": "Row preview",
                "content": [{"id": "text", "type": "text", "markdown": "Example", "extra": True}],
            }
        ],
    }
    result = call(
        lambda request: httpx.Response(200, json=payload),
        lambda c: c.get_block("collection", -1),
    )
    assert result.model_dump(exclude_none=True) == {
        "id": "collection",
        "type": "collection",
        "items": [
            {
                "id": "row",
                "properties": {},
                "contentPreviewMd": "Row preview",
                "content": [{"id": "text", "type": "text", "markdown": "Example"}],
            }
        ],
    }


def test_search_preserves_more_than_twenty_hits_and_repeated_document_ids():
    payload = {
        "items": [
            {"documentId": "document", "markdown": f"Match {i}", "blockIds": [f"block-{i}"]}
            for i in range(25)
        ]
    }
    result = call(
        lambda request: httpx.Response(200, json=payload),
        lambda c: c.search_documents({"query": "match"}),
    )
    assert result.model_dump(exclude_none=True) == payload

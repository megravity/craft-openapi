from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from craft_wrapper.craft.errors import CraftError
from craft_wrapper.craft.models import Block, CollectionItem, CollectionSchema, Items
from craft_wrapper.craft.transport import CraftTransport


def segment(value: str) -> str:
    # Dot segments have URL traversal semantics, even when quoted.
    if value in {".", ".."}:
        raise CraftError("craft_rejected_request", "Invalid resource identifier.", 400)
    return quote(value, safe="")


async def request_model[M: BaseModel](
    transport: CraftTransport, model: type[M], method: str, path: str, **kwargs: Any
) -> M:
    data = await transport.request(method, path, **kwargs)
    try:
        return model.model_validate(data)
    except ValidationError:
        raise CraftError(
            "craft_upstream_error",
            "Craft returned an unexpected response shape.",
            outcome_unknown=method != "GET",
        ) from None


async def get_block(transport: CraftTransport, block_id: str, max_depth: int = 1) -> Block:
    return await request_model(
        transport, Block, "GET", "blocks", params={"id": block_id, "maxDepth": max_depth}
    )


async def read_markdown(transport: CraftTransport, block_id: str, max_depth: int = 1) -> str:
    return await transport.request(
        "GET", "blocks", markdown=True, params={"id": block_id, "maxDepth": max_depth}
    )


async def insert_markdown(
    transport: CraftTransport, page_id: str, markdown: str, position: str = "end"
) -> Items[Block]:
    return await request_model(
        transport,
        Items[Block],
        "POST",
        "blocks",
        body={"markdown": markdown, "position": {"pageId": page_id, "position": position}},
    )


async def update_block_markdown(transport: CraftTransport, block_id: str, markdown: str) -> Block:
    result = await request_model(
        transport,
        Items[Block],
        "PUT",
        "blocks",
        body={"blocks": [{"id": block_id, "markdown": markdown}]},
    )
    return single(result)


async def get_collection_schema(transport: CraftTransport, collection_id: str) -> CollectionSchema:
    return await request_model(
        transport,
        CollectionSchema,
        "GET",
        f"collections/{segment(collection_id)}/schema",
        params={"format": "schema"},
    )


async def list_collection_items(
    transport: CraftTransport, collection_id: str, max_depth: int = 0
) -> Items[CollectionItem]:
    return await request_model(
        transport,
        Items[CollectionItem],
        "GET",
        f"collections/{segment(collection_id)}/items",
        params={"maxDepth": max_depth},
    )


async def add_collection_item(
    transport: CraftTransport, collection_id: str, title: str, properties: dict[str, str]
) -> CollectionItem:
    result = await request_model(
        transport,
        Items[CollectionItem],
        "POST",
        f"collections/{segment(collection_id)}/items",
        body={"items": [{"title": title, "properties": properties}]},
    )
    return single(result)


async def update_collection_item_properties(
    transport: CraftTransport, collection_id: str, item_id: str, properties: dict[str, str]
) -> CollectionItem:
    result = await request_model(
        transport,
        Items[CollectionItem],
        "PUT",
        f"collections/{segment(collection_id)}/items",
        body={"itemsToUpdate": [{"id": item_id, "properties": properties}]},
    )
    return single(result)


def single[M: BaseModel](result: Items[M]) -> M:
    if len(result.items) != 1:
        raise CraftError(
            "craft_upstream_error",
            "Craft did not return exactly one result.",
            outcome_unknown=True,
        )
    return result.items[0]

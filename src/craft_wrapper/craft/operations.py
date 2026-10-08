import asyncio
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from craft_wrapper.craft.errors import CraftError
from craft_wrapper.craft.models import (
    Block,
    CollectionItem,
    CollectionSchema,
    DeletedResource,
    Items,
)
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
    return parse_model(model, data, write=method != "GET")


def parse_model[M: BaseModel](model: type[M], data: Any, *, write: bool = False) -> M:
    try:
        return model.model_validate(data)
    except ValidationError:
        raise CraftError(
            "craft_upstream_error",
            "Craft returned an unexpected response shape.",
            outcome_unknown=write,
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
    transport: CraftTransport,
    collection_id: str,
    max_depth: int = 0,
    *,
    schema: CollectionSchema | None = None,
) -> Items[CollectionItem]:
    return await collection_items_request(
        transport, collection_id, "GET", max_depth=max_depth, schema=schema
    )


async def add_collection_item(
    transport: CraftTransport,
    collection_id: str,
    title: str,
    properties: dict[str, str],
    *,
    schema: CollectionSchema | None = None,
) -> CollectionItem:
    result = await collection_items_request(
        transport,
        collection_id,
        "POST",
        item={"properties": properties},
        title=title,
        schema=schema,
    )
    resource = single(result)
    if not resource.id:
        raise CraftError(
            "craft_upstream_error", "Craft returned an invalid item ID.", outcome_unknown=True
        )
    return resource


async def update_collection_item_properties(
    transport: CraftTransport,
    collection_id: str,
    item_id: str,
    properties: dict[str, str],
    *,
    schema: CollectionSchema | None = None,
) -> CollectionItem:
    return updated_item(
        await collection_items_request(
            transport,
            collection_id,
            "PUT",
            item={"id": item_id, "properties": properties},
            schema=schema,
        ),
        item_id,
    )


async def update_collection_item_title(
    transport: CraftTransport,
    collection_id: str,
    item_id: str,
    title: str,
    *,
    schema: CollectionSchema | None = None,
) -> CollectionItem:
    resource = updated_item(
        await collection_items_request(
            transport, collection_id, "PUT", item={"id": item_id}, title=title, schema=schema
        ),
        item_id,
    )
    if resource.title is not None and resource.title != title:
        raise CraftError(
            "craft_upstream_error", "Craft returned an unexpected item title.", outcome_unknown=True
        )
    return resource


def headline_key(schema: CollectionSchema) -> str:
    key = schema.contentPropDetails.key if schema.contentPropDetails is not None else "title"
    if not key.strip() or key in CollectionItem.model_fields.keys() - {"title"}:
        raise CraftError("craft_upstream_error", "Craft returned an unsupported headline key.")
    return key


def normalized_items(data: Any, key: str, *, write: bool) -> Items[CollectionItem]:
    if key != "title" and isinstance(data, dict) and isinstance(data.get("items"), list):
        rows = []
        for item in data["items"]:
            if isinstance(item, dict) and key in item:
                if "title" in item and item["title"] != item[key]:
                    raise CraftError(
                        "craft_upstream_error",
                        "Craft returned ambiguous item headlines.",
                        outcome_unknown=write,
                    )
                item = {**item, "title": item[key]}
            rows.append(item)
        data = {**data, "items": rows}
    return parse_model(Items[CollectionItem], data, write=write)


async def collection_items_request(
    transport: CraftTransport,
    collection_id: str,
    method: Literal["GET", "POST", "PUT"],
    *,
    item: dict[str, Any] | None = None,
    title: str | None = None,
    max_depth: int = 0,
    schema: CollectionSchema | None = None,
) -> Items[CollectionItem]:
    submitted = False
    try:
        async with asyncio.timeout(transport.deadline_seconds):
            schema = (
                schema
                if schema is not None
                else await get_collection_schema(transport, collection_id)
            )
            key = headline_key(schema)
            body = None
            if method != "GET":
                row = dict(item or {})
                if title is not None:
                    row[key] = title
                body = {"items" if method == "POST" else "itemsToUpdate": [row]}
            submitted = method != "GET"
            data = await transport.request(
                method,
                f"collections/{segment(collection_id)}/items",
                params={"maxDepth": max_depth} if method == "GET" else None,
                body=body,
            )
            return normalized_items(data, key, write=submitted)
    except TimeoutError:
        raise CraftError(
            "craft_timeout", "Craft request timed out.", 504, outcome_unknown=submitted
        ) from None


def updated_item(result: Items[CollectionItem], expected_id: str) -> CollectionItem:
    resource = single(result)
    if resource.id != expected_id:
        raise CraftError(
            "craft_upstream_error", "Craft returned an unexpected item ID.", outcome_unknown=True
        )
    return resource


def single[M: BaseModel](result: Items[M]) -> M:
    if len(result.items) != 1:
        raise CraftError(
            "craft_upstream_error",
            "Craft did not return exactly one result.",
            outcome_unknown=True,
        )
    return result.items[0]


def deleted[M: DeletedResource](result: Items[M], expected_id: str) -> M:
    resource = single(result)
    if resource.id != expected_id:
        raise CraftError(
            "craft_upstream_error",
            "Craft returned an unexpected deleted resource.",
            outcome_unknown=True,
        )
    return resource


async def delete_block(transport: CraftTransport, block_id: str) -> DeletedResource:
    return deleted(
        await request_model(
            transport,
            Items[DeletedResource],
            "DELETE",
            "blocks",
            body={"blockIds": [block_id]},
        ),
        block_id,
    )


async def delete_collection_item(
    transport: CraftTransport,
    collection_id: str,
    item_id: str,
) -> DeletedResource:
    return deleted(
        await request_model(
            transport,
            Items[DeletedResource],
            "DELETE",
            f"collections/{segment(collection_id)}/items",
            body={"idsToDelete": [item_id]},
        ),
        item_id,
    )

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from craft_wrapper.craft.errors import CraftError
from craft_wrapper.craft.models import Block, CollectionItem, Items
from craft_wrapper.craft.space.models import (
    CollectionSchema,
    CollectionSummary,
    DocumentSearchHit,
    DocumentSummary,
    Folder,
)
from craft_wrapper.craft.transport import CraftTransport


def segment(value: str) -> str:
    # IDs are opaque. Dot segments have URL traversal semantics, even when quoted.
    if value in {".", ".."}:
        raise CraftError("craft_rejected_request", "Invalid resource identifier.", 400)
    return quote(value, safe="")


class SpaceClient:
    def __init__(self, transport: CraftTransport):
        self.transport = transport

    async def _request[M: BaseModel](
        self, model: type[M], method: str, path: str, **kwargs: Any
    ) -> M:
        data = await self.transport.request(method, path, **kwargs)
        try:
            return model.model_validate(data)
        except ValidationError:
            raise CraftError(
                "craft_upstream_error",
                "Craft returned an unexpected response shape.",
                outcome_unknown=method != "GET",
            ) from None

    async def list_folders(self) -> Items[Folder]:
        return await self._request(Items[Folder], "GET", "folders")

    async def list_documents(
        self, params: Mapping[str, str | bool | int | None]
    ) -> Items[DocumentSummary]:
        return await self._request(Items[DocumentSummary], "GET", "documents", params=params)

    async def search_documents(
        self, params: Mapping[str, str | bool | int | None]
    ) -> Items[DocumentSearchHit]:
        values = dict(params)
        values["include"] = values.pop("query")
        if "folderId" in values:
            values["folderIds"] = values.pop("folderId")
        if "documentId" in values:
            values["documentIds"] = values.pop("documentId")
        return await self._request(
            Items[DocumentSearchHit], "GET", "documents/search", params=values
        )

    async def create_document(
        self, title: str, *, folder_id: str | None = None, location: str | None = None
    ) -> DocumentSummary:
        body: dict[str, Any] = {"documents": [{"title": title}]}
        if folder_id is not None:
            body["destination"] = {"folderId": folder_id}
        elif location is not None:
            body["destination"] = {"destination": location}
        result = await self._request(Items[DocumentSummary], "POST", "documents", body=body)
        return self._single(result)

    async def get_block(self, block_id: str, max_depth: int = 1) -> Block:
        return await self._request(
            Block, "GET", "blocks", params={"id": block_id, "maxDepth": max_depth}
        )

    async def read_markdown(self, block_id: str, max_depth: int = 1) -> str:
        return await self.transport.request(
            "GET", "blocks", markdown=True, params={"id": block_id, "maxDepth": max_depth}
        )

    async def insert_markdown(
        self, page_id: str, markdown: str, position: str = "end"
    ) -> Items[Block]:
        return await self._request(
            Items[Block],
            "POST",
            "blocks",
            body={"markdown": markdown, "position": {"pageId": page_id, "position": position}},
        )

    async def update_block_markdown(self, block_id: str, markdown: str) -> Block:
        result = await self._request(
            Items[Block], "PUT", "blocks", body={"blocks": [{"id": block_id, "markdown": markdown}]}
        )
        return self._single(result)

    async def list_collections(self, document_id: str | None = None) -> Items[CollectionSummary]:
        return await self._request(
            Items[CollectionSummary], "GET", "collections", params={"documentIds": document_id}
        )

    async def get_collection_schema(self, collection_id: str) -> CollectionSchema:
        return await self._request(
            CollectionSchema,
            "GET",
            f"collections/{segment(collection_id)}/schema",
            params={"format": "schema"},
        )

    async def list_collection_items(
        self, collection_id: str, max_depth: int = 0
    ) -> Items[CollectionItem]:
        return await self._request(
            Items[CollectionItem],
            "GET",
            f"collections/{segment(collection_id)}/items",
            params={"maxDepth": max_depth},
        )

    async def add_collection_item(
        self, collection_id: str, title: str, properties: dict[str, str]
    ) -> CollectionItem:
        result = await self._request(
            Items[CollectionItem],
            "POST",
            f"collections/{segment(collection_id)}/items",
            body={"items": [{"title": title, "properties": properties}]},
        )
        return self._single(result)

    async def update_collection_item_properties(
        self, collection_id: str, item_id: str, properties: dict[str, str]
    ) -> CollectionItem:
        result = await self._request(
            Items[CollectionItem],
            "PUT",
            f"collections/{segment(collection_id)}/items",
            body={"itemsToUpdate": [{"id": item_id, "properties": properties}]},
        )
        return self._single(result)

    @staticmethod
    def _single[M: BaseModel](result: Items[M]) -> M:
        if len(result.items) != 1:
            raise CraftError(
                "craft_upstream_error",
                "Craft did not return exactly one result.",
                outcome_unknown=True,
            )
        return result.items[0]

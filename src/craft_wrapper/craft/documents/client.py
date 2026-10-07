from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from craft_wrapper.craft import operations
from craft_wrapper.craft.documents.models import DocumentSummary
from craft_wrapper.craft.models import (
    Block,
    CollectionItem,
    CollectionSchema,
    CollectionSummary,
    DeletedResource,
    DocumentSearchHit,
    Items,
)
from craft_wrapper.craft.transport import CraftTransport


class DocumentsClient:
    def __init__(self, transport: CraftTransport):
        self.transport = transport

    async def _request[M: BaseModel](
        self, model: type[M], method: str, path: str, **kwargs: Any
    ) -> M:
        return await operations.request_model(self.transport, model, method, path, **kwargs)

    async def list_documents(
        self, params: Mapping[str, str | bool | int | None]
    ) -> Items[DocumentSummary]:
        return await self._request(Items[DocumentSummary], "GET", "documents", params=params)

    async def search_documents(
        self, params: Mapping[str, str | bool | int | None]
    ) -> Items[DocumentSearchHit]:
        values = dict(params)
        values["include"] = values.pop("query")
        values = document_scope(values)
        return await self._request(
            Items[DocumentSearchHit], "GET", "documents/search", params=values
        )

    async def get_block(self, block_id: str, max_depth: int = 1) -> Block:
        return await operations.get_block(self.transport, block_id, max_depth)

    async def read_markdown(self, block_id: str, max_depth: int = 1) -> str:
        return await operations.read_markdown(self.transport, block_id, max_depth)

    async def insert_markdown(
        self, page_id: str, markdown: str, position: str = "end"
    ) -> Items[Block]:
        return await operations.insert_markdown(self.transport, page_id, markdown, position)

    async def update_block_markdown(self, block_id: str, markdown: str) -> Block:
        return await operations.update_block_markdown(self.transport, block_id, markdown)

    async def list_collections(
        self, params: Mapping[str, str | bool | int | None]
    ) -> Items[CollectionSummary]:
        return await self._request(
            Items[CollectionSummary], "GET", "collections", params=document_scope(params)
        )

    async def get_collection_schema(self, collection_id: str) -> CollectionSchema:
        return await operations.get_collection_schema(self.transport, collection_id)

    async def list_collection_items(
        self, collection_id: str, max_depth: int = 0
    ) -> Items[CollectionItem]:
        return await operations.list_collection_items(self.transport, collection_id, max_depth)

    async def add_collection_item(
        self, collection_id: str, title: str, properties: dict[str, str]
    ) -> CollectionItem:
        return await operations.add_collection_item(
            self.transport, collection_id, title, properties
        )

    async def update_collection_item_properties(
        self, collection_id: str, item_id: str, properties: dict[str, str]
    ) -> CollectionItem:
        return await operations.update_collection_item_properties(
            self.transport, collection_id, item_id, properties
        )

    async def delete_block(self, block_id: str) -> DeletedResource:
        return await operations.delete_block(self.transport, block_id)

    async def delete_collection_item(self, collection_id: str, item_id: str) -> DeletedResource:
        return await operations.delete_collection_item(self.transport, collection_id, item_id)


def document_scope(
    params: Mapping[str, str | bool | int | None],
) -> dict[str, str | bool | int | None]:
    values = dict(params)
    document_id = values.pop("documentId", None)
    if document_id is not None:
        values["documentIds"] = document_id
        if values.get("documentFilterMode") is None:
            values["documentFilterMode"] = "include"
    return values

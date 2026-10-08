from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from craft_wrapper.craft import operations
from craft_wrapper.craft.errors import CraftError
from craft_wrapper.craft.models import Block, CollectionItem, DeletedResource, Items
from craft_wrapper.craft.space.models import (
    CollectionSchema,
    CollectionSummary,
    DocumentSearchHit,
    DocumentSummary,
    Folder,
    SpaceTask,
)
from craft_wrapper.craft.transport import CraftTransport


class SpaceClient:
    def __init__(self, transport: CraftTransport):
        self.transport = transport

    async def _request[M: BaseModel](
        self, model: type[M], method: str, path: str, **kwargs: Any
    ) -> M:
        return await operations.request_model(self.transport, model, method, path, **kwargs)

    async def list_folders(self) -> Items[Folder]:
        return await self._request(Items[Folder], "GET", "folders")

    async def list_tasks(
        self,
        params: Mapping[str, str | bool | int | None],
    ) -> Items[SpaceTask]:
        return await self._request(Items[SpaceTask], "GET", "tasks", params=params)

    async def add_task(self, values: Mapping[str, str]) -> SpaceTask:
        task: dict[str, Any] = {
            "markdown": values["markdown"],
            "location": {"type": "document", "documentId": values["documentId"]},
        }
        info = {key: values[key] for key in ("scheduleDate", "deadlineDate") if key in values}
        if info:
            task["taskInfo"] = info
        result = operations.single(
            await self._request(Items[SpaceTask], "POST", "tasks", body={"tasks": [task]})
        )
        if not result.id:
            raise CraftError(
                "craft_upstream_error", "Craft returned an invalid task ID.", outcome_unknown=True
            )
        return result

    async def update_task(self, task_id: str, values: Mapping[str, str]) -> SpaceTask:
        task: dict[str, Any] = {"id": task_id}
        if "markdown" in values:
            task["markdown"] = values["markdown"]
        info = {
            key: values[key] for key in ("state", "scheduleDate", "deadlineDate") if key in values
        }
        if info:
            task["taskInfo"] = info
        result = operations.single(
            await self._request(Items[SpaceTask], "PUT", "tasks", body={"tasksToUpdate": [task]})
        )
        if result.id != task_id:
            raise CraftError(
                "craft_upstream_error",
                "Craft returned an unexpected task ID.",
                outcome_unknown=True,
            )
        return result

    async def delete_task(self, task_id: str) -> DeletedResource:
        return operations.deleted(
            await self._request(
                Items[DeletedResource], "DELETE", "tasks", body={"idsToDelete": [task_id]}
            ),
            task_id,
        )

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
        return await operations.get_block(self.transport, block_id, max_depth)

    async def read_markdown(self, block_id: str, max_depth: int = 1) -> str:
        return await operations.read_markdown(self.transport, block_id, max_depth)

    async def insert_markdown(
        self, page_id: str, markdown: str, position: str = "end"
    ) -> Items[Block]:
        return await operations.insert_markdown(self.transport, page_id, markdown, position)

    async def update_block_markdown(self, block_id: str, markdown: str) -> Block:
        return await operations.update_block_markdown(self.transport, block_id, markdown)

    async def list_collections(self, document_id: str | None = None) -> Items[CollectionSummary]:
        return await self._request(
            Items[CollectionSummary], "GET", "collections", params={"documentIds": document_id}
        )

    async def get_collection_schema(self, collection_id: str) -> CollectionSchema:
        return await operations.get_collection_schema(self.transport, collection_id)

    async def list_collection_items(
        self,
        collection_id: str,
        max_depth: int = 0,
        *,
        schema: CollectionSchema | None = None,
    ) -> Items[CollectionItem]:
        return await operations.list_collection_items(
            self.transport, collection_id, max_depth, schema=schema
        )

    async def add_collection_item(
        self,
        collection_id: str,
        title: str,
        properties: dict[str, str],
        *,
        schema: CollectionSchema | None = None,
    ) -> CollectionItem:
        return await operations.add_collection_item(
            self.transport, collection_id, title, properties, schema=schema
        )

    async def update_collection_item_properties(
        self,
        collection_id: str,
        item_id: str,
        properties: dict[str, str],
        *,
        schema: CollectionSchema | None = None,
    ) -> CollectionItem:
        return await operations.update_collection_item_properties(
            self.transport, collection_id, item_id, properties, schema=schema
        )

    @staticmethod
    def _single[M: BaseModel](result: Items[M]) -> M:
        return operations.single(result)

    async def update_collection_item_title(
        self,
        collection_id: str,
        item_id: str,
        title: str,
        *,
        schema: CollectionSchema | None = None,
    ) -> CollectionItem:
        return await operations.update_collection_item_title(
            self.transport, collection_id, item_id, title, schema=schema
        )

    async def delete_block(self, block_id: str) -> DeletedResource:
        return await operations.delete_block(self.transport, block_id)

    async def delete_collection_item(self, collection_id: str, item_id: str) -> DeletedResource:
        return await operations.delete_collection_item(self.transport, collection_id, item_id)

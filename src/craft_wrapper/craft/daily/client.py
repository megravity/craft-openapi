from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from craft_wrapper.craft import operations
from craft_wrapper.craft.daily.models import (
    DailyCollectionSummary,
    DailyNoteSearchHit,
    DeletedTask,
    Task,
)
from craft_wrapper.craft.models import Block, CollectionItem, CollectionSchema, Items
from craft_wrapper.craft.transport import CraftTransport


class DailyClient:
    def __init__(self, transport: CraftTransport):
        self.transport = transport

    async def _request[M: BaseModel](
        self, model: type[M], method: str, path: str, **kwargs: Any
    ) -> M:
        return await operations.request_model(self.transport, model, method, path, **kwargs)

    async def get_note(self, date: str = "today", max_depth: int = 1) -> Block:
        return await self._request(
            Block, "GET", "blocks", params={"date": date, "maxDepth": max_depth}
        )

    async def read_note_markdown(self, date: str = "today", max_depth: int = 1) -> str:
        return await self.transport.request(
            "GET", "blocks", markdown=True, params={"date": date, "maxDepth": max_depth}
        )

    async def insert_note_markdown(
        self, date: str, markdown: str, position: str = "end"
    ) -> Items[Block]:
        return await self._request(
            Items[Block],
            "POST",
            "blocks",
            body={"markdown": markdown, "position": {"date": date, "position": position}},
        )

    async def search_notes(
        self, params: Mapping[str, str | bool | int | None]
    ) -> Items[DailyNoteSearchHit]:
        values = dict(params)
        values["include"] = values.pop("query")
        return await self._request(
            Items[DailyNoteSearchHit], "GET", "daily-notes/search", params=values
        )

    async def list_collections(
        self, params: Mapping[str, str | bool | int | None]
    ) -> Items[DailyCollectionSummary]:
        return await self._request(
            Items[DailyCollectionSummary], "GET", "collections", params=params
        )

    async def list_tasks(self, scope: str) -> Items[Task]:
        return await self._request(Items[Task], "GET", "tasks", params={"scope": scope})

    async def add_task(self, values: Mapping[str, str]) -> Task:
        location = (
            {"type": "inbox"}
            if values.get("target", "inbox") == "inbox"
            else {"type": "dailyNote", "date": values.get("date", "today")}
        )
        task: dict[str, Any] = {"markdown": values["markdown"], "location": location}
        info = {key: values[key] for key in ("scheduleDate", "deadlineDate") if key in values}
        if info:
            task["taskInfo"] = info
        return operations.single(
            await self._request(Items[Task], "POST", "tasks", body={"tasks": [task]})
        )

    async def update_task(self, task_id: str, values: Mapping[str, str]) -> Task:
        task: dict[str, Any] = {"id": task_id}
        if "markdown" in values:
            task["markdown"] = values["markdown"]
        info = {
            key: values[key] for key in ("state", "scheduleDate", "deadlineDate") if key in values
        }
        if info:
            task["taskInfo"] = info
        return operations.single(
            await self._request(Items[Task], "PUT", "tasks", body={"tasksToUpdate": [task]})
        )

    async def delete_task(self, task_id: str) -> DeletedTask:
        return operations.single(
            await self._request(
                Items[DeletedTask], "DELETE", "tasks", body={"idsToDelete": [task_id]}
            )
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

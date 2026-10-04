from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from craft_wrapper.api.auth import require_token
from craft_wrapper.api.daily_schemas import (
    AddTask,
    DailyDateRange,
    DailyMarkdownContent,
    DailyNoteRead,
    DailyNoteSelector,
    DailySearchFilters,
    TaskFilters,
    UpdateTask,
)
from craft_wrapper.api.responses import ERROR_RESPONSES
from craft_wrapper.api.schemas import (
    AddCollectionItem,
    BlockDepth,
    Identifier,
    InsertMarkdown,
    ItemDepth,
    MarkdownContent,
    UpdateCollectionProperties,
    UpdateMarkdown,
)
from craft_wrapper.craft.daily.client import DailyClient
from craft_wrapper.craft.daily.models import (
    DailyCollectionSummary,
    DailyNoteSearchHit,
    DeletedTask,
    Task,
)
from craft_wrapper.craft.models import Block, CollectionItem, CollectionSchema, Items


def get_client(request: Request) -> DailyClient:
    return request.app.state.daily_client


Client = Annotated[DailyClient, Depends(get_client)]


def make_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/daily",
        tags=["Craft Daily Notes"],
        dependencies=[Depends(require_token)],
        responses=ERROR_RESPONSES,
    )

    @router.get(
        "/notes",
        operation_id="craft_daily_get_note",
        response_model=Block,
        response_model_exclude_none=True,
        summary="Read a daily note as structured blocks",
        description="Read a daily-note root by date, defaulting to today. Craft "
        "resolves relative dates. "
        "Use returned root/page and text-block IDs for ID-based reads and editing. "
        "Default depth 1 omits deeper descendants; -1 requests all descendants. "
        "Nested collections, previews, and invalid:out_of_scope links are preserved. "
        "A missing note returns Craft's error; reads do not implicitly insert content.",
    )
    async def get_note(client: Client, filters: Annotated[DailyNoteRead, Query()]):
        return await client.get_note(filters.date, filters.maxDepth)

    @router.get(
        "/notes/markdown",
        operation_id="craft_daily_read_note_markdown",
        response_model=DailyMarkdownContent,
        summary="Read a daily note as rendered Markdown",
        description="Read rendered daily-note content for summarization. date "
        "defaults to today and "
        "relative dates pass unchanged to Craft. The response date is the requested selector. "
        "Default depth 1 omits deeper descendants; -1 requests all descendants. "
        "Use get_note for editable block IDs and hierarchy. Craft "
        "tags and scope markers are preserved.",
    )
    async def read_note_markdown(client: Client, filters: Annotated[DailyNoteRead, Query()]):
        return DailyMarkdownContent(
            date=filters.date,
            markdown=await client.read_note_markdown(filters.date, filters.maxDepth),
        )

    @router.post(
        "/notes/content",
        operation_id="craft_daily_insert_note_markdown",
        status_code=201,
        response_model=Items[Block],
        response_model_exclude_none=True,
        summary="Insert Markdown into a daily note by date",
        description="Add Markdown at the start or end of a daily note; date defaults to today. "
        "Relative dates are resolved by Craft. Date insertion targets the most recently updated "
        "note if multiple notes share that date; use insert_markdown "
        "with a pageId for an exact page. "
        "One insertion can create multiple blocks. Writes are never retried; outcomeUnknown means "
        "the content may have been inserted. This does not replace the note.",
    )
    async def insert_note_markdown(
        body: InsertMarkdown, client: Client, selector: Annotated[DailyNoteSelector, Query()]
    ):
        return await client.insert_note_markdown(selector.date, body.markdown, body.position)

    @router.get(
        "/notes/search",
        operation_id="craft_daily_search_notes",
        response_model=Items[DailyNoteSearchHit],
        response_model_exclude_none=True,
        summary="Search content across daily notes",
        description="Find one plain include string across daily notes within an "
        "optional date range. "
        "Returns relevance-ranked snippets and block IDs, with "
        "dailyNoteDate instead of documentId. "
        "Craft documents top 20 results, not an exhaustive "
        "inventory. Use a hit's date with get_note "
        "or its block IDs with get_block. Regex and pagination are unsupported.",
    )
    async def search_notes(client: Client, filters: Annotated[DailySearchFilters, Query()]):
        return await client.search_notes(filters.model_dump(exclude_none=True))

    @router.get(
        "/collections",
        operation_id="craft_daily_list_collections",
        response_model=Items[DailyCollectionSummary],
        response_model_exclude_none=True,
        summary="Discover collections in daily notes",
        description="List existing collections with their dailyNoteDate, optionally filtered by "
        "startDate/endDate. Relative dates pass unchanged to Craft. Inspect get_collection_schema "
        "before writing rows. A collection block ID can also be its collection ID. "
        "This does not list rows or execute stored views; no pagination is documented.",
    )
    async def list_collections(client: Client, filters: Annotated[DailyDateRange, Query()]):
        return await client.list_collections(filters.model_dump(exclude_none=True))

    @router.get(
        "/blocks/{blockId}",
        operation_id="craft_daily_get_block",
        response_model=Block,
        response_model_exclude_none=True,
        summary="Read structured page content",
        description="Read a document/page root and nested blocks with IDs and hierarchy. "
        "Use the root id from get_note or a blockId from search_notes as blockId; "
        "do not extract an API ID from clickableLink. "
        "Use returned text-block IDs for update_block_markdown. Default depth 1 "
        "omits deeper descendants; -1 reads all descendants. Collection rows appear "
        "under items when returned by Craft; list_collection_items reads rows directly. "
        "Depth-limited reads preserve contentPreviewMd and itemsPreviewMd when supplied. Prefer "
        "read_markdown for reading and summarization. Craft scoped links and "
        "invalid:out_of_scope markers are preserved.",
    )
    async def get_block(blockId: Identifier, client: Client, depth: Annotated[BlockDepth, Query()]):
        return await client.get_block(blockId, depth.maxDepth)

    @router.get(
        "/blocks/{blockId}/markdown",
        operation_id="craft_daily_read_markdown",
        response_model=MarkdownContent,
        summary="Read rendered Markdown",
        description="Read a document/page as Craft-rendered Markdown for reading or "
        "summarization. Craft-specific structural tags and links are preserved. "
        "Default depth 1 omits deeper descendants; -1 reads all descendants. "
        "Use get_block instead when you need IDs and hierarchy for editing.",
    )
    async def read_markdown(
        blockId: Identifier, client: Client, depth: Annotated[BlockDepth, Query()]
    ):
        return MarkdownContent(
            blockId=blockId, markdown=await client.read_markdown(blockId, depth.maxDepth)
        )

    @router.post(
        "/blocks/{pageId}/content",
        operation_id="craft_daily_insert_markdown",
        status_code=201,
        response_model=Items[Block],
        response_model_exclude_none=True,
        summary="Insert Markdown into an existing page",
        description="Insert Markdown at the start or end of an existing document/page. "
        "The document ID is its root page ID. One insertion may create multiple "
        "blocks; returned IDs can be used for later updates. This adds content "
        "rather than replacing it. Writes are never retried; outcomeUnknown "
        "means content may already have been inserted.",
    )
    async def insert_markdown(pageId: Identifier, body: InsertMarkdown, client: Client):
        return await client.insert_markdown(pageId, body.markdown, body.position)

    @router.patch(
        "/blocks/{blockId}",
        operation_id="craft_daily_update_block_markdown",
        response_model=Block,
        response_model_exclude_none=True,
        summary="Update one text block's Markdown",
        description="Replace the Markdown of one existing text block whose ID was read "
        "with get_block. Other fields are preserved. This is not whole-document "
        "replacement. Craft validates the target's suitability. Writes are "
        "never retried; outcomeUnknown means the update may have happened.",
    )
    async def update_block(blockId: Identifier, body: UpdateMarkdown, client: Client):
        return await client.update_block_markdown(blockId, body.markdown)

    @router.get(
        "/collections/{collectionId}/schema",
        operation_id="craft_daily_get_collection_schema",
        response_model=CollectionSchema,
        response_model_exclude_none=True,
        summary="Inspect collection property keys and options",
        description="Read the editable schema representation of an existing collection. "
        "Use property keys, not display names, in item writes. Returned type "
        "strings are preserved. V1 writes accept strings only; complex properties "
        "and relations are unsupported. This does not change the schema or "
        "return items, and does not return an OpenAPI document.",
    )
    async def get_schema(collectionId: Identifier, client: Client):
        return await client.get_collection_schema(collectionId)

    @router.get(
        "/collections/{collectionId}/items",
        operation_id="craft_daily_list_collection_items",
        response_model=Items[CollectionItem],
        response_model_exclude_none=True,
        summary="Read collection items",
        description="Read all items in an existing collection. Default maxDepth=0 reads "
        "properties without nested content; -1 reads all descendants. Values "
        "can have collection-specific JSON shapes. No pagination or execution "
        "of stored view filters/sorts/groups is documented.",
    )
    async def list_items(
        collectionId: Identifier, client: Client, depth: Annotated[ItemDepth, Query()]
    ):
        return await client.list_collection_items(collectionId, depth.maxDepth)

    @router.post(
        "/collections/{collectionId}/items",
        operation_id="craft_daily_add_collection_item",
        status_code=201,
        response_model=CollectionItem,
        response_model_exclude_none=True,
        summary="Add one collection item",
        description="Add one titled row to an existing collection. Inspect its schema "
        "first; property keys and string values must suit that collection. "
        "V1 does not support relations or complex values. Writes are never "
        "retried; outcomeUnknown means the item may already have been created.",
    )
    async def add_item(collectionId: Identifier, body: AddCollectionItem, client: Client):
        return await client.add_collection_item(collectionId, body.title, body.properties)

    @router.patch(
        "/collections/{collectionId}/items/{itemId}",
        operation_id="craft_daily_update_collection_item_properties",
        response_model=CollectionItem,
        response_model_exclude_none=True,
        summary="Update selected collection-item properties",
        description="Update string-valued properties on one existing item. Obtain itemId "
        "from list_collection_items and property keys/options from its schema. "
        "Omitted keys are preserved; null clearing, title updates, and relations "
        "are unsupported. Writes are never retried; outcomeUnknown means the "
        "update may have happened.",
    )
    async def update_item(
        collectionId: Identifier,
        itemId: Identifier,
        body: UpdateCollectionProperties,
        client: Client,
    ):
        return await client.update_collection_item_properties(collectionId, itemId, body.properties)

    @router.get(
        "/tasks",
        operation_id="craft_daily_list_tasks",
        response_model=Items[Task],
        response_model_exclude_none=True,
        summary="List native Craft tasks by scope",
        description="Discover native task IDs in active, upcoming, inbox, or logbook. "
        "active/upcoming use schedule date when present, otherwise deadline date. "
        "logbook contains completed/canceled tasks. Space-specific "
        "all/document scopes are unsupported. "
        "Use returned IDs to update or delete tasks; collection rows "
        "are distinct from native tasks.",
    )
    async def list_tasks(client: Client, filters: Annotated[TaskFilters, Query()]):
        return await client.list_tasks(filters.scope)

    @router.post(
        "/tasks",
        operation_id="craft_daily_add_task",
        status_code=201,
        response_model=Task,
        response_model_exclude_none=True,
        summary="Create one native Craft task",
        description="Create one task in the inbox by default, or target a daily_note. "
        "date is valid only for daily_note and defaults to today for that target. "
        "Optional scheduleDate/deadlineDate accept calendar or relative dates, resolved by Craft. "
        "Task dates are not timed reminders. Writes are never retried; outcomeUnknown means "
        "the task may already exist.",
    )
    async def add_task(body: AddTask, client: Client):
        return await client.add_task(body.model_dump(exclude_none=True))

    @router.patch(
        "/tasks/{taskId}",
        operation_id="craft_daily_update_task",
        response_model=Task,
        response_model_exclude_none=True,
        summary="Update one native Craft task",
        description="Update selected Markdown, state, scheduleDate, or "
        "deadlineDate fields on a task "
        "whose ID came from list_tasks or add_task. At least one change is required. "
        "done/canceled moves tasks to Craft's logbook. Omitted "
        "fields are preserved; explicit nulls, "
        "date clearing, and task movement are unsupported. Writes are never retried; "
        "outcomeUnknown means the change may have happened. Responses can be partial.",
    )
    async def update_task(taskId: Identifier, body: UpdateTask, client: Client):
        return await client.update_task(taskId, body.model_dump(exclude_none=True))

    @router.delete(
        "/tasks/{taskId}",
        operation_id="craft_daily_delete_task",
        response_model=DeletedTask,
        summary="Delete one native Craft task",
        description="Delete a task by ID from this connection's daily notes, inbox, or logbook. "
        "This removes the task; it does not mark it done or canceled. No rollback is promised. "
        "Writes are never retried; outcomeUnknown means deletion may already have happened. "
        "Do not repeat an uncertain deletion blindly.",
    )
    async def delete_task(taskId: Identifier, client: Client):
        return await client.delete_task(taskId)

    return router

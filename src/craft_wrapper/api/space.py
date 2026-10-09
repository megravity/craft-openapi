from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from craft_wrapper.api.auth import require_token
from craft_wrapper.api.permissions import authorize_write
from craft_wrapper.api.responses import ERROR_RESPONSES
from craft_wrapper.api.schemas import (
    AddCollectionItem,
    AddSpaceTask,
    BlockDepth,
    CollectionFilters,
    CreateDocument,
    DocumentFilters,
    DocumentWriteContext,
    Identifier,
    InsertMarkdown,
    ItemDepth,
    MarkdownContent,
    SearchFilters,
    SpaceTaskFilters,
    SpaceTaskWriteContext,
    UpdateCollectionProperties,
    UpdateCollectionTitle,
    UpdateMarkdown,
    UpdateTask,
)
from craft_wrapper.craft.models import Block, CollectionItem, DeletedResource, Items
from craft_wrapper.craft.space.client import SpaceClient
from craft_wrapper.craft.space.models import (
    CollectionSchema,
    CollectionSummary,
    DocumentSearchHit,
    DocumentSummary,
    Folder,
    SpaceTask,
)


def get_client(request: Request) -> SpaceClient:
    return request.app.state.space_client


Client = Annotated[SpaceClient, Depends(get_client)]


def make_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/space",
        tags=["Craft Space"],
        dependencies=[Depends(require_token)],
        responses=ERROR_RESPONSES,
    )

    @router.get(
        "/tasks",
        operation_id="craft_space_list_tasks",
        response_model=Items[SpaceTask],
        response_model_exclude_none=True,
        summary="Discover native tasks across the Space",
        description="Read native tasks by active/upcoming/inbox/logbook/document/all scope. "
        "document requires documentId; all includes every task block, including unscheduled "
        "document tasks, and is broader than the union of the four Daily scopes. Locations, "
        "scheduling and completion metadata are retained. Discovery does not modify tasks.",
    )
    async def list_tasks(client: Client, filters: Annotated[SpaceTaskFilters, Query()]):
        return await client.list_tasks(filters.model_dump(exclude_none=True))

    @router.post(
        "/tasks",
        operation_id="craft_space_add_task",
        status_code=201,
        response_model=SpaceTask,
        response_model_exclude_none=True,
        summary="Create one task in an approved planning document",
        description="Create one native task at the top of the specified document. documentId "
        "is its root block ID and must be approved in profile mode. The root is verified "
        "freshly before submission in every mode. Optional scheduleDate/deadlineDate accept "
        "calendar or relative dates resolved by Craft. Use the Daily tool for inbox/daily-note "
        "targets. No retries; outcomeUnknown means the task may already exist.",
    )
    async def add_task(body: AddSpaceTask, client: Client, request: Request):
        await authorize_write(request)
        return await client.add_task(body.model_dump(exclude_none=True))

    @router.patch(
        "/tasks/{taskId}",
        operation_id="craft_space_update_task",
        response_model=SpaceTask,
        response_model_exclude_none=True,
        summary="Edit or complete one task in an approved document",
        description="Update selected Markdown, state (todo/done/canceled), scheduleDate, or "
        "deadlineDate. Require owning documentId query context in every mode. Fresh document "
        "structure and native-task discovery verify membership, excluding collection subtrees. "
        "Omitted fields are preserved; nulls, date clearing and movement are unsupported. "
        "Responses can be partial. No retries; inspect uncertain outcomes before repeating.",
    )
    async def update_task(
        taskId: Identifier,
        body: UpdateTask,
        client: Client,
        request: Request,
        context: Annotated[SpaceTaskWriteContext, Query()],
    ):
        await authorize_write(request)
        return await client.update_task(taskId, body.model_dump(exclude_none=True))

    @router.delete(
        "/tasks/{taskId}",
        operation_id="craft_space_delete_task",
        response_model=DeletedResource,
        summary="Delete one verified leaf task in an approved document",
        description="Require owning documentId query context in every mode. Verify document "
        "structure and native-task membership freshly. Only leaf text tasks are deletable; "
        "nested content, roots, media and collection subtrees are protected. Python tools "
        "require confirmation; authorized raw HTTP does not. No rollback or retries; "
        "inspect uncertain outcomes before repeating.",
    )
    async def delete_task(
        taskId: Identifier,
        client: Client,
        request: Request,
        context: Annotated[SpaceTaskWriteContext, Query()],
    ):
        await authorize_write(request)
        return await client.delete_task(taskId)

    @router.get(
        "/folders",
        operation_id="craft_space_list_folders",
        response_model=Items[Folder],
        response_model_exclude_none=True,
        summary="Discover locations and folders",
        description="List built-in locations and the folder hierarchy with document counts. "
        "Use folder IDs or built-in location names to narrow list_documents. "
        "No pagination is documented.",
    )
    async def list_folders(client: Client):
        return await client.list_folders()

    @router.get(
        "/documents",
        operation_id="craft_space_list_documents",
        response_model=Items[DocumentSummary],
        response_model_exclude_none=True,
        summary="List document IDs and titles",
        description="Discover documents before reading their root blocks. A document ID is "
        "its root block ID. Choose location OR folderId; folderId lists only "
        "direct documents, so list each descendant folder separately when needed. "
        "Daily-note date bounds require location=daily_notes. "
        "Ordering is unspecified; sort results client-side. "
        "With no scope filter this returns all documents and may "
        "be large; list_folders first. This is not content search. No pagination "
        "is documented. Metadata is optional. Use each item's id for API calls; "
        "clickableLink is for navigation and can contain a different documentId.",
    )
    async def list_documents(client: Client, filters: Annotated[DocumentFilters, Query()]):
        return await client.list_documents(filters.model_dump(exclude_none=True))

    @router.get(
        "/documents/search",
        operation_id="craft_space_search_documents",
        response_model=Items[DocumentSearchHit],
        response_model_exclude_none=True,
        summary="Search content across documents",
        description="Find content mentions using one plain include string. Matches can occur "
        "inside words, rather than only whole words. Returns relevance-ranked results "
        "with highlighted snippets, document IDs, and matching block IDs; result counts "
        "vary and completeness is not guaranteed. No pagination is documented. "
        "Choose at most one of location, folderId, documentId; folderId includes descendants. "
        "Daily-note date bounds do not require a location here. Use read_markdown "
        "to read a result's document, or get_block for IDs/hierarchy to edit. "
        "Regex is not exposed in v1.",
    )
    async def search_documents(client: Client, filters: Annotated[SearchFilters, Query()]):
        return await client.search_documents(filters.model_dump(exclude_none=True))

    @router.post(
        "/documents",
        operation_id="craft_space_create_document",
        status_code=201,
        response_model=DocumentSummary,
        response_model_exclude_none=True,
        summary="Create one empty document",
        description="Create one titled document in Unsorted (default), Templates, or a "
        "folder discovered with list_folders. Choose folderId OR location. "
        "Use insert_markdown with the returned ID to add content separately. "
        "This does not create a daily note. Writes are never retried; an error "
        "with outcomeUnknown means the document may already have been created.",
    )
    async def create_document(body: CreateDocument, client: Client):
        return await client.create_document(
            body.title, folder_id=body.folderId, location=body.location
        )

    @router.get(
        "/blocks/{blockId}",
        operation_id="craft_space_get_block",
        response_model=Block,
        response_model_exclude_none=True,
        summary="Read structured page content",
        description="Read a document/page root and nested blocks with IDs and hierarchy. "
        "Use the id from list_documents or documentId from search_documents as blockId; "
        "do not extract an API ID from clickableLink. "
        "Use returned text-block IDs for update_block_markdown. Default depth 1 "
        "omits deeper descendants; -1 reads all descendants. Collection rows appear "
        "under items when returned by Craft; list_collection_items reads rows directly. "
        "Depth-limited reads preserve contentPreviewMd and itemsPreviewMd when supplied. Prefer "
        "read_markdown for reading and summarization. Craft links are preserved.",
    )
    async def get_block(blockId: Identifier, client: Client, depth: Annotated[BlockDepth, Query()]):
        return await client.get_block(blockId, depth.maxDepth)

    @router.get(
        "/blocks/{blockId}/markdown",
        operation_id="craft_space_read_markdown",
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
        operation_id="craft_space_insert_markdown",
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
    async def insert_markdown(
        pageId: Identifier,
        body: InsertMarkdown,
        client: Client,
        request: Request,
        context: Annotated[DocumentWriteContext, Query()],
    ):
        await authorize_write(request)
        return await client.insert_markdown(pageId, body.markdown, body.position)

    @router.patch(
        "/blocks/{blockId}",
        operation_id="craft_space_update_block_markdown",
        response_model=Block,
        response_model_exclude_none=True,
        summary="Update one text block's Markdown",
        description="Replace the Markdown of one existing text block whose ID was read "
        "with get_block. Other fields are preserved. This is not whole-document "
        "replacement. Craft validates the target's suitability. Writes are "
        "never retried; outcomeUnknown means the update may have happened.",
    )
    async def update_block(
        blockId: Identifier,
        body: UpdateMarkdown,
        client: Client,
        request: Request,
        context: Annotated[DocumentWriteContext, Query()],
    ):
        await authorize_write(request)
        return await client.update_block_markdown(blockId, body.markdown)

    @router.get(
        "/collections",
        operation_id="craft_space_list_collections",
        response_model=Items[CollectionSummary],
        response_model_exclude_none=True,
        summary="Discover existing collections",
        description="List collections in the Space, optionally narrowed to one document. "
        "A collection block's id can also be its collection ID. "
        "Use a returned collection ID with get_collection_schema before writing "
        "items. This does not list rows or execute stored views. No pagination "
        "is documented.",
    )
    async def list_collections(client: Client, filters: Annotated[CollectionFilters, Query()]):
        return await client.list_collections(filters.documentId)

    @router.get(
        "/collections/{collectionId}/schema",
        operation_id="craft_space_get_collection_schema",
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
        operation_id="craft_space_list_collection_items",
        response_model=Items[CollectionItem],
        response_model_exclude_none=True,
        summary="Read collection items",
        description="Read all items in an existing collection. Default maxDepth=0 reads "
        "properties without nested content; -1 reads all descendants. Values "
        "can have collection-specific JSON shapes. A fresh schema read normalizes the headline "
        "to title; unknown extra fields are omitted. No pagination or execution "
        "of stored view filters/sorts/groups is documented.",
    )
    async def list_items(
        collectionId: Identifier, client: Client, depth: Annotated[ItemDepth, Query()]
    ):
        return await client.list_collection_items(collectionId, depth.maxDepth)

    @router.post(
        "/collections/{collectionId}/items",
        operation_id="craft_space_add_collection_item",
        status_code=201,
        response_model=CollectionItem,
        response_model_exclude_none=True,
        summary="Add one collection item",
        description="Add one titled row to an existing collection. Inspect its schema "
        "first; property keys and string values must suit that collection. "
        "V1 does not support relations or complex values. Writes are never "
        "retried; outcomeUnknown means the item may already have been created.",
    )
    async def add_item(
        collectionId: Identifier, body: AddCollectionItem, client: Client, request: Request
    ):
        schema = await authorize_write(request)
        return await client.add_collection_item(
            collectionId, body.title, body.properties, schema=schema
        )

    @router.post(
        "/collections/{collectionId}/items/{itemId}/content",
        operation_id="craft_space_insert_collection_item_markdown",
        status_code=201,
        response_model=Items[Block],
        response_model_exclude_none=True,
        summary="Add Markdown context inside one collection entry",
        description="Append/prepend Markdown to an existing entry body; its title/properties "
        "are preserved. Obtain itemId from collection reads. Fresh collection membership and "
        "the full item structure are verified in every mode; planner requires an approved "
        "collection. Multiple text/page blocks can be created. Read the body with read_markdown "
        "using itemId as blockId and maxDepth=-1. No retries; inspect uncertain outcomes.",
    )
    async def insert_item_markdown(
        collectionId: Identifier,
        itemId: Identifier,
        body: InsertMarkdown,
        client: Client,
        request: Request,
    ):
        await authorize_write(request)
        return await client.insert_collection_item_markdown(itemId, body.markdown, body.position)

    @router.patch(
        "/collections/{collectionId}/items/{itemId}/blocks/{blockId}",
        operation_id="craft_space_update_collection_item_block_markdown",
        response_model=Block,
        response_model_exclude_none=True,
        summary="Edit one text block inside a collection entry",
        description="Replace one text block's Markdown, preserving other entry content, "
        "title and properties. Use block IDs from get_block(itemId,maxDepth=-1). Verify fresh "
        "collection/item ownership and structural membership in every mode; planner requires "
        "an approved collection. The item root, nested collections/items, links/properties "
        "and non-text resources cannot be targets. No whole-body replacement or retries.",
    )
    async def update_item_block(
        collectionId: Identifier,
        itemId: Identifier,
        blockId: Identifier,
        body: UpdateMarkdown,
        client: Client,
        request: Request,
    ):
        await authorize_write(request)
        return await client.update_collection_item_block_markdown(blockId, body.markdown)

    @router.delete(
        "/collections/{collectionId}/items/{itemId}/blocks/{blockId}",
        operation_id="craft_space_delete_collection_item_block",
        response_model=DeletedResource,
        summary="Delete one verified leaf text block inside a collection entry",
        description="Delete only a leaf text block in the verified entry structure. Fresh "
        "collection/item membership is required in every mode; planner requires an approved "
        "collection. Roots, descendants, nested collections/items and media are protected. "
        "Python tools require a live confirmation; authorized raw HTTP does not. "
        "No retries or rollback; inspect uncertain outcomes before repeating.",
    )
    async def delete_item_block(
        collectionId: Identifier,
        itemId: Identifier,
        blockId: Identifier,
        client: Client,
        request: Request,
    ):
        await authorize_write(request)
        return await client.delete_collection_item_block(blockId)

    @router.patch(
        "/collections/{collectionId}/items/{itemId}/title",
        operation_id="craft_space_update_collection_item_title",
        response_model=CollectionItem,
        response_model_exclude_none=True,
        summary="Rename one existing collection row",
        description="Set a nonempty title on one existing row. Craft's current schema selects "
        "the native headline key; the public response uses title. Other properties/nested "
        "content are preserved. Planner requires an approved collection and fresh item membership; "
        "read-only/migration cannot rename. No schema replacement, clearing, retries or rollback. "
        "Responses can be partial; verify uncertain outcomes before repeating.",
    )
    async def update_item_title(
        collectionId: Identifier,
        itemId: Identifier,
        body: UpdateCollectionTitle,
        client: Client,
        request: Request,
    ):
        schema = await authorize_write(request)
        return await client.update_collection_item_title(
            collectionId, itemId, body.title, schema=schema
        )

    @router.patch(
        "/collections/{collectionId}/items/{itemId}",
        operation_id="craft_space_update_collection_item_properties",
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
        request: Request,
    ):
        schema = await authorize_write(request)
        return await client.update_collection_item_properties(
            collectionId, itemId, body.properties, schema=schema
        )

    @router.delete(
        "/collections/{collectionId}/items/{itemId}",
        operation_id="craft_space_delete_collection_item",
        response_model=DeletedResource,
        summary="Delete one collection item and its nested content",
        description="Delete one row by IDs from collection discovery/item reads. This also removes "
        "nested content. Profile writes require an approved collection and verified membership. "
        "Open WebUI Python tools require confirmation; raw API calls do not. "
        "No retries or rollback.",
    )
    async def delete_item(
        collectionId: Identifier, itemId: Identifier, client: Client, request: Request
    ):
        await authorize_write(request)
        return await client.delete_collection_item(collectionId, itemId)

    @router.delete(
        "/blocks/{blockId}",
        operation_id="craft_space_delete_block",
        response_model=DeletedResource,
        summary="Delete one leaf text block",
        description="Delete only a leaf text block from a verified document/note structure. "
        "Requires owning documentId context, including in legacy mode. "
        "Roots, pages, collections, media, descendants, and incomplete reads are rejected. "
        "Open WebUI Python tools require confirmation; raw API calls do not. "
        "No retries or rollback.",
    )
    async def delete_block(
        blockId: Identifier,
        client: Client,
        request: Request,
        context: Annotated[DocumentWriteContext, Query()],
    ):
        await authorize_write(request)
        return await client.delete_block(blockId)

    return router

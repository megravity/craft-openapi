from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from craft_wrapper.api.auth import require_token
from craft_wrapper.api.documents_schemas import (
    DocumentsCollectionFilters,
    DocumentsFilters,
    DocumentsSearchFilters,
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
from craft_wrapper.craft.documents.client import DocumentsClient
from craft_wrapper.craft.documents.models import DocumentSummary
from craft_wrapper.craft.models import (
    Block,
    CollectionItem,
    CollectionSchema,
    CollectionSummary,
    DocumentSearchHit,
    Items,
)


def get_client(request: Request) -> DocumentsClient:
    return request.app.state.documents_client


Client = Annotated[DocumentsClient, Depends(get_client)]


def make_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/documents",
        tags=["Craft Multi-Document"],
        dependencies=[Depends(require_token)],
        responses=ERROR_RESPONSES,
    )

    @router.get(
        "/documents",
        operation_id="craft_documents_list_documents",
        response_model=Items[DocumentSummary],
        response_model_exclude_none=True,
        summary="List document IDs and titles",
        description="Discover documents exposed by this Multi-Document connection, including "
        "deleted entries marked isDeleted. Use each item's id as the root block ID for reads; "
        "clickableLink is for navigation and may contain a different ID. Metadata is optional. "
        "No location, folder, or date filters are supported; no pagination is documented.",
    )
    async def list_documents(client: Client, filters: Annotated[DocumentsFilters, Query()]):
        return await client.list_documents(filters.model_dump(exclude_none=True))

    @router.get(
        "/documents/search",
        operation_id="craft_documents_search_documents",
        response_model=Items[DocumentSearchHit],
        response_model_exclude_none=True,
        summary="Search content across documents",
        description="Find content mentions within this connection using one plain include string. "
        "Returns relevance-ranked snippets and matching block IDs; Craft documents top 20 "
        "results, not an exhaustive inventory. Optional documentId can be included or excluded "
        "with documentFilterMode; this never expands the connection's access. Use read_markdown "
        "for reading or get_block for IDs and hierarchy. Regex and pagination are unsupported.",
    )
    async def search_documents(client: Client, filters: Annotated[DocumentsSearchFilters, Query()]):
        return await client.search_documents(filters.model_dump(exclude_none=True))

    @router.get(
        "/blocks/{blockId}",
        operation_id="craft_documents_get_block",
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
        "read_markdown for reading and summarization. Craft scoped links and "
        "invalid:out_of_scope markers are preserved.",
    )
    async def get_block(blockId: Identifier, client: Client, depth: Annotated[BlockDepth, Query()]):
        return await client.get_block(blockId, depth.maxDepth)

    @router.get(
        "/blocks/{blockId}/markdown",
        operation_id="craft_documents_read_markdown",
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
        operation_id="craft_documents_insert_markdown",
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
        operation_id="craft_documents_update_block_markdown",
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
        "/collections",
        operation_id="craft_documents_list_collections",
        response_model=Items[CollectionSummary],
        response_model_exclude_none=True,
        summary="Discover existing collections",
        description="List collections within this connection. Include or exclude one document "
        "with documentId "
        "and documentFilterMode; neither expands connection access. "
        "A collection block's id can also be its collection ID. "
        "Use a returned collection ID with get_collection_schema before writing "
        "items. This does not list rows or execute stored views. No pagination "
        "is documented.",
    )
    async def list_collections(
        client: Client, filters: Annotated[DocumentsCollectionFilters, Query()]
    ):
        return await client.list_collections(filters.model_dump(exclude_none=True))

    @router.get(
        "/collections/{collectionId}/schema",
        operation_id="craft_documents_get_collection_schema",
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
        operation_id="craft_documents_list_collection_items",
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
        operation_id="craft_documents_add_collection_item",
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
        operation_id="craft_documents_update_collection_item_properties",
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

    return router

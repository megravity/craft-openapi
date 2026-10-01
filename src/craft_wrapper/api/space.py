from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from craft_wrapper.api.auth import require_token
from craft_wrapper.api.schemas import (
    AddCollectionItem,
    BlockDepth,
    CollectionFilters,
    CreateDocument,
    DocumentFilters,
    ErrorResponse,
    Identifier,
    InsertMarkdown,
    ItemDepth,
    MarkdownContent,
    SearchFilters,
    UpdateCollectionProperties,
    UpdateMarkdown,
)
from craft_wrapper.craft.models import Block, Items
from craft_wrapper.craft.space.client import SpaceClient
from craft_wrapper.craft.space.models import (
    CollectionItem,
    CollectionSchema,
    CollectionSummary,
    DocumentSearchHit,
    DocumentSummary,
    Folder,
)

ERROR_RESPONSES = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "Craft rejected the request.",
        401: "Missing or invalid wrapper bearer token.",
        404: "Craft resource not found.",
        409: "Craft conflict.",
        413: "Request body exceeds 1 MiB.",
        422: "Invalid request parameters or body.",
        429: "Craft rate limit; inspect Retry-After.",
        500: "Internal wrapper error.",
        502: "Craft access, response, or upstream failure.",
        503: "Could not reach Craft.",
        504: "Craft request timed out.",
    }.items()
}


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
        "its root block ID. Choose location OR folderId; folders include "
        "subfolders. With no scope filter this returns all documents and may "
        "be large; list_folders first. This is not content search. No pagination "
        "is documented. Metadata is optional.",
    )
    async def list_documents(client: Client, filters: Annotated[DocumentFilters, Query()]):
        return await client.list_documents(filters.model_dump(exclude_none=True))

    @router.get(
        "/documents/search",
        operation_id="craft_space_search_documents",
        response_model=Items[DocumentSearchHit],
        response_model_exclude_none=True,
        summary="Search content across documents",
        description="Find content mentions using one plain include string. Returns the top "
        "20 relevance-ranked results with highlighted snippets, document IDs, "
        "and matching block IDs; it is not exhaustive and has no pagination. "
        "Choose at most one of location, folderId, documentId. Use read_markdown "
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
        "Use a document ID from list_documents or search_documents as blockId. "
        "Use returned text-block IDs for update_block_markdown. Default depth 1 "
        "omits deeper descendants; -1 reads all descendants. Prefer "
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
    async def insert_markdown(pageId: Identifier, body: InsertMarkdown, client: Client):
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
    async def update_block(blockId: Identifier, body: UpdateMarkdown, client: Client):
        return await client.update_block_markdown(blockId, body.markdown)

    @router.get(
        "/collections",
        operation_id="craft_space_list_collections",
        response_model=Items[CollectionSummary],
        response_model_exclude_none=True,
        summary="Discover existing collections",
        description="List collections in the Space, optionally narrowed to one document. "
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
        "can have collection-specific JSON shapes. No pagination or execution "
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
    async def add_item(collectionId: Identifier, body: AddCollectionItem, client: Client):
        return await client.add_collection_item(collectionId, body.title, body.properties)

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
    ):
        return await client.update_collection_item_properties(collectionId, itemId, body.properties)

    return router

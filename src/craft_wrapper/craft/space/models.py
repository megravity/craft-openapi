from typing import Any

from pydantic import Field

from craft_wrapper.craft.models import Block, CraftModel


class Folder(CraftModel):
    id: str
    name: str
    documentCount: int
    folders: list["Folder"]


class DocumentSummary(CraftModel):
    id: str
    title: str
    dailyNoteDate: str | None = None
    createdAt: str | None = None
    lastModifiedAt: str | None = None
    clickableLink: str | None = None


class DocumentSearchHit(CraftModel):
    documentId: str
    markdown: str
    blockIds: list[str]
    blocks: list[Block] | None = None


class CollectionSummary(CraftModel):
    id: str
    name: str
    itemCount: int
    documentId: str


class TitleProperty(CraftModel):
    key: str
    name: str


class CollectionProperty(CraftModel):
    key: str
    name: str
    type: str = Field(description="Craft's returned type string; not a universal type enum.")
    options: list[str] | None = None


class CollectionSchema(CraftModel):
    key: str | None = None
    name: str
    contentPropDetails: TitleProperty
    properties: list[CollectionProperty]


class CollectionItem(CraftModel):
    id: str
    title: str | None = None
    properties: dict[str, Any] | None = Field(
        default=None,
        description="Dynamic collection values returned by Craft, including nested JSON.",
    )
    content: list[Block] | None = None

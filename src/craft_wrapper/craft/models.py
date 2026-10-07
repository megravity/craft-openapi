from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CraftModel(BaseModel):
    # Documentation is example-based: accept additions, expose only modeled fields.
    model_config = ConfigDict(extra="ignore", strict=True)


class DeletedResource(CraftModel):
    id: str


class Block(CraftModel):
    id: str
    type: str
    textStyle: str | None = None
    markdown: str | None = None
    font: str | None = None
    url: str | None = None
    altText: str | None = None
    content: list["Block"] | None = None
    items: list["CollectionItem"] | None = Field(
        default=None, description="Collection rows returned within the requested depth."
    )
    contentPreviewMd: str | None = Field(
        default=None, description="Markdown preview of content omitted by the depth limit."
    )
    itemsPreviewMd: str | None = Field(
        default=None, description="Markdown preview of collection rows omitted by the depth limit."
    )


class CollectionItem(CraftModel):
    id: str
    type: str | None = None
    title: str | None = Field(default=None, description="May be omitted for untitled rows.")
    markdown: str | None = None
    properties: dict[str, Any] | None = Field(
        default=None,
        description="Dynamic collection values returned by Craft, including nested JSON. "
        "Single-select values can be strings and multi-select values arrays; "
        "the wrapper preserves their shape. Empty or omitted properties are valid.",
    )
    content: list[Block] | None = None
    contentPreviewMd: str | None = Field(
        default=None, description="Markdown preview of content omitted by the depth limit."
    )


Block.model_rebuild()


class Items[T](CraftModel):
    items: list[T] = Field(
        description="Returned items; no pagination is documented for this operation."
    )


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


class SelectOption(CraftModel):
    name: str
    color: str | None = None


class CollectionProperty(CraftModel):
    key: str
    name: str
    type: str = Field(description="Craft's returned type string; not a universal type enum.")
    options: list[str | SelectOption] | None = Field(
        default=None,
        description="Option labels from documentation or name/color objects returned by Craft. "
        "Object names are the labels; color is preserved when supplied.",
    )


class CollectionSchema(CraftModel):
    key: str | None = None
    name: str
    contentPropDetails: TitleProperty | None = Field(
        default=None, description="Title-property metadata, when supplied by Craft."
    )
    properties: list[CollectionProperty]


class TaskInfo(CraftModel):
    state: str | None = None
    scheduleDate: str | None = None
    deadlineDate: str | None = None

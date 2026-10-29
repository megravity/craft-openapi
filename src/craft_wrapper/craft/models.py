from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CraftModel(BaseModel):
    # Documentation is example-based: accept additions, expose only modeled fields.
    model_config = ConfigDict(extra="ignore", strict=True)


class DeletedResource(CraftModel):
    id: str


class TaskInfo(CraftModel):
    state: str | None = None
    scheduleDate: str | None = None
    deadlineDate: str | None = None


class BlockMetadata(CraftModel):
    createdAt: str | None = Field(
        default=None,
        description="Upstream creation timestamp; absent means unknown.",
        json_schema_extra={"format": "date-time"},
    )
    lastModifiedAt: str | None = None

    @field_validator("createdAt", "lastModifiedAt")
    @classmethod
    def timestamp(cls, value: str | None) -> str | None:
        if value is not None and datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Expected an offset-aware creation/modification timestamp")
        return value


class Block(CraftModel):
    id: str
    type: str
    textStyle: str | None = None
    markdown: str | None = None
    font: str | None = None
    url: str | None = None
    altText: str | None = None
    listStyle: str | None = None
    taskInfo: TaskInfo | None = None
    metadata: BlockMetadata | None = None
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
    title: str | None = Field(
        default=None,
        description="Row headline; collection-item endpoints normalize the schema key. "
        "May be omitted for untitled rows or partial mutation responses.",
    )
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


class TaskDetail(Block):
    """One verified native task, with the requested depth of child blocks."""


class ConnectionSpace(CraftModel):
    id: str = Field(min_length=1)
    timezone: str = Field(min_length=1)
    time: str = Field(min_length=1)
    friendlyDate: str | None = None


class ConnectionUTC(CraftModel):
    time: str = Field(min_length=1)


class AppLinkTemplates(CraftModel):
    app: str = Field(min_length=1, description="Native Craft app URL template, not an API URL.")

    @field_validator("app")
    @classmethod
    def native_app_template(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "craftdocs"
            or parsed.netloc != "open"
            or "{blockId}" not in value
            or any(char.isspace() or ord(char) < 32 for char in value)
        ):
            raise ValueError("Expected a Craft native app block-link template")
        return value


class ConnectionInfo(CraftModel):
    space: ConnectionSpace
    utc: ConnectionUTC
    urlTemplates: AppLinkTemplates


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

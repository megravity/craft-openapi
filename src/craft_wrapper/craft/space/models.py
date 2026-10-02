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
    clickableLink: str | None = Field(
        default=None,
        description="Craft navigation link. Its documentId can differ from the API id; "
        "use id for API requests rather than extracting an ID from this link.",
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


class CollectionItem(CraftModel):
    id: str
    title: str | None = None
    properties: dict[str, Any] | None = Field(
        default=None,
        description="Dynamic collection values returned by Craft, including nested JSON. "
        "Single-select values can be strings and multi-select values arrays; "
        "the wrapper preserves their shape.",
    )
    content: list[Block] | None = None

from pydantic import Field

from craft_wrapper.craft.models import CollectionSchema as CollectionSchema
from craft_wrapper.craft.models import CollectionSummary as CollectionSummary
from craft_wrapper.craft.models import CraftModel
from craft_wrapper.craft.models import DocumentSearchHit as DocumentSearchHit


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

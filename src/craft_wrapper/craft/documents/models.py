from pydantic import Field

from craft_wrapper.craft.models import CraftModel


class DocumentSummary(CraftModel):
    id: str
    title: str
    isDeleted: bool
    createdAt: str | None = None
    lastModifiedAt: str | None = None
    clickableLink: str | None = Field(
        default=None,
        description="Craft navigation link. Use id for API calls; its embedded documentId "
        "may be different.",
    )

from typing import Literal

from pydantic import Field, model_validator

from craft_wrapper.api.schemas import Identifier, InputModel, NonemptyText


class DocumentsFilters(InputModel):
    fetchMetadata: bool = False


class DocumentsCollectionFilters(InputModel):
    documentId: Identifier | None = None
    documentFilterMode: Literal["include", "exclude"] | None = Field(
        default=None,
        description="Include or exclude documentId within this connection; defaults to include "
        "when documentId is supplied. Requires documentId.",
    )

    @model_validator(mode="after")
    def require_document(self) -> "DocumentsCollectionFilters":
        if self.documentFilterMode is not None and self.documentId is None:
            raise ValueError("documentFilterMode requires documentId")
        return self


class DocumentsSearchFilters(DocumentsCollectionFilters):
    query: NonemptyText = Field(description="One plain content-search include string, not a regex.")
    fetchBlocks: bool = False

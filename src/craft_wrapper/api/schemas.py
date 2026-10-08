import re
from datetime import date
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    model_validator,
)

Identifier = Annotated[
    StrictStr, Field(min_length=1, description="Opaque Craft ID, not necessarily a UUID.")
]
NonemptyText = Annotated[StrictStr, Field(min_length=1)]
Location = Literal["unsorted", "trash", "templates", "daily_notes"]


def validate_date(value: str) -> str:
    if value in {"today", "tomorrow", "yesterday"}:
        return value
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use YYYY-MM-DD, today, tomorrow, or yesterday")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("Invalid calendar date") from None
    return value


CraftDate = Annotated[
    str,
    Field(description="Calendar date YYYY-MM-DD or today/tomorrow/yesterday, resolved by Craft."),
    AfterValidator(validate_date),
]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DateFilters(InputModel):
    createdDateGte: CraftDate | None = None
    createdDateLte: CraftDate | None = None
    lastModifiedDateGte: CraftDate | None = None
    lastModifiedDateLte: CraftDate | None = None
    dailyNoteDateGte: CraftDate | None = None
    dailyNoteDateLte: CraftDate | None = None

    @model_validator(mode="after")
    def ordered_absolute_dates(self) -> "DateFilters":
        for prefix in ("createdDate", "lastModifiedDate", "dailyNoteDate"):
            lower, upper = getattr(self, prefix + "Gte"), getattr(self, prefix + "Lte")
            if lower and upper and lower[0].isdigit() and upper[0].isdigit() and lower > upper:
                raise ValueError("Absolute date range start must not follow its end")
        return self


class DocumentFilters(DateFilters):
    location: Location | None = Field(
        default=None, description="Required as daily_notes when using dailyNoteDateGte/Lte."
    )
    folderId: Identifier | None = Field(
        default=None,
        description="Lists direct documents only; query descendant folders separately.",
    )
    fetchMetadata: bool = False

    @model_validator(mode="after")
    def exclusive_location(self) -> "DocumentFilters":
        if self.location is not None and self.folderId is not None:
            raise ValueError("Use only one of location or folderId")
        if (
            self.dailyNoteDateGte is not None or self.dailyNoteDateLte is not None
        ) and self.location != "daily_notes":
            raise ValueError("Daily-note date filters require location=daily_notes")
        return self


class SearchFilters(DateFilters):
    query: NonemptyText = Field(
        description="One plain content-search include string; can match substrings inside words. "
        "Not a regex."
    )
    location: Location | None = None
    folderId: Identifier | None = Field(
        default=None, description="Includes this folder's subfolders."
    )
    documentId: Identifier | None = None
    fetchBlocks: bool = False

    @model_validator(mode="after")
    def exclusive_scope(self) -> "SearchFilters":
        if sum(value is not None for value in (self.location, self.folderId, self.documentId)) > 1:
            raise ValueError("Use only one of location, folderId, or documentId")
        return self


class BlockDepth(InputModel):
    maxDepth: int = Field(
        default=1,
        ge=-1,
        description="1: root and direct children; 0: root only; -1: all descendants. "
        "Finite depths deliberately omit deeper content.",
    )


class ItemDepth(InputModel):
    maxDepth: int = Field(
        default=0,
        ge=-1,
        description="0: properties only; positive values: nested content depth; "
        "-1: all descendants.",
    )


class CollectionFilters(InputModel):
    documentId: Identifier | None = None


class SpaceTaskFilters(InputModel):
    scope: Literal["active", "upcoming", "inbox", "logbook", "document", "all"]
    documentId: Identifier | None = None

    @model_validator(mode="after")
    def document_scope(self) -> "SpaceTaskFilters":
        if (self.scope == "document") != (self.documentId is not None):
            raise ValueError("documentId is required only for scope=document")
        return self


class AddSpaceTask(InputModel):
    documentId: Identifier = Field(description="Owning document root ID; approved in profile mode.")
    markdown: NonemptyText
    scheduleDate: CraftDate | None = None
    deadlineDate: CraftDate | None = None

    @model_validator(mode="after")
    def no_nulls(self) -> "AddSpaceTask":
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Explicit nulls and date clearing are unsupported")
        return self


class SpaceTaskWriteContext(InputModel):
    documentId: Identifier = Field(
        description="Owning document root ID, required in every mode. "
        "Used for fresh structure/native-task verification; never moves the task."
    )


class UpdateTask(InputModel):
    markdown: NonemptyText | None = None
    state: Literal["todo", "done", "canceled"] | None = None
    scheduleDate: CraftDate | None = None
    deadlineDate: CraftDate | None = None

    @model_validator(mode="after")
    def nonempty_changes(self) -> "UpdateTask":
        if not self.model_fields_set:
            raise ValueError("Provide at least one task change")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Explicit nulls and date clearing are unsupported")
        return self


class CreateDocument(InputModel):
    title: NonemptyText
    folderId: Identifier | None = None
    location: Literal["unsorted", "templates"] | None = Field(
        default=None, description="Omit both destination fields to create in Unsorted."
    )

    @model_validator(mode="after")
    def exclusive_destination(self) -> "CreateDocument":
        if self.folderId is not None and self.location is not None:
            raise ValueError("Use only one of location or folderId")
        return self


class InsertMarkdown(InputModel):
    markdown: NonemptyText = Field(
        description="Craft Markdown to insert; may create multiple blocks."
    )
    position: Literal["start", "end"] = "end"


class UpdateMarkdown(InputModel):
    markdown: StrictStr = Field(description="Replacement Markdown for one existing text block.")


class DocumentWriteContext(InputModel):
    documentId: Identifier | None = Field(
        default=None,
        description="Owning document root ID. Required for profile-scoped block "
        "writes and all leaf-block deletions; verified against fresh structure.",
    )


PropertyValues = dict[Identifier, StrictStr]


class AddCollectionItem(InputModel):
    title: NonemptyText
    properties: PropertyValues = Field(
        default_factory=dict,
        description="Use keys from get_collection_schema. Only string values are supported; "
        "Craft validates each property's value. Relations are unsupported in v1.",
    )


class UpdateCollectionProperties(InputModel):
    properties: PropertyValues = Field(
        min_length=1,
        description="Property keys to update, with string values. Omitted keys are preserved. "
        "V1 does not support relations, null clearing, or title updates.",
    )


class UpdateCollectionTitle(InputModel):
    title: NonemptyText


class MarkdownContent(BaseModel):
    blockId: str
    markdown: str


class ErrorDetail(BaseModel):
    field: str
    message: str


class ErrorInfo(BaseModel):
    code: str
    message: str
    requestId: str
    upstreamStatus: int | None = None
    upstreamCode: str | None = None
    retryAfterSeconds: int | None = None
    outcomeUnknown: bool | None = None
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorInfo

from typing import Literal

from pydantic import Field, model_validator

from craft_wrapper.api.schemas import BlockDepth, CraftDate, InputModel, NonemptyText


class DailyNoteSelector(InputModel):
    date: CraftDate = "today"


class DailyNoteRead(DailyNoteSelector, BlockDepth):
    pass


class DailyDateRange(InputModel):
    startDate: CraftDate | None = None
    endDate: CraftDate | None = None

    @model_validator(mode="after")
    def ordered_absolute_dates(self) -> "DailyDateRange":
        lower, upper = self.startDate, self.endDate
        if lower and upper and lower[0].isdigit() and upper[0].isdigit() and lower > upper:
            raise ValueError("Absolute date range start must not follow its end")
        return self


class DailySearchFilters(DailyDateRange):
    query: NonemptyText = Field(description="One plain content-search include string, not a regex.")
    fetchBlocks: bool = False


class DailyMarkdownContent(InputModel):
    date: str = Field(description="Requested date selector, including relative dates unchanged.")
    markdown: str


class TaskFilters(InputModel):
    scope: Literal["active", "upcoming", "inbox", "logbook"] = Field(
        description="active/upcoming classify open tasks by schedule date, falling back to "
        "deadline date. inbox selects the task inbox; logbook selects completed/canceled tasks."
    )


class AddTask(InputModel):
    markdown: NonemptyText
    target: Literal["inbox", "daily_note"] = "inbox"
    date: CraftDate | None = Field(
        default=None, description="Only valid for daily_note; omitted means today for that target."
    )
    scheduleDate: CraftDate | None = None
    deadlineDate: CraftDate | None = None

    @model_validator(mode="after")
    def valid_target(self) -> "AddTask":
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Explicit nulls and date clearing are unsupported")
        if self.target == "inbox" and self.date is not None:
            raise ValueError("date requires target=daily_note")
        return self


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

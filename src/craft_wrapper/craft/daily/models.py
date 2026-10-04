from craft_wrapper.craft.models import Block, CraftModel


class DailyNoteSearchHit(CraftModel):
    dailyNoteDate: str
    markdown: str
    blockIds: list[str]
    blocks: list[Block] | None = None


class DailyCollectionSummary(CraftModel):
    id: str
    name: str
    itemCount: int
    dailyNoteDate: str


class TaskInfo(CraftModel):
    state: str | None = None
    scheduleDate: str | None = None
    deadlineDate: str | None = None


class Task(CraftModel):
    id: str
    markdown: str | None = None
    taskInfo: TaskInfo | None = None


class DeletedTask(CraftModel):
    id: str

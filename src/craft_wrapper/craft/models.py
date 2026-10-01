from pydantic import BaseModel, ConfigDict, Field


class CraftModel(BaseModel):
    # Documentation is example-based: accept additions, expose only modeled fields.
    model_config = ConfigDict(extra="ignore", strict=True)


class Block(CraftModel):
    id: str
    type: str
    textStyle: str | None = None
    markdown: str | None = None
    font: str | None = None
    url: str | None = None
    altText: str | None = None
    content: list["Block"] | None = None


class Items[T](CraftModel):
    items: list[T] = Field(
        description="Returned items; no pagination is documented for this operation."
    )

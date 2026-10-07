"""Concrete, opt-in access profiles; connection secrets stay in Settings."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
)

Adapter = Literal["space", "documents", "daily"]
ProfileId = Literal["read-only", "planner", "migration"]
PROFILE_TOKEN_FIELDS = {
    "read-only": "wrapper_read_only_token",
    "planner": "wrapper_planner_token",
    "migration": "wrapper_migration_token",
}


class WriteTargets(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    documentIds: list[StrictStr] = Field(default_factory=list)
    collectionIds: list[StrictStr] = Field(default_factory=list)

    @field_validator("documentIds", "collectionIds")
    @classmethod
    def identifiers(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(
            not v.strip() or v in {".", ".."} for v in values
        ):
            raise ValueError("Targets require unique nonempty resource IDs")
        return values


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    enabled: StrictBool = True
    adapters: list[Adapter] = Field(min_length=1)
    operations: list[StrictStr] | None = Field(default=None, min_length=1)
    writeTargets: dict[Adapter, WriteTargets] = Field(default_factory=dict)
    expiresAt: AwareDatetime | None = None

    @field_validator("adapters", "operations")
    @classmethod
    def unique_values(cls, values):
        if values is not None and len(values) != len(set(values)):
            raise ValueError("Profile lists must contain unique values")
        return values

    @property
    def expired(self) -> bool:
        return self.expiresAt is not None and datetime.now(UTC) >= self.expiresAt

    def targets(self, adapter: str) -> WriteTargets:
        return next((v for k, v in self.writeTargets.items() if k == adapter), WriteTargets())


class Profiles(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    read_only: Profile | None = Field(default=None, alias="read-only")
    planner: Profile | None = None
    migration: Profile | None = None

    def entries(self) -> dict[str, Profile]:
        return {
            name: profile
            for name, profile in (
                ("read-only", self.read_only),
                ("planner", self.planner),
                ("migration", self.migration),
            )
            if profile is not None
        }

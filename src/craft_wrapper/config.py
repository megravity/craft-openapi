import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import (
    Field,
    PrivateAttr,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from craft_wrapper.profiles import PROFILE_TOKEN_FIELDS, Profile, Profiles

SPACE_OPERATION_IDS = frozenset(
    {
        "craft_space_list_folders",
        "craft_space_list_tasks",
        "craft_space_add_task",
        "craft_space_update_task",
        "craft_space_delete_task",
        "craft_space_list_documents",
        "craft_space_search_documents",
        "craft_space_create_document",
        "craft_space_delete_block",
        "craft_space_delete_collection_item",
        "craft_space_get_block",
        "craft_space_read_markdown",
        "craft_space_insert_markdown",
        "craft_space_update_block_markdown",
        "craft_space_list_collections",
        "craft_space_get_collection_schema",
        "craft_space_list_collection_items",
        "craft_space_add_collection_item",
        "craft_space_update_collection_item_properties",
        "craft_space_update_collection_item_title",
    }
)

SPACE_READ_OPERATION_IDS = frozenset(
    {
        "craft_space_list_folders",
        "craft_space_list_tasks",
        "craft_space_list_documents",
        "craft_space_search_documents",
        "craft_space_get_block",
        "craft_space_read_markdown",
        "craft_space_list_collections",
        "craft_space_get_collection_schema",
        "craft_space_list_collection_items",
    }
)

DOCUMENTS_OPERATION_IDS = frozenset(
    {
        "craft_documents_list_documents",
        "craft_documents_search_documents",
        "craft_documents_get_block",
        "craft_documents_read_markdown",
        "craft_documents_insert_markdown",
        "craft_documents_update_block_markdown",
        "craft_documents_list_collections",
        "craft_documents_get_collection_schema",
        "craft_documents_list_collection_items",
        "craft_documents_add_collection_item",
        "craft_documents_delete_block",
        "craft_documents_delete_collection_item",
        "craft_documents_update_collection_item_properties",
        "craft_documents_update_collection_item_title",
    }
)
DOCUMENTS_READ_OPERATION_IDS = frozenset(
    {
        "craft_documents_list_documents",
        "craft_documents_search_documents",
        "craft_documents_get_block",
        "craft_documents_read_markdown",
        "craft_documents_list_collections",
        "craft_documents_get_collection_schema",
        "craft_documents_list_collection_items",
    }
)
DAILY_READ_OPERATION_IDS = frozenset(
    {
        "craft_daily_get_note",
        "craft_daily_read_note_markdown",
        "craft_daily_get_block",
        "craft_daily_read_markdown",
        "craft_daily_search_notes",
        "craft_daily_list_collections",
        "craft_daily_get_collection_schema",
        "craft_daily_list_collection_items",
        "craft_daily_list_tasks",
    }
)
DAILY_OPERATION_IDS = DAILY_READ_OPERATION_IDS | frozenset(
    {
        "craft_daily_insert_note_markdown",
        "craft_daily_insert_markdown",
        "craft_daily_update_block_markdown",
        "craft_daily_add_collection_item",
        "craft_daily_update_collection_item_properties",
        "craft_daily_update_collection_item_title",
        "craft_daily_add_task",
        "craft_daily_update_task",
        "craft_daily_delete_task",
        "craft_daily_delete_block",
        "craft_daily_delete_collection_item",
    }
)
OPERATION_IDS = SPACE_OPERATION_IDS | DOCUMENTS_OPERATION_IDS | DAILY_OPERATION_IDS
OPERATION_PRESETS = {
    "full": OPERATION_IDS,
    "read_only": SPACE_READ_OPERATION_IDS | DOCUMENTS_READ_OPERATION_IDS | DAILY_READ_OPERATION_IDS,
}


def _parse_enabled_operations(value: str | None, available: frozenset[str]) -> frozenset[str]:
    if value is None:
        return available
    preset = re.sub(r"[\s-]+", "_", value.strip().casefold())
    if preset in OPERATION_PRESETS:
        return OPERATION_PRESETS[preset] & available
    entries = [entry.strip() for entry in value.split(",")]
    if not all(entries) or set(entries) - OPERATION_IDS:
        raise ValueError("Expected full, read_only, or a list of valid operation IDs")
    if set(entries) - available:
        raise ValueError("Operation IDs require their configured Craft connection")
    return frozenset(entries)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    craft_space_base_url: SecretStr | None = None
    craft_documents_base_url: SecretStr | None = None
    craft_daily_base_url: SecretStr | None = None
    wrapper_api_token: SecretStr | None = None
    wrapper_profiles_json: str | None = Field(default=None, repr=False)
    wrapper_read_only_token: SecretStr | None = None
    wrapper_planner_token: SecretStr | None = None
    wrapper_migration_token: SecretStr | None = None
    craft_timeout_seconds: float = 30
    craft_connect_timeout_seconds: float = 5
    wrapper_enabled_operations: str | None = None
    wrapper_public_url: str | None = None
    _profiles: dict[str, Profile] = PrivateAttr(default_factory=dict)

    def __init__(self, **values: Any) -> None:
        # Required fields can come from settings sources rather than constructor arguments.
        super().__init__(**values)

    @field_validator("craft_space_base_url", "craft_documents_base_url", "craft_daily_base_url")
    @classmethod
    def validate_craft_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value()
        if any(c.isspace() or ord(c) < 32 for c in raw) or "?" in raw or "#" in raw:
            raise ValueError("Craft URL must not contain whitespace, a query, or a fragment")
        parsed = urlsplit(raw)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in {"connect.craft.do", "connect.craft.do:443"}
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(r"/links/[A-Za-z0-9_-]+/api/v1/?", parsed.path)
            or "/REPLACE_ME/" in parsed.path
        ):
            raise ValueError("Expected a real HTTPS Craft secret-link API URL")
        return value

    @field_validator(
        "wrapper_read_only_token",
        "wrapper_planner_token",
        "wrapper_migration_token",
    )
    @classmethod
    def validate_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        token = value.get_secret_value()
        if not token.strip() or token == "REPLACE_ME" or any(c.isspace() for c in token):
            raise ValueError("Expected a nonempty wrapper token without whitespace")
        return value

    @field_validator("craft_timeout_seconds", "craft_connect_timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        import math

        if not math.isfinite(value) or value <= 0:
            raise ValueError("Timeout must be a finite positive number")
        return value

    @field_validator("wrapper_public_url")
    @classmethod
    def validate_public_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(c.isspace() or ord(c) < 32 for c in value) or "?" in value or "#" in value:
            raise ValueError("Public URL must not contain whitespace, a query, or a fragment")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Public URL must be a non-secret HTTP(S) origin")
        # Accessing port also validates malformed port numbers.
        _ = parsed.port
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_operations(self) -> "Settings":
        if not self.profile_mode and self.wrapper_api_token is None:
            raise ValidationError.from_exception_data(
                "Settings",
                [{"type": "missing", "loc": ("wrapper_api_token",), "input": None}],
            )
        if not self.profile_mode:
            try:
                self.validate_token(self.wrapper_api_token)
            except ValueError as error:
                raise ValidationError.from_exception_data(
                    "Settings",
                    [
                        {
                            "type": "value_error",
                            "loc": ("wrapper_api_token",),
                            "input": None,
                            "ctx": {"error": error},
                        }
                    ],
                ) from None
        if all(
            connection is None
            for connection in (
                self.craft_space_base_url,
                self.craft_documents_base_url,
                self.craft_daily_base_url,
            )
        ):
            raise ValueError("At least one Craft connection must be configured")
        _parse_enabled_operations(self.wrapper_enabled_operations, self.available_operations)
        if self.wrapper_profiles_json is not None:
            try:
                entries = Profiles.model_validate_json(self.wrapper_profiles_json).entries()
                if not entries:
                    raise ValueError("At least one profile must be configured")
                credentials = []
                for name, profile in entries.items():
                    if set(profile.adapters) - self.configured_adapters:
                        raise ValueError("Profile adapters require configured connections")
                    if set(profile.writeTargets) - set(profile.adapters):
                        raise ValueError("Targets require an enabled profile adapter")
                    if profile.targets("daily").documentIds:
                        raise ValueError("Daily content uses date context, not document targets")
                    if name == "read-only" and profile.writeTargets:
                        raise ValueError("Read-only profiles cannot have write targets")
                    if name == "migration" and (
                        "space" not in profile.adapters
                        or profile.expiresAt is None
                        or len(profile.targets("space").collectionIds) != 1
                        or profile.targets("space").documentIds
                        or set(profile.writeTargets) != {"space"}
                    ):
                        raise ValueError(
                            "Migration requires expiration and exactly one Space collection"
                        )
                    if profile.operations is not None and (
                        set(profile.operations) - self.available_operations
                        or set(profile.operations) - self.profile_preset(name, profile)
                    ):
                        raise ValueError("Invalid profile operations")
                    token = self.profile_token(name)
                    if profile.enabled and token is None:
                        raise ValueError("Enabled profiles require their credential")
                    if token is not None:
                        credentials.append(token.get_secret_value())
                if len(credentials) != len(set(credentials)):
                    raise ValueError("Profile credentials must be distinct")
                self._profiles = entries
            except (ValueError, ValidationError):
                raise ValueError("Invalid experimental profile configuration") from None
        return self

    @property
    def profiles(self) -> dict[str, Profile]:
        return self._profiles

    @property
    def profile_mode(self) -> bool:
        return self.wrapper_profiles_json is not None

    @property
    def configured_adapters(self) -> set[str]:
        return {
            name
            for name in ("space", "documents", "daily")
            if getattr(self, f"craft_{name}_base_url") is not None
        }

    def profile_token(self, name: str) -> SecretStr | None:
        return getattr(self, PROFILE_TOKEN_FIELDS[name])

    def profile_preset(self, name: str, profile: Profile) -> frozenset[str]:
        reads = OPERATION_PRESETS["read_only"]
        allowed = {op for op in reads if op.split("_")[1] in profile.adapters}
        if name == "planner":
            for adapter in profile.adapters:
                targets = profile.targets(adapter)
                if targets.collectionIds:
                    allowed.update(
                        f"craft_{adapter}_{suffix}"
                        for suffix in (
                            "add_collection_item",
                            "update_collection_item_properties",
                            "update_collection_item_title",
                            "delete_collection_item",
                        )
                    )
                if targets.documentIds or adapter == "daily":
                    allowed.update(
                        f"craft_{adapter}_{suffix}"
                        for suffix in (
                            "insert_markdown",
                            "update_block_markdown",
                            "delete_block",
                        )
                    )
                if adapter == "space" and targets.documentIds:
                    allowed.update(
                        f"craft_space_{suffix}"
                        for suffix in ("add_task", "update_task", "delete_task")
                    )
                if adapter == "daily":
                    allowed.update(
                        f"craft_daily_{suffix}"
                        for suffix in (
                            "insert_note_markdown",
                            "add_task",
                            "update_task",
                            "delete_task",
                        )
                    )
        elif name == "migration":
            allowed.add("craft_space_add_collection_item")
        return frozenset(allowed) & self.available_operations

    def profile_operations(self, name: str) -> frozenset[str]:
        profile = self.profiles[name]
        allowed = self.profile_preset(name, profile) & self.enabled_operations
        return allowed if profile.operations is None else allowed & frozenset(profile.operations)

    @property
    def enabled_operations(self) -> frozenset[str]:
        return _parse_enabled_operations(self.wrapper_enabled_operations, self.available_operations)

    @property
    def available_operations(self) -> frozenset[str]:
        return (
            (SPACE_OPERATION_IDS if self.craft_space_base_url is not None else frozenset())
            | (
                DOCUMENTS_OPERATION_IDS
                if self.craft_documents_base_url is not None
                else frozenset()
            )
            | (DAILY_OPERATION_IDS if self.craft_daily_base_url is not None else frozenset())
        )

    @property
    def secrets(self) -> tuple[str, ...]:
        values = [
            token.get_secret_value()
            for token in (
                self.wrapper_api_token,
                self.wrapper_read_only_token,
                self.wrapper_planner_token,
                self.wrapper_migration_token,
            )
            if token is not None
        ]
        for connection in (
            self.craft_space_base_url,
            self.craft_documents_base_url,
            self.craft_daily_base_url,
        ):
            if connection is not None:
                url = connection.get_secret_value()
                values.extend((url, urlsplit(url).path.split("/")[2]))
        return tuple(values)


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        fields = sorted(
            {str(error["loc"][0]) if error["loc"] else "settings" for error in exc.errors()}
        )
        raise RuntimeError("Invalid wrapper configuration: " + ", ".join(fields)) from None

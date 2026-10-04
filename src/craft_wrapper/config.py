import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SPACE_OPERATION_IDS = frozenset(
    {
        "craft_space_list_folders",
        "craft_space_list_documents",
        "craft_space_search_documents",
        "craft_space_create_document",
        "craft_space_get_block",
        "craft_space_read_markdown",
        "craft_space_insert_markdown",
        "craft_space_update_block_markdown",
        "craft_space_list_collections",
        "craft_space_get_collection_schema",
        "craft_space_list_collection_items",
        "craft_space_add_collection_item",
        "craft_space_update_collection_item_properties",
    }
)

SPACE_READ_OPERATION_IDS = frozenset(
    {
        "craft_space_list_folders",
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
        "craft_documents_update_collection_item_properties",
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
        "craft_daily_add_task",
        "craft_daily_update_task",
        "craft_daily_delete_task",
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
    wrapper_api_token: SecretStr
    craft_timeout_seconds: float = 30
    craft_connect_timeout_seconds: float = 5
    wrapper_enabled_operations: str | None = None
    wrapper_public_url: str | None = None

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

    @field_validator("wrapper_api_token")
    @classmethod
    def validate_token(cls, value: SecretStr) -> SecretStr:
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
        return self

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
        values = [self.wrapper_api_token.get_secret_value()]
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

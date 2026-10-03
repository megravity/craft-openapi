"""
title: Craft Multi-Document HTTP Wrapper
description: Explicit HTTP calls to the configured Craft wrapper, with request evidence.
version: 0.3.0
requirements: httpx
"""

import asyncio
import json
import logging
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_RESPONSE_BYTES = 9 * 1024 * 1024


class _WrapperRequestLogFilter(logging.Filter):
    """Keep HTTPX from logging document IDs and content-search queries for this client."""

    def __init__(self, origin: str):
        super().__init__()
        self.origin = httpx.URL(origin)

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        return not (
            isinstance(args, tuple)
            and len(args) > 1
            and isinstance(args[1], httpx.URL)
            and (args[1].scheme, args[1].host, args[1].port)
            == (self.origin.scheme, self.origin.host, self.origin.port)
        )


class Tools:
    class Valves(BaseModel):
        model_config = ConfigDict(hide_input_in_errors=True)

        WRAPPER_URL: str = Field(
            default="http://craft-wrapper:8000",
            description="Wrapper origin reachable from Open WebUI; not a Craft connection URL.",
        )
        WRAPPER_API_TOKEN: str = Field(
            default="",
            repr=False,
            description="Wrapper bearer token only, without the Bearer prefix.",
            json_schema_extra={"input": {"type": "password"}},
        )
        TIMEOUT_SECONDS: float = Field(
            default=45,
            gt=0,
            le=300,
            description="Overall HTTP deadline; allow time for the wrapper.",
        )

        @field_validator("WRAPPER_URL")
        @classmethod
        def validate_origin(cls, value: str) -> str:
            parsed = urlsplit(value)
            if (
                any(c.isspace() or ord(c) < 32 for c in value)
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or "?" in value
                or "#" in value
                or parsed.hostname.lower() in {"connect.craft.do", "mcp.craft.do"}
            ):
                raise ValueError("Use the wrapper HTTP(S) origin without credentials or a path")
            _ = parsed.port
            return value.rstrip("/")

    def __init__(self):
        self.valves = self.Valves()

    @staticmethod
    def _id(value: str) -> str:
        if not isinstance(value, str) or not value or value in {".", ".."}:
            raise ValueError("Resource IDs must be nonempty strings other than . or ..")
        return quote(value, safe="")

    async def _request(
        self,
        method: str,
        path: str,
        parameters: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"method": method, "path": path, "query": {}}
        status = None
        request_id = None
        write = method != "GET"

        def failure(code: str, message: str) -> dict[str, Any]:
            error: dict[str, Any] = {"code": code, "message": message}
            if write:
                error["outcomeUnknown"] = submitted
            return {
                "request": request,
                "statusCode": status,
                "requestId": request_id,
                "response": {"error": error},
            }

        submitted = False
        token = self.valves.WRAPPER_API_TOKEN
        if not token or any(c.isspace() for c in token):
            return failure("tool_configuration_error", "Set WRAPPER_API_TOKEN to the token alone.")
        try:
            if parameters is not None and not isinstance(parameters, dict):
                return failure("tool_invalid_arguments", "parameters must be a JSON object.")
            if body is not None and not isinstance(body, dict):
                return failure("tool_invalid_arguments", "body must be a JSON object.")
            query: dict[str, str] = {}
            for key, value in (parameters or {}).items():
                if not isinstance(key, str) or not isinstance(value, (str, int, bool, type(None))):
                    return failure("tool_invalid_arguments", "Query values must be scalar or null.")
                if value is not None:
                    query[key] = str(value).lower() if isinstance(value, bool) else str(value)
            # Unknown query keys and body fields reach the wrapper for its own validation.
            request["query"] = query
            origin = self.valves.WRAPPER_URL
            log_filter = _WrapperRequestLogFilter(origin)
            logger = logging.getLogger("httpx")
            logger.addFilter(log_filter)
            try:
                async with asyncio.timeout(self.valves.TIMEOUT_SECONDS):
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(self.valves.TIMEOUT_SECONDS, connect=5),
                        follow_redirects=False,
                        trust_env=False,
                    ) as client:
                        submitted = True
                        async with client.stream(
                            method,
                            origin + path,
                            params=query,
                            json=body,
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Accept": "application/json",
                            },
                        ) as result:
                            status = result.status_code
                            request_id = result.headers.get("X-Request-Id")
                            data = bytearray()
                            async for chunk in result.aiter_bytes():
                                if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                                    return failure(
                                        "tool_response_too_large", "Wrapper response exceeds 9 MiB."
                                    )
                                data.extend(chunk)
                            media_type = (
                                result.headers.get("content-type", "").split(";")[0].lower()
                            )
                            if media_type != "application/json" and not media_type.endswith(
                                "+json"
                            ):
                                return failure(
                                    "tool_invalid_response", "Wrapper did not return JSON."
                                )
                            payload = json.loads(data)
                            if not isinstance(payload, dict):
                                return failure(
                                    "tool_invalid_response", "Wrapper did not return a JSON object."
                                )
                            return {
                                "request": request,
                                "statusCode": status,
                                "requestId": request_id,
                                "response": payload,
                            }
            finally:
                logger.removeFilter(log_filter)
        except (TimeoutError, httpx.TimeoutException):
            return failure("tool_wrapper_timeout", "Wrapper request timed out; it was not retried.")
        except httpx.RequestError:
            return failure(
                "tool_wrapper_unavailable", "Could not reach the wrapper; no retry made."
            )
        except (TypeError, ValueError, UnicodeError):
            return failure("tool_invalid_response", "Invalid JSON arguments or wrapper response.")

    async def craft_documents_list_documents(
        self, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Discover documents exposed by this connection, including isDeleted entries.
        Use id for API requests, never clickableLink's embedded documentId.
        :param parameters: JSON query object. Optional fetchMetadata=false. Location, folder,
            documentId, and date filters are unsupported and return 422.
        """
        return await self._request("GET", "/v1/documents/documents", parameters)

    async def craft_documents_search_documents(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """
        Search within the selected documents. Relevance-limited snippets are not an inventory.
        :param parameters: JSON query object with required query string. Optional documentId,
            documentFilterMode (include or exclude, requires documentId, defaults to include),
            fetchBlocks=false. Filters never expand this connection's access. Regex, date,
            location, and folder filters are unsupported.
        """
        return await self._request("GET", "/v1/documents/documents/search", parameters)

    async def craft_documents_get_block(
        self, blockId: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Read structured blocks and editable IDs. Finite depth is incomplete; previews are preserved.
        Read collection properties with list_collection_items; standalone item reads may omit them.
        :param blockId: API id from document/block discovery, not a navigation-link ID.
        :param parameters: Optional JSON query object with maxDepth (default 1; -1 all descendants).
        """
        return await self._request("GET", f"/v1/documents/blocks/{self._id(blockId)}", parameters)

    async def craft_documents_read_markdown(
        self, blockId: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Read rendered Markdown for summarization, with Craft structural tags and previews intact.
        Craft can render block-link properties as [object Object]; read items for structured values.
        :param blockId: API document/page/block ID.
        :param parameters: Optional JSON query object with maxDepth (default 1; -1 all descendants).
        """
        return await self._request(
            "GET", f"/v1/documents/blocks/{self._id(blockId)}/markdown", parameters
        )

    async def craft_documents_insert_markdown(
        self, pageId: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Insert Markdown into one existing page; adds content and may create multiple blocks.
        :param pageId: API root/page ID from document or block discovery.
        :param body: JSON object with nonempty markdown; position defaults to end (or use start).
        """
        return await self._request(
            "POST", f"/v1/documents/blocks/{self._id(pageId)}/content", body=body
        )

    async def craft_documents_update_block_markdown(
        self, blockId: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Replace Markdown on one text block while preserving other fields.
        :param blockId: Editable text-block ID from structured block reads.
        :param body: JSON object with markdown string. Empty string allowed; other fields rejected.
        """
        return await self._request("PATCH", f"/v1/documents/blocks/{self._id(blockId)}", body=body)

    async def craft_documents_list_collections(
        self, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Discover existing collections within this Multi-Document connection.
        A collection block's id can be used as its collection ID. Inspect schema before writing.
        :param parameters: JSON query object with optional documentId and documentFilterMode
            (include or exclude, requires documentId, defaults to include).
        """
        return await self._request("GET", "/v1/documents/collections", parameters)

    async def craft_documents_get_collection_schema(self, collectionId: str) -> dict[str, Any]:
        """
        Discover property keys/types/options before writing. Schema and views remain unchanged.
        :param collectionId: Collection ID from list_collections, not its parent document ID.
        """
        return await self._request(
            "GET", f"/v1/documents/collections/{self._id(collectionId)}/schema"
        )

    async def craft_documents_list_collection_items(
        self, collectionId: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Read collection rows with structured properties, including links and relations.
        Titles can be omitted; properties can be empty. No view execution or pagination.
        :param collectionId: Collection ID from discovery.
        :param parameters: Optional JSON query object with maxDepth (default 0; -1 all descendants).
        """
        return await self._request(
            "GET", f"/v1/documents/collections/{self._id(collectionId)}/items", parameters
        )

    async def craft_documents_add_collection_item(
        self, collectionId: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Add one titled row to an existing collection. Inspect its schema first.
        :param collectionId: Collection ID from discovery.
        :param body: JSON object with title; optional properties object using schema keys and string
            values only. Relations, arrays, booleans, numbers and null writes are unsupported.
        """
        return await self._request(
            "POST", f"/v1/documents/collections/{self._id(collectionId)}/items", body=body
        )

    async def craft_documents_update_collection_item_properties(
        self, collectionId: str, itemId: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Update selected properties of one existing row. Omitted properties are preserved.
        :param collectionId: Collection ID from discovery.
        :param itemId: Item ID from list_collection_items.
        :param body: JSON object with nonempty properties mapping schema keys to string values.
            Craft validates each string value. Title updates, relations, complex values,
            and clearing are unsupported.
        """
        return await self._request(
            "PATCH",
            f"/v1/documents/collections/{self._id(collectionId)}/items/{self._id(itemId)}",
            body=body,
        )

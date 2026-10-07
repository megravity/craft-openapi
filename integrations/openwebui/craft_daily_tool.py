"""
title: Craft Daily Notes HTTP Wrapper
description: Explicit HTTP calls to the configured Craft wrapper, with request evidence.
version: 0.4.0
requirements: httpx
"""

import asyncio
import copy
import json
import logging
from typing import Any, Literal
from urllib.parse import quote, unquote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_RESPONSE_BYTES = 9 * 1024 * 1024
CONFIRMATION_TIMEOUT_SECONDS = 120
UI_EVENT_TIMEOUT_SECONDS = 5


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
        WRAPPER_PROFILE: Literal["", "read-only", "planner", "migration"] = Field(
            default="",
            description="Experimental profile; empty uses legacy routes. Token must match.",
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

    async def _http_request(
        self,
        method: str,
        path: str,
        parameters: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        *,
        valves=None,
    ) -> dict[str, Any]:
        valves = valves or self.valves
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
        token = valves.WRAPPER_API_TOKEN
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
            origin = valves.WRAPPER_URL
            log_filter = _WrapperRequestLogFilter(origin)
            logger = logging.getLogger("httpx")
            logger.addFilter(log_filter)
            try:
                async with asyncio.timeout(valves.TIMEOUT_SECONDS):
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(valves.TIMEOUT_SECONDS, connect=5),
                        follow_redirects=False,
                        trust_env=False,
                    ) as client:
                        submitted = True
                        async with client.stream(
                            method,
                            origin
                            + (
                                f"/profiles/{valves.WRAPPER_PROFILE}"
                                if valves.WRAPPER_PROFILE
                                else ""
                            )
                            + path,
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

    @staticmethod
    def _blocked(method: str, path: str, code: str, message: str) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if method != "GET":
            error["outcomeUnknown"] = False
        return {
            "request": {"method": method, "path": path, "query": {}},
            "statusCode": None,
            "requestId": None,
            "response": {"error": error},
        }

    async def _confirmation_failure(
        self, method: str, path: str, code: str, message: str, event_emitter
    ) -> dict[str, Any]:
        result = self._blocked(method, path, code, message)
        if event_emitter is not None:
            try:
                await asyncio.wait_for(
                    event_emitter(
                        {
                            "type": "status",
                            "data": {
                                "description": f"Nothing deleted. {message}",
                                "done": True,
                                "hidden": False,
                            },
                        }
                    ),
                    timeout=UI_EVENT_TIMEOUT_SECONDS,
                )
            except Exception:
                pass  # UI delivery failure must preserve the original no-mutation result.
        return result

    async def _capabilities(self, valves) -> dict[str, Any]:
        if valves.WRAPPER_PROFILE:
            return await self._http_request("GET", "/capabilities", valves=valves)
        result = await self._http_request("GET", "/openapi.json", valves=valves)
        if result["statusCode"] != 200:
            return result
        schema = result["response"]
        try:
            operations = [
                operation["operationId"]
                for path in schema["paths"].values()
                for method, operation in path.items()
                if method in {"get", "post", "put", "patch", "delete"}
            ]
        except (KeyError, TypeError, AttributeError):
            return self._blocked(
                "GET",
                "/openapi.json",
                "tool_capabilities_unavailable",
                "Could not determine enabled wrapper operations.",
            )
        result["response"] = {
            "profileId": None,
            "operations": operations,
            "writeTargets": {},
            "restrictionMode": "legacy",
        }
        return result

    async def _request(
        self,
        method: str,
        path: str,
        parameters: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        *,
        operation_id: str,
        event_call=None,
        event_emitter=None,
    ) -> dict[str, Any]:
        valves = self.valves.model_copy(deep=True)
        try:
            parameters, body = copy.deepcopy(parameters), copy.deepcopy(body)
        except (TypeError, ValueError, RecursionError):
            return self._blocked(method, path, "tool_invalid_arguments", "Invalid JSON arguments.")
        if (parameters is not None and not isinstance(parameters, dict)) or (
            body is not None and not isinstance(body, dict)
        ):
            return self._blocked(
                method, path, "tool_invalid_arguments", "Arguments must be JSON objects."
            )
        if any(
            not isinstance(key, str) or not isinstance(value, (str, int, bool, type(None)))
            for key, value in (parameters or {}).items()
        ):
            return self._blocked(
                method, path, "tool_invalid_arguments", "Query values must be scalar or null."
            )
        if valves.WRAPPER_PROFILE:
            capabilities = await self._capabilities(valves)
            if capabilities["statusCode"] != 200:
                return capabilities
            if capabilities["response"].get("profileId") != valves.WRAPPER_PROFILE:
                return self._blocked(
                    method,
                    path,
                    "tool_capabilities_unavailable",
                    "Wrapper capabilities did not match the configured profile.",
                )
            operations = capabilities["response"].get("operations")
            if not isinstance(operations, list) or not all(
                isinstance(op, str) for op in operations
            ):
                return self._blocked(
                    method,
                    path,
                    "tool_capabilities_unavailable",
                    "Could not determine enabled profile operations.",
                )
            if operation_id not in operations:
                return self._blocked(
                    method,
                    path,
                    "tool_permission_denied",
                    "This operation is not enabled for this profile.",
                )
        if method == "DELETE":
            if event_call is None:
                return await self._confirmation_failure(
                    method,
                    path,
                    "tool_confirmation_required",
                    "Deletion requires a live Open WebUI confirmation dialog.",
                    event_emitter,
                )
            parts = path.split("/")
            try:
                if parts[3] == "collections" and parts[5] == "items":
                    collection_id, resource_id = unquote(parts[4]), unquote(parts[6])
                    preview = await self._http_request(
                        "GET", "/".join(parts[:6]), {"maxDepth": 0}, valves=valves
                    )
                    resource = next(
                        item
                        for item in preview["response"].get("items", [])
                        if item.get("id") == resource_id
                    )
                    label = resource.get("title") or "Untitled row"
                    consequence = "This deletes the row and all nested item content."
                    target = f"Collection ID: {collection_id}\nItem ID: {resource_id}"
                else:
                    resource_id = unquote(parts[4])
                    preview = await self._http_request(
                        "GET",
                        f"/v1/{parts[2]}/blocks/{parts[4]}",
                        {"maxDepth": 0},
                        valves=valves,
                    )
                    resource = preview["response"]
                    if resource.get("id") != resource_id:
                        raise ValueError("Unreadable target")
                    label = resource.get("markdown") or "Untitled block/task"
                    consequence = (
                        "This deletes the selected task."
                        if parts[3] == "tasks"
                        else "This deletes the selected leaf text block."
                    )
                    target = f"ID: {resource_id}"
                if preview["statusCode"] != 200 or not isinstance(label, str):
                    raise ValueError("Unreadable target")
            except (KeyError, TypeError, ValueError, StopIteration, IndexError, AttributeError):
                return await self._confirmation_failure(
                    method,
                    path,
                    "tool_preview_unavailable",
                    "Could not read the exact deletion target; nothing was deleted.",
                    event_emitter,
                )
            context = "".join(f"\n{key}: {value}" for key, value in (parameters or {}).items())
            prompt = {
                "type": "confirmation",
                "data": {
                    "title": "Confirm Craft deletion",
                    "message": f"Profile: {valves.WRAPPER_PROFILE or 'legacy'}\n"
                    f"Operation: {operation_id}\n{target}{context}\n"
                    f"Content preview: {label[:400]}\n{consequence} No rollback is promised.",
                },
            }
            try:
                confirmed = await asyncio.wait_for(
                    event_call(prompt), timeout=CONFIRMATION_TIMEOUT_SECONDS
                )
            except TimeoutError:
                return await self._confirmation_failure(
                    method,
                    path,
                    "tool_confirmation_unavailable",
                    "Confirmation timed out; nothing was deleted. Do not automatically retry.",
                    event_emitter,
                )
            except Exception:
                return await self._confirmation_failure(
                    method,
                    path,
                    "tool_confirmation_unavailable",
                    "Confirmation failed; nothing was deleted. Do not automatically retry.",
                    event_emitter,
                )
            if confirmed is False:
                return await self._confirmation_failure(
                    method,
                    path,
                    "tool_confirmation_declined",
                    "Deletion was canceled; nothing was deleted. Do not automatically retry.",
                    event_emitter,
                )
            if confirmed is not True:
                return await self._confirmation_failure(
                    method,
                    path,
                    "tool_confirmation_invalid_response",
                    "Confirmation returned an invalid response; nothing was deleted. "
                    "Do not automatically retry.",
                    event_emitter,
                )
        return await self._http_request(method, path, parameters, body, valves=valves)

    async def craft_daily_get_note(
        self, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Read a daily-note root with editable IDs and hierarchy.
        :param parameters: Optional JSON query object with date (default today; YYYY-MM-DD or
            today/tomorrow/yesterday) and maxDepth (default 1; -1 all descendants).
        """
        return await self._request(
            "GET", "/v1/daily/notes", parameters, operation_id="craft_daily_get_note"
        )

    async def craft_daily_read_note_markdown(
        self, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Read a daily note as rendered Markdown for summarization; use get_note for editable IDs.
        :param parameters: Optional JSON query object with date (default today; YYYY-MM-DD or
            today/tomorrow/yesterday) and maxDepth (default 1; -1 all descendants).
        """
        return await self._request(
            "GET",
            "/v1/daily/notes/markdown",
            parameters,
            operation_id="craft_daily_read_note_markdown",
        )

    async def craft_daily_insert_note_markdown(
        self, body: dict[str, Any], parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Add content to a daily note by date; defaults to today, resolved by Craft.
        For duplicate dates, Craft selects the most recently updated note; use pageId for precision.
        :param body: JSON object with nonempty markdown and optional position (start/end;
            default end).
        :param parameters: Optional JSON query object with date (YYYY-MM-DD or
            today/tomorrow/yesterday).
        """
        return await self._request(
            "POST",
            "/v1/daily/notes/content",
            parameters,
            body,
            operation_id="craft_daily_insert_note_markdown",
        )

    async def craft_daily_search_notes(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """
        Search content across daily notes; relevance-limited top 20, not an exhaustive inventory.
        :param parameters: JSON query object with required query string; optional startDate,
            endDate (calendar or relative dates), and fetchBlocks (default false). Regex
                unsupported.
        """
        return await self._request(
            "GET", "/v1/daily/notes/search", parameters, operation_id="craft_daily_search_notes"
        )

    async def craft_daily_list_collections(
        self, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Discover existing daily-note collections. Inspect their schemas before writing rows.
        :param parameters: Optional JSON query object with startDate/endDate (calendar or relative
            dates). Responses identify the dailyNoteDate; no document or folder filters.
        """
        return await self._request(
            "GET", "/v1/daily/collections", parameters, operation_id="craft_daily_list_collections"
        )

    async def craft_daily_list_tasks(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """
        List native Craft tasks; native tasks are distinct from collection rows.
        :param parameters: JSON query object with required scope: active, upcoming, inbox,
            or logbook.
            active/upcoming use schedule date, otherwise deadline; logbook holds
                done/canceled tasks.
        """
        return await self._request(
            "GET", "/v1/daily/tasks", parameters, operation_id="craft_daily_list_tasks"
        )

    async def craft_daily_add_task(self, body: dict[str, Any]) -> dict[str, Any]:
        """
        Create one native task in the inbox or a daily note. Task dates are not timed reminders.
        :param body: JSON object with required markdown; target inbox (default) or daily_note;
            date is only valid for daily_note and defaults to today. Optional
                scheduleDate/deadlineDate
            accept calendar or relative dates. Explicit nulls unsupported.
        """
        return await self._request(
            "POST", "/v1/daily/tasks", body=body, operation_id="craft_daily_add_task"
        )

    async def craft_daily_update_task(self, taskId: str, body: dict[str, Any]) -> dict[str, Any]:
        """
        Update one native task; done/canceled moves it to the logbook. Responses may be partial.
        :param taskId: Task ID from list_tasks or add_task.
        :param body: Nonempty JSON object with markdown, state (todo/done/canceled), scheduleDate,
            and/or deadlineDate. Omitted fields preserved; null clearing and movement unsupported.
        """
        return await self._request(
            "PATCH",
            f"/v1/daily/tasks/{self._id(taskId)}",
            body=body,
            operation_id="craft_daily_update_task",
        )

    async def craft_daily_delete_task(
        self, taskId: str, __event_call__=None, __event_emitter__=None
    ) -> dict[str, Any]:
        """
        Delete one native task from daily notes, inbox, or logbook; this does not mark it done.
        No rollback or automatic retry. Do not blindly repeat an outcomeUnknown deletion.
        :param taskId: Task ID from list_tasks or add_task.
        """
        return await self._request(
            "DELETE",
            f"/v1/daily/tasks/{self._id(taskId)}",
            event_call=__event_call__,
            event_emitter=__event_emitter__,
            operation_id="craft_daily_delete_task",
        )

    async def craft_daily_get_block(
        self, blockId: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Read structured blocks and editable IDs. Finite depth is incomplete; previews are preserved.
        Read collection properties with list_collection_items; standalone item reads may omit them.
        :param blockId: API id from document/block discovery, not a navigation-link ID.
        :param parameters: Optional JSON query object with maxDepth (default 1; -1 all descendants).
            Do not send date write context on this read.
        """
        return await self._request(
            "GET",
            f"/v1/daily/blocks/{self._id(blockId)}",
            parameters,
            operation_id="craft_daily_get_block",
        )

    async def craft_daily_read_markdown(
        self, blockId: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Read rendered Markdown for summarization, with Craft structural tags and previews intact.
        Craft can render block-link properties as [object Object]; read items for structured values.
        :param blockId: API document/page/block ID.
        :param parameters: Optional JSON query object with maxDepth (default 1; -1 all descendants).
            Do not send date write context on this read.
        """
        return await self._request(
            "GET",
            f"/v1/daily/blocks/{self._id(blockId)}/markdown",
            parameters,
            operation_id="craft_daily_read_markdown",
        )

    async def craft_daily_insert_markdown(
        self, pageId: str, body: dict[str, Any], parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Insert Markdown into one existing page; adds content and may create multiple blocks.
        :param pageId: API root/page ID from document or block discovery.
        :param body: JSON object with nonempty markdown; position defaults to end (or use start).

        :param parameters: Owning date context required for profile-scoped writes.
        """
        return await self._request(
            "POST",
            f"/v1/daily/blocks/{self._id(pageId)}/content",
            parameters=parameters,
            body=body,
            operation_id="craft_daily_insert_markdown",
        )

    async def craft_daily_update_block_markdown(
        self, blockId: str, body: dict[str, Any], parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Replace Markdown on one text block while preserving other fields.
        :param blockId: Editable text-block ID from structured block reads.
        :param body: JSON object with markdown string. Empty string allowed; other fields rejected.

        :param parameters: Owning date context required for profile-scoped writes.
        """
        return await self._request(
            "PATCH",
            f"/v1/daily/blocks/{self._id(blockId)}",
            parameters=parameters,
            body=body,
            operation_id="craft_daily_update_block_markdown",
        )

    async def craft_daily_get_collection_schema(self, collectionId: str) -> dict[str, Any]:
        """
        Discover property keys/types/options before writing. Schema and views remain unchanged.
        :param collectionId: Collection ID from list_collections, not its parent document ID.
        """
        return await self._request(
            "GET",
            f"/v1/daily/collections/{self._id(collectionId)}/schema",
            operation_id="craft_daily_get_collection_schema",
        )

    async def craft_daily_list_collection_items(
        self, collectionId: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Read collection rows with structured properties, including links and relations.
        Titles can be omitted; properties can be empty. No view execution or pagination.
        :param collectionId: Collection ID from discovery.
        :param parameters: Optional JSON query object with maxDepth (default 0; -1 all descendants).
        """
        return await self._request(
            "GET",
            f"/v1/daily/collections/{self._id(collectionId)}/items",
            parameters,
            operation_id="craft_daily_list_collection_items",
        )

    async def craft_daily_add_collection_item(
        self, collectionId: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Add one titled row to an existing collection. Inspect its schema first.
        :param collectionId: Collection ID from discovery.
        :param body: JSON object with title; optional properties object using schema keys and string
            values only. Relations, arrays, booleans, numbers and null writes are unsupported.
        """
        return await self._request(
            "POST",
            f"/v1/daily/collections/{self._id(collectionId)}/items",
            body=body,
            operation_id="craft_daily_add_collection_item",
        )

    async def craft_daily_update_collection_item_properties(
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
            f"/v1/daily/collections/{self._id(collectionId)}/items/{self._id(itemId)}",
            body=body,
            operation_id="craft_daily_update_collection_item_properties",
        )

    async def craft_daily_get_capabilities(self) -> dict[str, Any]:
        """Discover enabled operations and writable targets; visibility is not authorization."""
        return await self._capabilities(self.valves.model_copy(deep=True))

    async def craft_daily_delete_collection_item(
        self,
        collectionId: str,
        itemId: str,
        __event_call__=None,
        __event_emitter__=None,
    ) -> dict[str, Any]:
        """Delete one row and its nested content after a live confirmation dialog.

        :param collectionId: Collection ID from discovery; must be writable for this profile.
        :param itemId: Exact item ID from collection reads.
        """
        return await self._request(
            "DELETE",
            f"/v1/daily/collections/{self._id(collectionId)}/items/{self._id(itemId)}",
            event_call=__event_call__,
            event_emitter=__event_emitter__,
            operation_id="craft_daily_delete_collection_item",
        )

    async def craft_daily_delete_block(
        self,
        blockId: str,
        parameters: dict[str, Any],
        __event_call__=None,
        __event_emitter__=None,
    ) -> dict[str, Any]:
        """Delete one verified leaf text block after a live confirmation dialog.

        :param blockId: Exact leaf text-block ID; root/page/collection/media deletion is rejected.
        :param parameters: Owning date context, required in every mode.
        """
        return await self._request(
            "DELETE",
            f"/v1/daily/blocks/{self._id(blockId)}",
            parameters,
            event_call=__event_call__,
            event_emitter=__event_emitter__,
            operation_id="craft_daily_delete_block",
        )

"""Update explicitly selected installed Open WebUI tools from this repository."""

import argparse
import ast
import hashlib
import json
import logging
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

REPO = Path(__file__).resolve().parents[1]
TOOL_PATHS = {
    adapter: REPO / "integrations" / "openwebui" / f"craft_{adapter}_tool.py"
    for adapter in ("space", "documents", "daily")
}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class UpdateError(Exception):
    """Safe CLI diagnostic; never include remote bodies, URLs, or credentials."""


@dataclass
class PlannedUpdate:
    tool_id: str
    source: str
    current: dict[str, Any]

    @property
    def changed(self) -> bool:
        return self.current["content"] != self.source


def tool_selection(value: str) -> tuple[str, str]:
    adapter, separator, tool_id = value.partition("=")
    if not separator or adapter not in TOOL_PATHS or not re.fullmatch(r"[a-z_][a-z0-9_]*", tool_id):
        raise argparse.ArgumentTypeError(
            "Use space=TOOL_ID, documents=TOOL_ID, or daily=TOOL_ID; "
            "IDs must be lowercase identifiers."
        )
    return adapter, tool_id


def base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in ("http", "https")
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not any(character.isspace() for character in value)
        )
        _ = parsed.port
        httpx.URL(value)
    except (ValueError, httpx.InvalidURL):
        valid = False
    if not valid:
        raise UpdateError("OWUI_URL must be an HTTP(S) base URL without credentials or query.")
    return value.rstrip("/") + "/api/v1/tools/"


def request_json(
    client: httpx.Client, method: str, path: str, *, payload: dict[str, Any] | None = None
) -> Any:
    try:
        with client.stream(method, path, json=payload) as response:
            if response.status_code != 200:
                raise UpdateError(f"Open WebUI returned HTTP {response.status_code}.")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise UpdateError("Open WebUI response exceeded 8 MiB.")
            return json.loads(body)
    except (httpx.HTTPError, ValueError):
        raise UpdateError("Open WebUI connection failed or returned invalid JSON.") from None


def read_tool(client: httpx.Client, tool_id: str) -> dict[str, Any]:
    try:
        data = request_json(client, "GET", f"id/{quote(tool_id, safe='')}")
    except UpdateError as error:
        raise UpdateError(f"{tool_id}: {error}") from None
    if (
        not isinstance(data, dict)
        or data.get("id") != tool_id
        or data.get("write_access") is not True
        or not isinstance(data.get("content"), str)
        or not isinstance(data.get("name"), str)
        or not isinstance(data.get("meta"), dict)
        or not isinstance(data.get("access_grants"), list)
    ):
        raise UpdateError(
            f"{tool_id}: Tool source is unavailable, lacks write access, or has an invalid shape."
        )
    return data


def plan_updates(client: httpx.Client, selections: list[tuple[str, str]]) -> list[PlannedUpdate]:
    if len({tool_id for _, tool_id in selections}) != len(selections):
        raise UpdateError("Each target tool ID may be selected only once.")
    # Preflight every source and target before any update. Never import/execute source locally.
    sources: list[tuple[str, str]] = []
    for adapter, tool_id in selections:
        try:
            source = TOOL_PATHS[adapter].read_text(encoding="utf-8")
            ast.parse(source)
        except (OSError, UnicodeError, SyntaxError):
            raise UpdateError(
                "Local tool source is unreadable or has invalid Python syntax."
            ) from None
        sources.append((tool_id, source))
    return [
        PlannedUpdate(tool_id, source, read_tool(client, tool_id)) for tool_id, source in sources
    ]


def apply_update(client: httpx.Client, plan: PlannedUpdate) -> None:
    # Catch edits since preflight. This is a safeguard, not an atomic conditional update.
    if read_tool(client, plan.tool_id) != plan.current:
        raise UpdateError(
            f"{plan.tool_id}: Tool changed since preflight; inspect it and run a new preview."
        )
    payload = {
        "id": plan.tool_id,
        "name": plan.current["name"],
        "content": plan.source,
        "meta": plan.current["meta"],
    }
    # Omitted access_grants preserves sharing; replaying grants can trigger permission filtering.
    # Valves/user Valves, ownership, and model assignments are not part of this update form.
    try:
        request_json(client, "POST", f"id/{quote(plan.tool_id, safe='')}/update", payload=payload)
        saved = read_tool(client, plan.tool_id)
        same_grants = sorted(json.dumps(grant, sort_keys=True) for grant in saved["access_grants"])
        old_grants = sorted(
            json.dumps(grant, sort_keys=True) for grant in plan.current["access_grants"]
        )
        if (
            saved["content"] != plan.source
            or saved["name"] != plan.current["name"]
            or same_grants != old_grants
            or any(
                saved["meta"].get(key) != plan.current["meta"].get(key)
                for key in ("description", "i18n")
            )
        ):
            raise UpdateError("Saved source or preserved metadata/sharing did not match.")
    except UpdateError as error:
        raise UpdateError(
            f"{plan.tool_id}: {error} Update may have been applied; "
            "inspect the tool before retrying."
        ) from None


def list_tools(client: httpx.Client) -> None:
    data = request_json(client, "GET", "")
    if not isinstance(data, list) or any(
        not isinstance(tool, dict)
        or not isinstance(tool.get("id"), str)
        or not isinstance(tool.get("name"), str)
        for tool in data
    ):
        raise UpdateError("Open WebUI returned an invalid tool listing.")
    for tool in data:
        # JSON escaping keeps names/IDs from injecting terminal control sequences.
        print(json.dumps({"id": tool["id"], "name": tool["name"]}, ensure_ascii=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tool",
        action="append",
        type=tool_selection,
        default=[],
        metavar="ADAPTER=TOOL_ID",
        help="Existing target ID; repeat to update test/production copies explicitly",
    )
    parser.add_argument("--list", action="store_true", help="List accessible tool IDs and names")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (the default)")
    mode.add_argument(
        "--apply", action="store_true", help="Save changed sources and verify read-back"
    )
    args = parser.parse_args(argv)
    if args.list and (args.tool or args.apply):
        parser.error("--list cannot be combined with --tool or --apply")
    if not args.list and not args.tool:
        parser.error("Select --list or at least one --tool ADAPTER=TOOL_ID")
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).disabled = True
    try:
        url = base_url(os.environ.get("OWUI_URL", ""))
        token = os.environ.get("OWUI_API_TOKEN", "")
        if not token or not token.isascii() or any(character.isspace() for character in token):
            raise UpdateError(
                "Set OWUI_API_TOKEN to an Open WebUI bearer token without its prefix."
            )
        try:
            timeout = float(os.environ.get("OWUI_TIMEOUT_SECONDS", "60"))
        except ValueError:
            raise UpdateError("OWUI_TIMEOUT_SECONDS must be positive and finite.") from None
        if not math.isfinite(timeout) or timeout <= 0:
            raise UpdateError("OWUI_TIMEOUT_SECONDS must be positive and finite.")
        with httpx.Client(
            base_url=url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            if args.list:
                list_tools(client)
                return 0
            plans = plan_updates(client, args.tool)
            for plan in plans:
                digest = hashlib.sha256(plan.source.encode()).hexdigest()[:12]
                if not plan.changed:
                    print(f"{plan.tool_id}: unchanged")
                elif args.apply:
                    apply_update(client, plan)
                    print(f"{plan.tool_id}: updated and verified (source sha256 {digest})")
                else:
                    print(f"{plan.tool_id}: would update (source sha256 {digest})")
            if not args.apply:
                print("Preview only; use --apply to save. No tool source was printed.")
        return 0
    except UpdateError as error:
        print(f"Tool update error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

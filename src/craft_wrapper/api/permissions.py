"""Fresh structural checks for the small set of supported write operations."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from craft_wrapper.api.auth import ensure_active
from craft_wrapper.api.schemas import validate_date
from craft_wrapper.craft.errors import CraftError
from craft_wrapper.craft.models import Block
from craft_wrapper.craft.transport import CraftTransport


def denied() -> None:
    raise HTTPException(403, "permission_denied")


def required_context(request: Request, field: str) -> str:
    value = request.query_params.get(field)
    if not value:
        raise RequestValidationError(
            [
                {
                    "type": "missing",
                    "loc": ("query", field),
                    "msg": f"{field} is required for scoped writes",
                    "input": None,
                }
            ]
        )
    return value


def structural_members(root: Block) -> dict[str, Block]:
    result: dict[str, Block] = {}
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type == "collection":
            continue
        if node.contentPreviewMd or node.itemsPreviewMd:
            raise CraftError(
                "craft_upstream_error", "Craft returned incomplete verification content."
            )
        if node.id in result:
            raise CraftError(
                "craft_upstream_error", "Craft returned ambiguous verification content."
            )
        result[node.id] = node
        pending.extend(node.content or [])
        # Never traverse collection items, relation properties, links, or Markdown.
    return result


async def verified_members(
    transport: CraftTransport, params: dict[str, str | int], expected_root: str | None
) -> tuple[Block, dict[str, Block]]:
    data = await transport.request("GET", "blocks", params=params)
    try:
        root = Block.model_validate(data)
    except ValidationError:
        raise CraftError(
            "craft_upstream_error", "Craft returned invalid verification content."
        ) from None
    if root.type != "page" or (expected_root is not None and root.id != expected_root):
        raise CraftError("craft_upstream_error", "Craft returned an unexpected verification root.")
    return root, structural_members(root)


async def authorize_write(request: Request) -> None:
    settings = request.app.state.settings
    profile_id = getattr(request.app.state, "profile_id", None)
    profile = settings.profiles.get(profile_id) if profile_id else None
    operation = request.scope["route"].operation_id
    adapter = operation.split("_")[1]
    client = getattr(request.app.state, f"{adapter}_client")
    ensure_active(request)

    if operation in {"craft_space_add_task", "craft_space_update_task", "craft_space_delete_task"}:
        document_id = (
            (await request.json())["documentId"]
            if request.method == "POST"
            else required_context(request, "documentId")
        )
        if profile is not None and document_id not in profile.targets("space").documentIds:
            denied()
        root, members = await verified_members(
            client.transport, {"id": document_id, "maxDepth": -1}, document_id
        )
        task_id = request.path_params.get("taskId")
        if task_id is not None:
            node = members.get(task_id)
            if node is None or node.type != "text" or node.id == root.id:
                denied()
            assert node is not None
            # A structural text node is not necessarily a task. Confirm through the
            # native task endpoint too; never trust Markdown checkboxes or linked IDs.
            tasks = await client.list_tasks({"scope": "document", "documentId": document_id})
            count = sum(task.id == task_id for task in tasks.items)
            if count > 1:
                raise CraftError(
                    "craft_upstream_error", "Craft returned ambiguous task membership."
                )
            if count == 0:
                denied()
            if request.method == "DELETE" and (node.content or node.items):
                denied()
        ensure_active(request)
        return

    collection_id = request.path_params.get("collectionId")
    if collection_id is not None:
        if profile is not None:
            if collection_id not in profile.targets(adapter).collectionIds:
                denied()
            # Relations can update reciprocal records outside this target. String-valued
            # input alone is not proof that a property is a simple, local field.
            body = await request.json() if request.method != "DELETE" else {}
            properties = body.get("properties", {})
            if properties:
                schema = await client.get_collection_schema(collection_id)
                kinds = {prop.key: prop.type for prop in schema.properties}
                simple = {
                    "text",
                    "number",
                    "boolean",
                    "date",
                    "url",
                    "email",
                    "phone",
                    "select",
                    "singleSelect",
                    "multiSelect",
                }
                if any(kinds.get(key) not in simple for key in properties):
                    denied()
        item_id = request.path_params.get("itemId")
        if item_id is not None and (
            profile is not None or operation.endswith("_delete_collection_item")
        ):
            items = await client.list_collection_items(collection_id, 0)
            if not any(item.id == item_id for item in items.items):
                denied()
        ensure_active(request)
        return

    block_id = request.path_params.get("blockId") or request.path_params.get("pageId")
    deletion = operation.endswith("_delete_block")
    if block_id is None or (profile is None and not deletion):
        ensure_active(request)
        return

    if adapter == "daily":
        date = validate_date(required_context(request, "date"))
        params = {"date": date, "maxDepth": -1}
        expected_root = None
    else:
        document_id = required_context(request, "documentId")
        if profile is not None and document_id not in profile.targets(adapter).documentIds:
            denied()
        params = {"id": document_id, "maxDepth": -1}
        expected_root = document_id
    root, members = await verified_members(client.transport, params, expected_root)
    node = members.get(block_id)
    if node is None:
        denied()
    assert node is not None
    if deletion:
        if node.id == root.id or node.type != "text" or node.content or node.items:
            denied()
    elif operation.endswith("_update_block_markdown") and node.type != "text":
        denied()
    elif operation.endswith("_insert_markdown") and node.type not in {"page", "text", "card"}:
        denied()
    ensure_active(request)

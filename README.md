# Craft OpenAPI wrapper

> [!CAUTION]
> This repo is purely vibe-coded. If you somehow find it, use at your own risk.

A small FastAPI service exposing 13 selected Craft **Space** operations as a generated OpenAPI 3.1 HTTP API. It is suitable for Open WebUI tool servers and other OpenAPI consumers.

Every data request shares one server-configured Craft connection. The wrapper has its own bearer token. The Craft client does not depend on FastAPI or Open WebUI.

## Local development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). The project defaults to Python 3.12; `uv` can install that interpreter if needed.

```sh
uv sync --locked --dev
cp .env.example .env
```

Edit `.env` and replace both placeholders with your Craft Space API URL and a separately generated wrapper token. `.env` is ignored by Git and excluded from Docker. No credentials are included in the schema.

```sh
uv run --locked uvicorn craft_wrapper.main:create_app --factory --reload --no-access-log
```

The default listener is `127.0.0.1:8000`. Generic Uvicorn access logging is disabled because it includes raw query strings; the wrapper logs request IDs, operation IDs, timings, status, and upstream error status instead.

- `GET /health`: public process liveness, `{"status":"ok"}`; does not call Craft or verify credentials.
- `GET /openapi.json`: public generated schema, exposing only enabled operations.
- `/docs`: local interactive Swagger documentation.

Example reads below call the configured **live** Craft connection. Export your wrapper token as `WRAPPER_API_TOKEN` in the shell; `.env` is read by the application, not automatically by your shell. Use a filtered list for large spaces.

```sh
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/openapi.json
curl -H "Authorization: Bearer $WRAPPER_API_TOKEN" \
  'http://127.0.0.1:8000/v1/space/documents?location=unsorted'
curl -H "Authorization: Bearer $WRAPPER_API_TOKEN" \
  'http://127.0.0.1:8000/v1/space/blocks/DOCUMENT_ID/markdown?maxDepth=1'
```

## Configuration

Environment variables override `.env`. Startup rejects missing credentials, placeholders, invalid URLs, non-positive/non-finite timeouts, and invalid allowlists without printing supplied values.

| Variable                        | Default / meaning                                                                                                                                                                     |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CRAFT_SPACE_BASE_URL`          | Required `https://connect.craft.do/links/SECRET/api/v1` URL; the link itself is a credential. Only this HTTPS host/path is accepted; redirects and ambient HTTP proxies are disabled. |
| `WRAPPER_API_TOKEN`             | Required independent, nonempty bearer token without whitespace.                                                                                                                       |
| `CRAFT_TIMEOUT_SECONDS`         | `30`; overall upstream deadline and read/write/pool phase limits.                                                                                                                     |
| `CRAFT_CONNECT_TIMEOUT_SECONDS` | `5`; upstream connection limit, also bounded by the overall deadline.                                                                                                                 |
| `WRAPPER_ENABLED_OPERATIONS`    | Omit to enable all 13 v1 operations. Otherwise a comma-separated list of exact operation IDs below. Empty/unknown entries are errors; duplicates are harmless.                        |
| `WRAPPER_PUBLIC_URL`            | Optional non-secret HTTP(S) origin, without a path/query/credentials; sets OpenAPI `servers`. Otherwise consumers use the schema origin.                                              |

For a read-only deployment, for example:

```dotenv
WRAPPER_ENABLED_OPERATIONS=craft_space_list_folders,craft_space_list_documents,craft_space_search_documents,craft_space_get_block,craft_space_read_markdown,craft_space_list_collections,craft_space_get_collection_schema,craft_space_list_collection_items
```

Selection takes effect at startup. Disabled operations are absent from both routing and OpenAPI and return `404`, including when another enabled method shares the same path. This is a deployment-level allowlist, not per-user authorization. Anyone with the wrapper token shares its configured Space access.

## Operations

All paths below start with `/v1/space`. Reads/updates return `200`; creates/insertion return `201`. All responses are JSON, including rendered Markdown.

| Method and path                                    | Stable operation ID                             | Behavior                                                                                                                                        |
| -------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /folders`                                     | `craft_space_list_folders`                      | Hierarchy and document counts, `{items:[...]}`.                                                                                                 |
| `GET /documents`                                   | `craft_space_list_documents`                    | IDs/titles, optional metadata, `{items:[...]}`. Filter by `location` or recursive `folderId`.                                                   |
| `GET /documents/search`                            | `craft_space_search_documents`                  | Required plain `query`; top 20 ranked content snippets. Optional one of `location`, `folderId`, `documentId`; `fetchBlocks=false`.              |
| `POST /documents`                                  | `craft_space_create_document`                   | One empty document: `{title, folderId? OR location?}`. Defaults to Unsorted; only Unsorted/Templates/folder destinations. Returns one document. |
| `GET /blocks/{blockId}`                            | `craft_space_get_block`                         | Structured root with nested blocks and IDs; `maxDepth=1`.                                                                                       |
| `GET /blocks/{blockId}/markdown`                   | `craft_space_read_markdown`                     | `{blockId,markdown}` using Craft rendering; `maxDepth=1`.                                                                                       |
| `POST /blocks/{pageId}/content`                    | `craft_space_insert_markdown`                   | `{markdown,position?:"start"\|"end"}`; default end; returns inserted `{items:[...]}`.                                                           |
| `PATCH /blocks/{blockId}`                          | `craft_space_update_block_markdown`             | `{markdown}` replaces one text block's Markdown; other fields preserved.                                                                        |
| `GET /collections`                                 | `craft_space_list_collections`                  | Existing collections, optionally filtered by one `documentId`.                                                                                  |
| `GET /collections/{collectionId}/schema`           | `craft_space_get_collection_schema`             | Native editable schema representation, with property keys/types/options.                                                                        |
| `GET /collections/{collectionId}/items`            | `craft_space_list_collection_items`             | All items; `maxDepth=0` defaults to properties without nested content.                                                                          |
| `POST /collections/{collectionId}/items`           | `craft_space_add_collection_item`               | One `{title,properties?:{key:"string"}}` item.                                                                                                  |
| `PATCH /collections/{collectionId}/items/{itemId}` | `craft_space_update_collection_item_properties` | Nonempty `{properties:{key:"string"}}`; omitted keys preserved.                                                                                 |

Document IDs equal root block IDs. There is no separate document-detail endpoint. Creation does not implicitly insert content: call insertion separately with the returned ID. Insertions may create multiple blocks.

Both document list and search support `createdDateGte/Lte`, `lastModifiedDateGte/Lte`, and `dailyNoteDateGte/Lte`. Dates are real `YYYY-MM-DD` calendar dates or `today`/`tomorrow`/`yesterday`; relative dates pass to Craft unchanged. Reversed absolute ranges and conflicting filters are rejected. Location values for reads are `unsorted`, `trash`, `templates`, and `daily_notes`. IDs are opaque nonempty strings; URL path dot segments `.`/`..` cannot be used as collection IDs.

Depth `0` reads only the requested root (or collection properties), positive values limit descendants, and `-1` requests all descendants. Finite depth is intentionally incomplete. Craft Markdown tags and link/scope markers are preserved.

The implemented lists have no documented pagination; the wrapper adds no cursors, limits, or totals. Search is relevance-limited, not exhaustive. Prefer filters and finite depth: incoming bodies are capped at **1 MiB**, upstream responses at **8 MiB**, including streamed data. Oversized results produce an error instead of truncation.

Collection reads allow dynamic JSON property values. Writes accept **strings only** and use keys/options discovered from the schema. Craft validates whether a string is suitable for that property's type. Relations, numeric/boolean/complex writes, null clearing, and item-title updates are unsupported. Stored views are not executed.

## Errors and write outcomes

Every error has an `error` object containing `code`, `message`, `requestId`, and optional `upstreamStatus`, `upstreamCode`, `retryAfterSeconds`, `outcomeUnknown`, or validation `details:[{field,message}]`. `X-Request-Id` matches the envelope.

| Status | Code / meaning                                                                                                                                                                             |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `400`  | `craft_rejected_request`: upstream 400/422 or an unsafe path identifier.                                                                                                                   |
| `401`  | `unauthorized`: missing/invalid **wrapper** token.                                                                                                                                         |
| `404`  | `craft_not_found` or `not_found`: missing Craft resource or wrapper route.                                                                                                                 |
| `409`  | `craft_conflict`.                                                                                                                                                                          |
| `413`  | `request_too_large`.                                                                                                                                                                       |
| `422`  | `validation_error`: invalid body/query; input values are not echoed.                                                                                                                       |
| `429`  | `craft_rate_limited`; valid upstream `Retry-After` is returned as seconds.                                                                                                                 |
| `500`  | `internal_error`; exception strings/tracebacks are not returned.                                                                                                                           |
| `502`  | `craft_access_error` for upstream 401/403; `craft_response_too_large`; or `craft_upstream_error` for other failures, redirects, invalid JSON/content types, or unexpected response shapes. |
| `503`  | `craft_unavailable`: upstream connection/network error.                                                                                                                                    |
| `504`  | `craft_timeout`.                                                                                                                                                                           |

There are **no automatic retries** on any operation. Craft budgets are shared across connections, clients, MCP, and public-IP users; a local limiter cannot reserve them. Safe upstream codes/messages are bounded and redacted; unrecognized bodies receive a fixed message. No raw upstream body or secret URL is returned in an error.

A write failure after submission can leave its outcome uncertain, including malformed success responses. Such errors set `outcomeUnknown=true`. Inspect the target before retrying; the wrapper provides neither transactions nor rollback. Conservatively, upstream write rejection responses also carry this flag because the docs provide no atomicity guarantee.

## Open WebUI

Register this as a **backend/global OpenAPI tool server**, using the wrapper origin and `/openapi.json`, with `Authorization: Bearer <WRAPPER_API_TOKEN>`. Restrict access to the intended user in Open WebUI. Enable selected tools in the chat. The server-side allowlist remains authoritative even if a consumer cached an older schema.

Use an address reachable from the Open WebUI backend. When both services are containers on the same Docker network, use the wrapper container's service name and port. A backend container's `localhost` is that container; on Docker Desktop, `host.docker.internal` can reach a host listener bound to a reachable interface. A listener bound to `127.0.0.1` is intended for host-local access. CORS is not enabled because this integration uses backend calls.

Open WebUI can import the OpenAPI 3.x schema and call ordinary HTTP operations. Tool results are complete responses, and this wrapper does not depend on streaming or interactive confirmation events. See [tool-server support](https://docs.openwebui.com/features/extensibility/plugin/tools/openapi-servers/) and [backend vs. browser integration](https://docs.openwebui.com/features/extensibility/plugin/tools/openapi-servers/open-webui/). The running Open WebUI installation still needs its own integration smoke check; the test suite does not claim to have verified its UI or model.

## Tests and checks

```sh
uv run --locked pytest -q
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

All tests use HTTPX MockTransport, fixture data, or an in-process ASGI app, with no live credentials or requests to Craft. They verify exact mappings for all 13 routes, discovery/editing and collection workflows, validation, auth, deadlines, size bounds, no retries, secret-safe errors/logs, allowlist enforcement, client shutdown, and OpenAPI validity.

Response fixtures are extracted from the **first response example** for implemented operations in `craft-docs/space-api-docs.md`. Singleton mutation tests narrow example batches; focused error/workflow tests use additional synthetic data. Fixture generation never edits the source docs.

Live Craft validation is optional and separate. In particular, secret-link-only authentication is an assumption from the documented URL pattern; no additional Craft auth headers or OAuth flow were documented or implemented.

## Docker

```sh
docker build -t craft-openapi-wrapper .
docker run --rm --env-file .env -p 127.0.0.1:8000:8000 craft-openapi-wrapper
```

The image uses Python 3.12 and the lockfile, installs no dev dependencies, runs as a non-root user, and checks `/health`. Supply secrets at runtime. For Open WebUI on the same Docker network, add `--network NETWORK --name craft-wrapper` and use `http://craft-wrapper:8000`; a published host port is unnecessary for container-to-container calls. TLS/remote hosting and Open WebUI deployment are outside this project.

### Compose and Portainer

`docker-compose.yml` builds from this repository and connects to an existing Docker network shared with the tool client. It publishes no host ports and contains no deployment-specific hostnames, paths, or network names. The Dockerfile supplies the non-root user and health check.

For a Portainer **Docker Standalone** environment, add a stack using **Git Repository**, select the repository and branch, and set **Compose path** to `docker-compose.yml`. Configure these stack environment variables:

- `CRAFT_SPACE_BASE_URL`: your secret Craft Space connection URL.
- `WRAPPER_API_TOKEN`: your independent wrapper bearer token.
- `WRAPPER_NETWORK`: the existing network also attached to Open WebUI or another tool client.
- Optionally, either timeout setting, `WRAPPER_ENABLED_OPERATIONS`, and `WRAPPER_PUBLIC_URL` as described above. Omit unused optional settings entirely; empty values are invalid.

Keep credentials in Portainer's configuration. No `.env` file or host directory is mounted into the container. Configure Open WebUI to use `http://craft-wrapper:8000/openapi.json` and the wrapper bearer token. Use one wrapper service with this name per shared network to avoid DNS alias collisions.

Portainer's [Git stack documentation](https://docs.portainer.io/user/docker/stacks/add) describes repository selection and stack variables. This build-based configuration targets Docker Standalone; Docker Swarm requires a separately built and published image.

For local Compose use, add `WRAPPER_NETWORK` to your ignored `.env`, ensure the network exists and the client is attached, then run:

```sh
docker compose up --build -d
docker compose ps
```

Rebuild when source changes. Building the image requires access to its base images and dependency registry; starting the container makes no Craft request until a data endpoint is called.

## Architecture and later APIs

`api/` owns HTTP models, validation, auth, error translation, and tool descriptions. `craft/transport.py` owns bounded asynchronous HTTP, decoding, deadlines, and sanitized failures. `craft/space/client.py` owns upstream query/body names, typed parsing, and singleton adaptation. `config.py` owns environment settings and operation selection.

All three local docs were compared before design. Space has 44 documented method/path pairs, Multi-Document 33, Daily Notes 36; 31 are shared. Overlap does not imply matching semantics:

- Space includes daily-note access and tasks; it is not disjoint from the Daily Notes API.
- Scoped connections filter links and relations; never fall back to a broader Space connection.
- Single-document search selectors are `blockId` (Space), `documentId` (Multi-Document), and `date` (Daily Notes).
- Collection discovery uses document filters, document include/exclude filters, or date ranges respectively.
- Daily Notes has date defaults/search results and narrower task scopes; Space task `all` is not the union of active/upcoming/inbox/logbook.
- Views are stored definitions, not executed queries. Reminders have conditional availability/ownership and cursor pagination; neither is exposed in v1.

Later add `craft/documents/` and `craft/daily/`, corresponding API routers, and independent server-side connection settings. Reuse transport/errors and proven common models; extract further helpers only when a second adapter proves matching contracts. Do not introduce a universal Craft interface or capability framework. Existing Space operation IDs stay stable.

V1 deliberately excludes deletion/movement, folder writes, collection creation/schema mutation/views, tasks, comments, reminders, uploads, and whiteboards. Other documented gaps remain explicit: examples use inconsistent identifier terminology and collection-type representations; array query serialization and regex claims are ambiguous; list pagination and mutation atomicity are unspecified. The wrapper follows documented example field names, accepts single-value filters, preserves read type strings, and omits those uncertain capabilities.

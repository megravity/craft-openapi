# Craft OpenAPI wrapper

> [!CAUTION]
> This repo is purely vibe-coded. If you somehow find it, use at your own risk.

A small FastAPI service exposing 13 selected [Craft](https://www.craft.do/) **Space** operations, 11 **Multi-Document** operations, and 17 **Daily Notes** operations as a generated OpenAPI 3.1 HTTP API. It is suitable for Open WebUI tool servers and other OpenAPI consumers.

Configure any combination of Space, Multi-Document, and Daily Notes. Each adapter uses its own server-configured Craft connection; it never falls back to another connection. The wrapper has one shared bearer token. The Craft client does not depend on FastAPI or Open WebUI.

For project context and agent handoff, start with [PROJECT.md](PROJECT.md). Contributor instructions are in [AGENTS.md](AGENTS.md).

## Contents

- [Installation](#installation): [Python](#python--local-development), [Docker Compose](#docker-compose), [Portainer](#portainer-with-a-cloned-repository-and-local-image), [Docker image](#docker-image-without-compose)
- [Updating](#updating)
- [Versioning](#versioning)
- [Configuration](#configuration)
- [Operations](#operations): [Space](#space), [Multi-Document](#multi-document), [Daily Notes](#daily-notes)
- [Errors and write outcomes](#errors-and-write-outcomes)
- [Open WebUI](#open-webui): [Python tool](#workspace-python-tool), [OpenAPI server](#openapi-tool-server)
- [Tests and checks](#tests-and-checks)
- [Architecture](#architecture)
- [Roadmap](#roadmap)

---

## Installation

Clone the repository and run the commands below from its root. Choose Python, Docker Compose, or Portainer according to how you want to manage the process. Supply connection secrets and the network name in your deployment configuration.

### Python / local development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). The project defaults to Python 3.12; `uv` can install that interpreter if needed.

```sh
uv sync --locked --dev
cp .env.example .env
```

Edit `.env` with at least one Craft connection URL and a separately generated wrapper token. Use `CRAFT_SPACE_BASE_URL` for Space, `CRAFT_DOCUMENTS_BASE_URL` for Multi-Document, and `CRAFT_DAILY_BASE_URL` for Daily Notes; configure any one, pair, or all three. Remove unused connection settings entirely, including their placeholder values; blank supplied URLs are invalid. `.env` is ignored by Git and excluded from Docker. No credentials are included in the schema.

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

### Docker Compose

Requires Docker Engine and the Docker Compose plugin. Copy `.env.example` to `.env` if you have not already done so, configure at least one connection URL and the wrapper token, and set `WRAPPER_NETWORK` to an **existing Docker network also attached to your tool client**. You can find that network in the client's container configuration. Omit unused optional variables instead of setting them to empty strings.

```sh
cp .env.example .env  # First-time setup only; do not overwrite an existing .env.
# Edit .env: credentials and WRAPPER_NETWORK=YOUR_SHARED_NETWORK.
docker compose up --build -d
docker compose ps
docker compose logs --tail=50 craft-wrapper
```

`docker-compose.yml` builds from the clone and tags the image `craft-openapi-wrapper:local`. Both Compose files set the container name to `craft-wrapper`, rather than a generated stack/service/instance name. This name must be unique on the Docker host; change it if deploying another instance. It publishes no host ports. A client on the shared network reaches `http://craft-wrapper:8000`; the schema is `/openapi.json`. Use one service with this name per shared network to avoid DNS alias collisions. Host-browser requests to `localhost:8000` do not reach this deployment.

### Portainer with a cloned repository and local image

This method targets **Docker Standalone**. Clone the repository on the Docker host managed by Portainer, and build there:

```sh
./scripts/build-image.sh
```

The script builds `craft-openapi-wrapper:local` using the repository as its context, even when invoked from another directory. It uses the Docker builder's default platform, so build on the intended host. You can supply a different tag with `./scripts/build-image.sh IMAGE_TAG`; also change the image in the Portainer Compose file if you do.

In Portainer:

1. Select the same Docker environment where you built the image.
2. Open **Stacks → Add stack → Web editor**, and paste **`docker-compose.portainer.yml`** from the clone. This file uses the local image with `pull_policy: never`; it contains no build context or host mounts.
3. Add stack variables `WRAPPER_API_TOKEN` and `WRAPPER_NETWORK`, plus at least one of `CRAFT_SPACE_BASE_URL`, `CRAFT_DOCUMENTS_BASE_URL`, or `CRAFT_DAILY_BASE_URL`. Any combination is supported; omit unused connection variables entirely. The network must already exist and also be attached to the tool client. Optionally set `WRAPPER_ENABLED_OPERATIONS` to `read_only`, `full`, or an explicit operation-ID list. You can also add timeout settings or `WRAPPER_PUBLIC_URL`; omit unused optional settings entirely.
4. Keep any **Re-pull image** option disabled and deploy. Check the container's health and logs.

The clone's `.env` is not automatically read by Portainer. Enter variables in Portainer or use its **Load variables from .env file** feature. No credential file is mounted into the container. See [Portainer's stack and environment-variable documentation](https://docs.portainer.io/user/docker/stacks/add).

The ordinary `docker-compose.yml` is for builds from the local clone. Pasting it into Portainer's editor does not give Portainer access to that clone: `build.context: .` refers to the stack's own working directory. Use the prebuilt-image file above for this installation method.

#### Optional stack update after building

On **Portainer Business Edition**, enable **Create a stack webhook** in the stack's **Editor** and copy its URL. Stack webhooks are available on non-Edge environments. The build host must reach Portainer and build on the Docker environment where the stack runs. See [Portainer's stack webhook documentation](https://docs.portainer.io/user/docker/stacks/webhooks).

Store the copied URL in the clone's ignored `.portainer-webhook` file:

```sh
cp .portainer-webhook.example .portainer-webhook
chmod 600 .portainer-webhook
# Edit .portainer-webhook: replace its entire line with the copied webhook URL.
./scripts/build-image.sh
```

Use the bare URL without query parameters. It grants deployment access; do not commit or share it. The script appends `pullimage=false` so Portainer uses the locally rebuilt image rather than pulling from a registry. Keep `pull_policy: never` in the stack. The webhook redeploys Portainer's saved stack definition; changes to the clone's Compose file still need to be copied into the stack editor.

Alternatively, export `PORTAINER_WEBHOOK_URL` in the build shell. It overrides the file; setting it to an empty string disables the webhook for that invocation. The build script does not load `.env` or require this setting in the application container. With neither setting, the script only builds, as before.

The optional hook requires `curl`. Configuration is checked before building. After a successful build, the script sends one POST with a 10-second connection timeout and a 60-second overall timeout. It does not follow redirects, retry, or print the secret URL or response body. A failed build never triggers the hook. A failed/rejected webhook makes the script exit nonzero, although the image has already been built. Check stack state before retrying an uncertain request.

Portainer returns before deployment completes. A successful script reports that the request was **accepted**; check the stack's deployment status, container image, health, and logs to confirm the update finished. Removing `.portainer-webhook` disables the saved hook. Community Edition installations can continue using the manual update procedure below.

### Docker image without Compose

For a host-local listener:

```sh
./scripts/build-image.sh
docker run --rm --env-file .env -p 127.0.0.1:8000:8000 craft-openapi-wrapper:local
```

The Dockerfile uses Python 3.12 and the lockfile, installs no dev dependencies, runs as a non-root user, and checks `/health`. `.dockerignore` excludes credentials, docs, scripts, and local caches from the build context. Supply credentials at runtime. Startup and health make no Craft request. TLS/remote hosting and deployment of the tool client are outside this project.

### Updating

Pull changes from your clone's configured remote with `git pull --ff-only`. Keep your existing `.env` or Portainer variables; review `.env.example` for new settings without copying it over your credentials.

For Python, run `uv sync --locked --dev` and restart Uvicorn.

For local Compose, rebuild and apply the changes:

```sh
git pull --ff-only
docker compose up --build -d
docker compose ps
```

For Portainer, rebuild on the same Docker host:

```sh
git pull --ff-only
./scripts/build-image.sh
```

With the optional webhook configured, the build script automatically requests a stack update after building. Check Portainer to confirm deployment completed. If `docker-compose.portainer.yml` changed, apply those changes to the stack editor as well; the webhook does not read your clone.

Without the webhook, open the stack in Portainer, copy any changes from `docker-compose.portainer.yml` into its editor, and **Update the stack** with re-pulling disabled. Ensure the container is recreated from the rebuilt image; if it is retained, use the container's **Recreate** action with pulling disabled. Restarting an existing container alone does not apply a rebuilt image. Check health and logs after recreation. A locally built image is not updated by Portainer's registry-pull or GitOps settings.

For a standalone `docker run` container, rebuild with the script, stop the old container, and run the replacement with the same environment and port/network settings.

---

## Versioning

The current release version is **0.3.0**, adding Multi-Document support alongside Space. Releases use Git tags such as `v0.3.0` and are recorded in [CHANGELOG.md](CHANGELOG.md). Minor releases add capabilities; patch releases fix defects. While the project is below 1.0, any breaking changes must be called out in the changelog. The `/v1/space`, `/v1/documents`, and `/v1/daily` prefixes identify the HTTP contract independently of the project release number.

The working tree also includes **unreleased Daily Notes support**; the next capability release is expected to be **0.4.0**. Release metadata remains at 0.3.0 until release preparation.

OpenAPI `info.version` comes from the installed package version. All three standalone Open WebUI tools include the release version in the metadata header. Docker images carry `org.opencontainers.image.version`; `craft-openapi-wrapper:local` remains the mutable tag used by the Portainer stack. Check the running container's release with:

```sh
docker inspect craft-wrapper --format '{{ index .Config.Labels "org.opencontainers.image.version" }}'
```

For an exact source release, check out its Git tag before building. Updating the wrapper image and updating the installed Open WebUI Python tool remain separate steps.

### Prepare a release locally

Keep reviewed changes under `## Unreleased` in [CHANGELOG.md](CHANGELOG.md). Choose the next version explicitly, then run from the repository root:

```sh
./scripts/prepare-release.sh 0.4.0 --dry-run
./scripts/prepare-release.sh 0.4.0
```

`0.4.0` is an example, not an automatic version choice. The command moves those notes into a dated release entry, leaves an empty `Unreleased` section, and updates `pyproject.toml`, the Docker label, all three tool headers, and current-version references in README/PROJECT. It runs `uv lock` and `uv sync --locked --dev` to align the lockfile and installed package metadata. The default date is the local calendar date; override it with `--date YYYY-MM-DD`.

The dry run validates the inputs and lists affected files without changing them or running lock/sync. Empty notes, inconsistent current metadata, an existing local release tag, or a non-increasing version fail preparation. If lock/sync or final validation fails, release files are restored; run `uv sync --locked --dev` to reconcile the environment.

Review `git diff` and run [the project checks](#tests-and-checks) before committing and tagging. The command never commits, tags, pushes, builds images, or deploys. Ordinary commits can continue without preparing a release.

### GitHub releases

[The release workflow](.github/workflows/release.yml) runs on pushed `v*` tags and accepts only `vMAJOR.MINOR.PATCH`, such as `v0.3.0`. Ordinary branch pushes do not publish releases. It verifies the **tagged** package, lockfile, Docker label, and tool versions present in that tag, then publishes a GitHub release using that tag's matching dated `CHANGELOG.md` entry. Missing/mismatched metadata or empty notes fail the run. Existing releases are left unchanged when rerun.

After preparing a release commit and running the checks:

```sh
git tag -a v0.3.0 -m "Release 0.3.0"  # Example: only after setting version 0.3.0.
git push origin main
git push origin v0.3.0
```

Commit and push the workflow before relying on automatic publishing. For an older tag such as `v0.2.0`, push the tag if needed, then select **Actions → Release → Run workflow**, use the default branch, and enter the existing tag. This manual path reads release metadata/notes from the tag without moving it. Manual workflows must exist on the default branch; see [GitHub's workflow trigger documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch).

The workflow uses GitHub's provided token with `contents: write`; no personal access token or Craft/Portainer credentials are required. Actions must be enabled and repository policy must permit this permission. It creates a published release with notes, using [`gh release create --verify-tag`](https://cli.github.com/manual/gh_release_create). It does not bump versions, create tags, run the application tests, publish Docker images/packages, or trigger deployments. Run the release checks before tagging. Prerelease suffixes are not supported by this initial workflow.

---

## Configuration

Environment variables override `.env`. Startup rejects missing credentials, placeholders, invalid URLs, non-positive/non-finite timeouts, and invalid allowlists without printing supplied values.

| Variable                        | Default / meaning                                                                                                                                                                     |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CRAFT_SPACE_BASE_URL`          | Optional Space connection: `https://connect.craft.do/links/SECRET/api/v1` URL; the link itself is a credential. Only this HTTPS host/path is accepted; redirects and ambient HTTP proxies are disabled. |
| `CRAFT_DOCUMENTS_BASE_URL`      | Optional Multi-Document secret-link URL with the same validation. At least one connection is required; omit unused connections. |
| `CRAFT_DAILY_BASE_URL` | Optional Daily Notes secret-link URL with the same validation. Omit to disable this adapter. |
| `WRAPPER_API_TOKEN`             | Required independent, nonempty bearer token without whitespace.                                                                                                                       |
| `CRAFT_TIMEOUT_SECONDS`         | `30`; overall upstream deadline and read/write/pool phase limits.                                                                                                                     |
| `CRAFT_CONNECT_TIMEOUT_SECONDS` | `5`; upstream connection limit, also bounded by the overall deadline.                                                                                                                 |
| `WRAPPER_ENABLED_OPERATIONS`    | `full` or omitted: all operations on configured adapters (13 Space, 11 Multi-Document, 17 Daily Notes; 41 combined). `read_only`: their reads (8 Space, 7 Multi-Document, 9 Daily Notes; 24 combined). Also accepts a comma-separated list of exact operation IDs below. Empty/unknown entries and IDs for an unconfigured adapter are errors; duplicates are harmless. |
| `WRAPPER_PUBLIC_URL`            | Optional non-secret HTTP(S) origin, without a path/query/credentials; sets OpenAPI `servers`. Otherwise consumers use the schema origin.                                              |

Use a preset for common configurations:

```dotenv
WRAPPER_ENABLED_OPERATIONS=read_only
```

`read_only` includes discovery, content search, structured blocks, Markdown, collection schemas, and collection items for the configured adapters. Space also includes folder discovery; Daily Notes includes native task listing. All mutations, including task deletion, are disabled. `full` enables all implemented v1 operations, including writes; it does not enable deferred Craft capabilities.

Preset names are case-insensitive; `Read Only` and `read-only` also work. Set one preset or an explicit list, rather than mixing presets and operation IDs. Explicit operation IDs remain case-sensitive. For a narrower selection:

```dotenv
WRAPPER_ENABLED_OPERATIONS=craft_space_list_documents,craft_space_get_block,craft_space_read_markdown
```

Selection takes effect at startup. Recreate the Docker container after changing its environment, or restart the Python process. Disabled operations are absent from both routing and OpenAPI and return `404`, including when another enabled method shares the same path. This is a deployment-level allowlist, not per-user authorization. Anyone with the wrapper token can call enabled operations on every configured adapter. The Multi-Document prefix is not a separate permission boundary for that token when Space is also enabled; use an instance configured only with the intended restricted connection. The same shared-token rule applies to Daily Notes.

---

## Operations

Reads/updates return `200`; creates/insertion return `201`. All responses are JSON, including rendered Markdown.

### Space

All paths below start with `/v1/space`.

| Method and path                                    | Stable operation ID                             | Behavior                                                                                                                                        |
| -------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /folders`                                     | `craft_space_list_folders`                      | Hierarchy and document counts, `{items:[...]}`.                                                                                                 |
| `GET /documents`                                   | `craft_space_list_documents`                    | IDs/titles, optional metadata, `{items:[...]}`. Filter by `location` or `folderId` (direct documents only).                                     |
| `GET /documents/search`                            | `craft_space_search_documents`                  | Required plain `query`; ranked content snippets, including substring matches. Optional one of `location`, `folderId`, `documentId`; `fetchBlocks=false`. |
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

Use the `id` returned by document discovery as the API root block ID, or `documentId` returned by content search. `clickableLink` is a navigation link: its embedded `documentId` can differ from the API ID and return `404` if used in an API request. Do not extract IDs from it for content reads or writes. A collection block's `id` can also be its collection ID; block and collection IDs are not disjoint namespaces. There is no separate document-detail endpoint. Creation does not implicitly insert content: call insertion separately with the returned ID. Insertions may create multiple blocks.

Both document list and search support `createdDateGte/Lte`, `lastModifiedDateGte/Lte`, and `dailyNoteDateGte/Lte`. Dates are real `YYYY-MM-DD` calendar dates or `today`/`tomorrow`/`yesterday`; relative dates pass to Craft unchanged. Reversed absolute ranges and conflicting filters are rejected. Location values for reads are `unsorted`, `trash`, `templates`, and `daily_notes`. IDs are opaque nonempty strings; URL path dot segments `.`/`..` cannot be used as collection IDs.

Document **listing** requires `location=daily_notes` with either daily-note date bound; missing or incompatible scopes return `422`. Live Craft listing otherwise returned an empty result despite matching daily notes. Document **search** accepts these date bounds without requiring that location. Listing by `folderId` returns direct documents only in observed Craft responses, contrary to the upstream documentation; query each descendant folder separately when needed. Folder-scoped search includes descendants. List ordering is unspecified; sort returned data client-side, requesting metadata when sorting by creation or modification dates.

Search terms can match inside words: `end` can match `frontend`, for example. Responses can contain multiple hits for one document. The upstream documentation describes a top-20 limit, but live responses exceeded 20 hits and 20 distinct documents; the wrapper preserves the returned results and makes no fixed result-count or completeness guarantee.

Depth `0` reads only the requested root (or collection properties), positive values limit descendants, and `-1` requests all descendants. Finite depth is intentionally incomplete. Structured block reads preserve `contentPreviewMd` and `itemsPreviewMd` when Craft supplies them. Collection blocks can include rows under `items`, with each row's properties and nested `content`; use `list_collection_items` to read rows directly. Craft Markdown tags and link/scope markers are preserved.

The implemented lists have no documented pagination; the wrapper adds no cursors, limits, or totals. Search is relevance-limited, not exhaustive. Prefer filters and finite depth: incoming bodies are capped at **1 MiB**, upstream responses at **8 MiB**, including streamed data. Oversized results produce an error instead of truncation.

Collection reads allow dynamic JSON property values. Untitled rows can omit `title`, and `properties` can be empty or omitted. Writes accept **strings only** and use keys/options discovered from the schema. Craft validates whether a string is suitable for that property's type. Relations, numeric/boolean/complex writes, null clearing, and item-title updates are unsupported. Stored views are not executed. A populated Date property was live-verified as a `YYYY-MM-DD` string, preserved by the wrapper. Existing-row Date updates using this string format were also live-verified with read-back and restoration of the original value. Other date representations remain unverified.

Schema option lists accept the documented string labels and observed `{name,color?}` objects, preserving the supplied representation. Title-property metadata (`contentPropDetails`) is optional because Craft may omit it. Property type strings such as the documented `select` and observed `singleSelect` are preserved without normalization. Single-select item values can be strings; multi-select values can be arrays. Both read shapes are preserved, while array writes remain unsupported. Existing row values are not a substitute for a schema: they do not reveal unused options or the full property contract.

### Multi-Document

All paths below start with `/v1/documents`. These routes use only `CRAFT_DOCUMENTS_BASE_URL`, preserving the documents exposed by that connection. Craft filters links and relations; returned `invalid:out_of_scope` markers are preserved. Neither include/exclude filters nor resource IDs expand access.

| Method and path | Stable operation ID |
|---|---|
| `GET /documents` | `craft_documents_list_documents` |
| `GET /documents/search` | `craft_documents_search_documents` |
| `GET /blocks/{blockId}` | `craft_documents_get_block` |
| `GET /blocks/{blockId}/markdown` | `craft_documents_read_markdown` |
| `POST /blocks/{pageId}/content` | `craft_documents_insert_markdown` |
| `PATCH /blocks/{blockId}` | `craft_documents_update_block_markdown` |
| `GET /collections` | `craft_documents_list_collections` |
| `GET /collections/{collectionId}/schema` | `craft_documents_get_collection_schema` |
| `GET /collections/{collectionId}/items` | `craft_documents_list_collection_items` |
| `POST /collections/{collectionId}/items` | `craft_documents_add_collection_item` |
| `PATCH /collections/{collectionId}/items/{itemId}` | `craft_documents_update_collection_item_properties` |

Document listing accepts only `fetchMetadata=false`; entries include `id`, `title`, and `isDeleted`. Deleted entries remain visible. Optional metadata includes `createdAt`, `lastModifiedAt`, and `clickableLink`. Use `id` for API reads, not an ID extracted from the navigation link.

Search accepts required `query`, optional `documentId`, `documentFilterMode=include|exclude`, and `fetchBlocks=false`. Collection discovery accepts optional `documentId` and the same filter mode. Supplying an ID defaults to include; supplying a mode without an ID returns `422`. A singular public `documentId` maps to upstream `documentIds`. Search is relevance-limited (Craft documents top 20), not an exhaustive inventory; the wrapper preserves returned results without truncating them or inventing pagination.

Space-specific location, folder, and date filters are rejected. Multi-Document has no wrapper folder or document-creation route. Block depth defaults to `1`, collection-item depth to `0`, and `-1` requests all descendants. Markdown insertion and block updates use the same request bodies as Space. Collection writes remain singleton, string-valued operations; complex reads and scope markers are preserved.

For a **Multi-Document-only** instance, remove `CRAFT_SPACE_BASE_URL` and set:

```dotenv
CRAFT_DOCUMENTS_BASE_URL=https://connect.craft.do/links/REPLACE_ME/api/v1
WRAPPER_API_TOKEN=REPLACE_ME
WRAPPER_ENABLED_OPERATIONS=read_only
```

Replace both placeholders. For combined access, configure both connection URLs instead. Example authenticated reads:

```sh
curl -H "Authorization: Bearer $WRAPPER_API_TOKEN" \
  'http://127.0.0.1:8000/v1/documents/documents?fetchMetadata=true'
curl -H "Authorization: Bearer $WRAPPER_API_TOKEN" \
  'http://127.0.0.1:8000/v1/documents/documents/search?query=example&documentId=DOCUMENT_ID&documentFilterMode=exclude'
```

### Daily Notes

All paths below start with `/v1/daily` and use only `CRAFT_DAILY_BASE_URL`. Craft enforces scope across daily notes, the task inbox, and task logbook; out-of-scope links/relations remain filtered. Date-based calls pass `today`, `tomorrow`, and `yesterday` unchanged to Craft; the wrapper never applies its host timezone. Calendar dates must be valid `YYYY-MM-DD`; reversed absolute ranges are rejected.

| Method/path | Stable operation ID | Behavior |
|---|---|---|
| `GET /notes` | `craft_daily_get_note` | Structured root by `date=today`; `maxDepth=1`. Returns editable IDs and hierarchy. |
| `GET /notes/markdown` | `craft_daily_read_note_markdown` | Rendered note with the same date/depth defaults; JSON `{date, markdown}` retains the requested selector. |
| `POST /notes/content` | `craft_daily_insert_note_markdown` | Insert `{markdown, position}` by query `date=today`; position defaults to `end`, or use `start`. |
| `GET /blocks/{blockId}` | `craft_daily_get_block` | Structured content by opaque ID; `maxDepth=1`. |
| `GET /blocks/{blockId}/markdown` | `craft_daily_read_markdown` | Rendered content by ID; JSON `{blockId, markdown}`, `maxDepth=1`. |
| `POST /blocks/{pageId}/content` | `craft_daily_insert_markdown` | Insert `{markdown, position}` into a specific page. |
| `PATCH /blocks/{blockId}` | `craft_daily_update_block_markdown` | Update one text block with `{markdown}`; empty Markdown is allowed. |
| `GET /notes/search` | `craft_daily_search_notes` | Required plain `query`; optional `startDate`, `endDate`, `fetchBlocks=false`. |
| `GET /collections` | `craft_daily_list_collections` | Discover collections with optional `startDate`/`endDate`; summaries identify `dailyNoteDate`. |
| `GET /collections/{collectionId}/schema` | `craft_daily_get_collection_schema` | Inspect property keys/types/options before writes. |
| `GET /collections/{collectionId}/items` | `craft_daily_list_collection_items` | Read rows with dynamic JSON properties; `maxDepth=0`. |
| `POST /collections/{collectionId}/items` | `craft_daily_add_collection_item` | Add one row with `{title, properties?}`; property values must be strings. |
| `PATCH /collections/{collectionId}/items/{itemId}` | `craft_daily_update_collection_item_properties` | Update a nonempty string-valued `{properties}` mapping. |
| `GET /tasks` | `craft_daily_list_tasks` | Required `scope=active\|upcoming\|inbox\|logbook`. |
| `POST /tasks` | `craft_daily_add_task` | Create one native task, defaulting to the inbox. |
| `PATCH /tasks/{taskId}` | `craft_daily_update_task` | Update selected content, state, schedule, or deadline fields. |
| `DELETE /tasks/{taskId}` | `craft_daily_delete_task` | Delete one native task; return `{id}` with status `200`. |

Date reads send only upstream `date`; ID reads send only `id`. Use the root ID from `get_note` and returned child IDs for exact page/block targeting. Date-based insertion chooses Craft's most recently updated note when duplicate daily notes share a date; use a specific `pageId` to target another copy. Finite depth is deliberately incomplete; `-1` requests all descendants. Missing notes return Craft's error without a wrapper-generated document or implicit read-side insertion.

Daily-note search returns relevance-ranked snippets with `dailyNoteDate`, `markdown`, `blockIds`, and optional matched `blocks`; Craft documents a top-20 limit. This is not a daily-note inventory. No document-listing endpoint, regex, or pagination is exposed; the upstream reference's discovery hint does not establish a `/documents` contract for this connection. Space-specific folder/location/document filters are rejected.

Task creation accepts `markdown`, `target=inbox|daily_note` (default `inbox`), optional `date`, `scheduleDate`, and `deadlineDate`. `date` is valid only for `daily_note` and defaults to `today` for that target. For example:

```json
{"markdown":"Review example","target":"daily_note","date":"today","scheduleDate":"tomorrow"}
```

Task updates accept at least one of `markdown`, `state=todo|done|canceled`, `scheduleDate`, or `deadlineDate`. Omitted fields are preserved; explicit nulls, date clearing, nested `taskInfo` write inputs, and task movement are rejected. The client translates the flat write fields into Craft's `taskInfo` structure. Responses can be partial, so only `id` is required; returned state strings are preserved.

`active` and `upcoming` classify open tasks by schedule date when present, otherwise deadline date. `inbox` selects the task inbox; `logbook` selects completed/canceled tasks. Marking tasks done/canceled moves them to Craft's logbook. Space-only `all`/`document` scopes are rejected. Native tasks differ from collection rows, and task dates do not create timed reminders. Deletion removes a task rather than completing it; no rollback is promised. Lost or malformed write/deletion responses report `outcomeUnknown`; inspect state before repeating.

Example reads for a Daily Notes connection:

```sh
curl -H "Authorization: Bearer $WRAPPER_API_TOKEN" \
  'http://127.0.0.1:8000/v1/daily/notes?date=today&maxDepth=1'
curl -H "Authorization: Bearer $WRAPPER_API_TOKEN" \
  'http://127.0.0.1:8000/v1/daily/tasks?scope=inbox'
```

---

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

Distinguish a `502` with an upstream failure and retry guidance from an unexpected response shape after a successful Craft response. A schema parsing mismatch is deterministic until the model or upstream shape changes; backoff does not repair it. For transient reads, callers can honor `retryAfterSeconds` before retrying. The wrapper does not assume every upstream `502` is throttling or convert it into `429`.

A write failure after submission can leave its outcome uncertain, including malformed success responses. Such errors set `outcomeUnknown=true`. Inspect the target before retrying; the wrapper provides neither transactions nor rollback. Conservatively, upstream write rejection responses also carry this flag because the docs provide no atomicity guarantee.

---

## Open WebUI

### Workspace Python tool

Choose the standalone [Space tool](integrations/openwebui/craft_space_tool.py) (13 operations), [Multi-Document tool](integrations/openwebui/craft_documents_tool.py) (11), or [Daily Notes tool](integrations/openwebui/craft_daily_tool.py) (17). Each explicitly calls this HTTP wrapper; none connects directly to Craft or requires the wrapper package inside Open WebUI. Their structures follow Open WebUI's [tool development conventions](https://docs.openwebui.com/features/extensibility/plugin/tools/development/).

1. Open **Workspace → Tools** in Open WebUI and create a tool. Paste the entire contents of the selected tool file into the editor and save it. The metadata declares its HTTPX dependency; Pydantic is supplied by Open WebUI.
2. Open the tool's **Valves** settings and configure the values below. The token field uses Open WebUI's [password input convention](https://docs.openwebui.com/features/extensibility/plugin/development/valves/); masking the input does not itself encrypt stored values. Restrict tool access to the intended users.
3. Enable the tool in a chat with a model that supports tool calling. Native function calling is recommended. Ask Space to list folders, Multi-Document to list documents, or Daily Notes to read today’s note. Successful reads return `200`; a missing daily note can return Craft’s `404`.

| Valve | Value |
|---|---|
| `WRAPPER_URL` | Wrapper origin reachable from Open WebUI, such as `http://craft-wrapper:8000` on a shared Docker network. No adapter path suffix such as `/v1/space`, `/v1/documents`, or `/v1/daily`. |
| `WRAPPER_API_TOKEN` | The wrapper's `WRAPPER_API_TOKEN`, without `Bearer `. Never use the Craft connection URL here. |
| `TIMEOUT_SECONDS` | Default `45`, covering the wrapper's default 30-second upstream deadline plus network overhead. |

The Space source was renamed from `craft_wrapper_tool.py` to `craft_space_tool.py`; existing installed tools keep working without changing their functions or Valves. Use the renamed source for subsequent installation or updates.

Each tool has named functions matching the wrapper's operation IDs. Query arguments go inside `parameters`; write payloads go inside `body`. IDs remain separate arguments. For example:

```json
{
  "parameters": {
    "query": "example",
    "documentId": "example-document",
    "fetchBlocks": true
  }
}
```

These are arguments for `craft_space_search_documents`. A block update uses `craft_space_update_block_markdown` with `{"blockId":"example-text-block","body":{"markdown":"Updated text"}}`. Collection writes accept string-valued properties only; the wrapper validates dates, depths, scopes, and payloads.

Nested query/body keys are forwarded without silently removing unknown fields. For instance, `craft_space_list_documents` with `{"parameters":{"documentId":"example-document"}}` reaches the wrapper and returns `422`, because that listing filter is unsupported. Open WebUI can still discard unsupported **top-level** arguments; put query fields inside `parameters` as documented.

Each result contains `request` (method, path, serialized query), `statusCode`, `requestId`, and the unchanged JSON `response`. This distinguishes a wrapper rejection from a tool connection/decoding failure. Authentication headers and write bodies are not included in request evidence. Wrapper error codes, retry guidance, and uncertain-write flags are preserved. The tool does not follow redirects or retry requests; failed writes after submission are marked uncertain. Results exceeding 9 MiB are rejected rather than truncated.

Each Python tool keeps its static function list: 13 for Space, 11 for Multi-Document. To use Multi-Document search, call `craft_documents_search_documents` with `parameters` containing `query` and optionally `documentId`, `documentFilterMode`, and `fetchBlocks`. Install each tool separately if both adapters are needed. `WRAPPER_ENABLED_OPERATIONS` still enforces permissions on the server; disabled operations return `404`. Use `read_only` on the wrapper to prohibit writes. Choose either this tool or the OpenAPI registration below for a chat to avoid duplicate operations.

To update the installed tool after pulling repository changes, replace its code in the Open WebUI editor with the current file and save it. Check its Valves settings afterward. Rebuilding the wrapper image does not update the separately installed Open WebUI tool. Automated tests cover mocked HTTP calls and calls through an in-process wrapper; the installed Open WebUI UI/model still needs the discovery smoke check above.

### OpenAPI tool server

Register this as a **backend/global OpenAPI tool server**, using the wrapper origin and `/openapi.json`, with `Authorization: Bearer <WRAPPER_API_TOKEN>`. Restrict access to the intended user in Open WebUI. Enable selected tools in the chat. The server-side allowlist remains authoritative even if a consumer cached an older schema.

Use an address reachable from the Open WebUI backend. When both services are containers on the same Docker network, use the wrapper container's service name and port. A backend container's `localhost` is that container; on Docker Desktop, `host.docker.internal` can reach a host listener bound to a reachable interface. A listener bound to `127.0.0.1` is intended for host-local access. CORS is not enabled because this integration uses backend calls.

Open WebUI can import the OpenAPI 3.x schema and call ordinary HTTP operations. Tool results are complete responses, and this wrapper does not depend on streaming or interactive confirmation events. See [tool-server support](https://docs.openwebui.com/features/extensibility/plugin/tools/openapi-servers/) and [backend vs. browser integration](https://docs.openwebui.com/features/extensibility/plugin/tools/openapi-servers/open-webui/). The running Open WebUI installation still needs its own integration smoke check; the test suite does not claim to have verified its UI or model.

---

## Tests and checks

```sh
uv run --locked pytest -q
uv run --locked ruff check src tests integrations scripts
uv run --locked ruff format --check src tests integrations scripts
uvx basedpyright
```

`pyproject.toml` sets standard type checking for Pyright and basedpyright, using the project's `.venv` and Python 3.12. The editor and CLI use the same configuration; basedpyright's stricter annotation/style rules are not enabled by this preset. `uvx` runs the checker separately from application dependencies. See [basedpyright configuration](https://docs.basedpyright.com/latest/configuration/config-files/).

All tests use HTTPX MockTransport, fixture data, or an in-process ASGI app, with no live credentials or requests to Craft. They verify exact mappings for all 41 routes across three adapters, discovery/editing, collection, and native task workflows, validation, auth, deadlines, size bounds, no retries, secret-safe errors/logs, allowlist enforcement, client shutdown, and OpenAPI validity.

Space response fixtures are extracted from the **first response example** for implemented operations in `craft-docs/space-api-docs.md`. Singleton mutation tests narrow example batches; focused error/workflow tests use additional synthetic data. Multi-Document tests use generic synthetic examples of documented responses, including deleted documents and scoped links. Daily Notes tests use generic synthetic fixtures for date-based content, search, collections, and partial task responses. Fixture generation never edits the source docs.

Live Craft validation is separate from automated tests. Read-only probes reproduced schema option objects, missing title metadata, and calendar-date string values. A separate write probe verified an existing collection row's Date update, read it back, restored the original value, and confirmed all properties matched their original values. Regression cases use generic synthetic values, not captured personal schemas. Secret-link-only authentication worked for these requests. No additional Craft auth headers or OAuth flow were documented or implemented, and select writes were not live-tested.

---

## Architecture

`api/` owns HTTP models, validation, auth, error translation, and tool descriptions. `craft/transport.py` owns bounded asynchronous HTTP, decoding, deadlines, and sanitized failures. `craft/space/client.py`, `craft/documents/client.py`, and `craft/daily/client.py` own their upstream query names and adapter methods. `craft/operations.py` shares matching block/collection mappings and response parsing; adapter-specific document/date summaries, task models, and filters stay separate. `config.py` owns environment settings and operation selection.

All three local docs were compared before design. Space has 44 documented method/path pairs, Multi-Document 33, Daily Notes 36; 31 are shared. Overlap does not imply matching semantics:

- Space includes daily-note access and tasks; it is not disjoint from the Daily Notes API.
- Scoped connections filter links and relations; never fall back to a broader Space connection.
- Single-document search selectors are `blockId` (Space), `documentId` (Multi-Document), and `date` (Daily Notes).
- Collection discovery uses document filters, document include/exclude filters, or date ranges respectively.
- Daily Notes has date defaults/search results and narrower task scopes; Space task `all` is not the union of active/upcoming/inbox/logbook.
- Views are stored definitions, not executed queries. Reminders have conditional availability/ownership and cursor pagination; neither is exposed in v1.

All three adapters reuse transport/errors and matching block/collection helpers and models. Keep scope-specific discovery and filters in their adapters; share additional helpers only when contracts match. Do not introduce a universal Craft interface or capability framework. Existing Space operation IDs stay stable.

V1 exposes native task listing/creation/update/deletion through Daily Notes only. Other deletion/movement operations, folder writes, collection creation/schema mutation/views, comments, reminders, uploads, and whiteboards remain deferred. Other documented gaps remain explicit: examples use inconsistent identifier terminology and collection-type representations; array query serialization and regex claims are ambiguous; list pagination and mutation atomicity are unspecified. The wrapper follows documented example field names, accepts single-value filters, preserves read type strings, and omits those uncertain capabilities.

---

## Roadmap

These additions are planned; their routes and configuration are not implemented yet.

### Additional Craft operations

Daily Notes content, existing collection items, and native task operations are implemented in the working tree. Future additions include Space task operations, other deletion/movement operations, collection creation/schema writes, comments, reminders, uploads, and whiteboards. Implement each against its adapter’s documented scope; do not expose Daily Notes task behavior through Space implicitly.

### Permission-based routes for LLM tools

Support multiple named Multi-Document connections within one wrapper instance. Each access profile selects a Craft connection, permitted operations, and a profile-bound wrapper credential. Different agents/tools can use different document scopes; multiple profiles can share a connection with different permissions. Give each profile a dedicated base URL and OpenAPI schema. Changing the URL must not let a profile's credential access another profile or the broader Space connection; never fall back between connections.

Expose permission-specific tool-server URLs, starting with an explicit read-only entry point, for example `/v1/space/read-only` with its own `/openapi.json`. A tool client could register this URL to discover and call only reads. Add narrower profiles for selected operation groups, such as content editing or collection-item updates, so different tools can receive different permissions on the same deployment.

Each profile must expose only its allowed HTTP routes and generate OpenAPI from those same routes. Enforce the scope on the server and bind credentials to permitted profiles, so a read-only tool cannot gain write access by calling a different URL. The deployment-wide operation allowlist remains an upper bound on every profile.

Use the generated OpenAPI operation IDs to communicate available operations to clients, rather than copying `WRAPPER_ENABLED_OPERATIONS` into Open WebUI settings. As an interim step, evaluate a capability-discovery function in the Python tool that reads the existing `/openapi.json` and reports the enabled operations. After scoped routes are added, discovery will read that profile's schema. Discovery failures must be reported rather than interpreted as full access; any cached result needs a bounded lifetime and refresh when the configured URL changes. The server remains authoritative if permissions change after discovery.

Open WebUI's OpenAPI integration can discover operations from the scoped schema. The Workspace Python tool has a separate constraint: its predefined function list is stored when the tool is saved. Capability discovery informs the model but does not automatically remove disabled functions from that list. Evaluate generating a reduced Python tool from a scoped schema during installation/update if hiding unavailable functions is required; avoid modifying Open WebUI internals or maintaining a second permission list.

The existing `WRAPPER_ENABLED_OPERATIONS` presets apply to the entire deployment and use one shared token. They do not yet provide separate permission URLs or credentials per tool. Existing Space paths and operation IDs will remain stable when these scoped entry points are added.

### Open WebUI profile factory and management (evaluation)

Build the factory for existing profiles first: an authorized user selects a profile, enters a tool name, previews its document scope and enabled operations, and clicks **Create tool**. Generate a dedicated tool from a trusted base definition using the profile's OpenAPI schema; expose only its enabled operations and configure its URL and credential separately from the generated source. Support regenerating the tool when the base definition or profile changes.

Current upstream Open WebUI provides [dynamic Valves dropdowns](https://docs.openwebui.com/features/extensibility/plugin/development/valves/#dynamic-options) for profile selection and [authenticated tool creation/update and Valves endpoints](https://github.com/open-webui/open-webui/blob/main/backend/open_webui/routers/tools.py) for saving tool instances. These establish the building blocks for a custom factory; verify compatibility with the installed Open WebUI version before implementation.

Add profile creation and management in a later step, including assigning a Craft Multi-Document connection and choosing permissions. This requires a wrapper administration API and persistent server-side configuration. Evaluate a user-triggered Open WebUI Action with an [interactive interface](https://docs.openwebui.com/features/extensibility/plugin/development/rich-ui/); embedded interfaces are sandboxed and must not assume access to the Open WebUI login session. If direct integration is impractical, use a small wrapper-hosted management interface that can be opened from Open WebUI, avoiding configuration-file edits on the deployment host.

Keep profile administration separate from ordinary LLM-callable tools, with explicit administrative authorization and durable server-side configuration. Keep connection secrets and wrapper credentials out of model context, generated tool source, logs, and exported definitions. Ordinary tool requests must never supply arbitrary upstream URLs or create profiles. The wrapper remains responsible for enforcing document scope and operation permissions.

Acceptance checks should cover selecting an existing profile, creating a tool with the matching operation set, creating a profile through the management flow, and updating a generated tool. Verify that read-only tools cannot write and that credentials cannot cross profiles, including when two profiles share a Craft connection. Profile revocation must stop access even if a tool retains an older definition.

### Reusable block and collection shapes (evaluation)

Evaluate named, versioned definitions for repeatable content structures, starting with a tasks collection. The aim is for creation through an LLM tool or a direct HTTP API call to use the same server-owned definition, defaults, and validation. Proposed task fields could include a title, status with explicit options, and a due date; settle the actual property keys, Craft types, and supported write values before defining the contract.

Keep block content structure, collection column schemas, and collection-item values distinct. A tasks collection is a collection of rows; it does not by itself establish native Craft task behavior. Verify the documented creation contracts and returned shapes before promising task integration or accepting additional property types.

Start with one concrete definition and evaluate how clients discover its shape and select its version when creating content. The API should apply that definition, and the Open WebUI tool should call the same API rather than recreate its rules. Acceptance checks should compare creation through both entry points and confirm consistent columns, options, defaults, and item validation. Collection creation is currently deferred; implementing this feature depends on adding the relevant creation operations and permissions.

Do not replace schemas on existing collections implicitly. Report incompatible shapes and require an explicit migration decision. Broader templates, dynamic per-collection OpenAPI generation, and a general schema registry are outside the initial evaluation.

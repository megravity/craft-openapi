# Project Overview & Agent Handoff

## Start here

This repository exposes a selected subset of [Craft](https://www.craft.do/)'s Space and Multi-Document APIs through a small HTTP service. Its purpose is to give LLM tools and other clients a stable, understandable API while keeping the upstream Craft client independent of the consumer.

Read [AGENTS.md](AGENTS.md) for contributor instructions, then use this map:

| Document | Purpose |
|---|---|
| [README.md](README.md) | Installation, configuration, endpoint contract, deployment updates, and troubleshooting context. |
| [Open WebUI setup](README.md#open-webui) | Native OpenAPI registration and the standalone Python Workspace tool. |
| [Roadmap](README.md#roadmap) | Proposed work; these capabilities are not implemented. |
| [CHANGELOG.md](CHANGELOG.md) | Release history. |
| [Space API reference](craft-docs/space-api-docs.md) | Upstream contracts for the implemented adapter. |
| [Multi-Document reference](craft-docs/documents-api-docs.md) | Implemented adapter's restricted document scope. |
| [Daily Notes reference](craft-docs/daily-notes-api-docs.md) | Future adapter's date targeting and task semantics. |

Treat running code and tests as evidence of implemented behavior. Upstream examples are incomplete and sometimes inconsistent; preserve the reference documents and record verified differences in the README. Do not assume identical upstream paths have identical contracts across connections.

## Current implementation

The current release version is **0.3.0**. It provides 13 operations under `/v1/space`: folders and documents, content search, structured/Markdown reads, empty document creation, Markdown insertion/update, and discovery/schema/row operations for existing collections.

Multi-Document support adds 11 operations under `/v1/documents`. Configure `CRAFT_SPACE_BASE_URL`, `CRAFT_DOCUMENTS_BASE_URL`, or both; at least one is required. Each adapter uses a separate client and never falls back to another connection. One independent wrapper bearer token covers all enabled routes. `WRAPPER_ENABLED_OPERATIONS` selects all configured operations, their reads (8 Space, 7 Multi-Document), or an explicit operation list. IDs for absent connections fail startup. Disabled routes are removed from routing and generated OpenAPI 3.1. Public health checks do not contact Craft or verify credentials.

Collection writes accept string-valued properties only; reads preserve dynamic JSON values. IDs are opaque: use API IDs from discovery, not IDs embedded in navigation links. Selected endpoints have no documented pagination. There are no automatic retries or transactional guarantees; write errors can report `outcomeUnknown=true`.

The Daily Notes adapter, native task operations, collection creation, and permission-specific URLs/tokens are not implemented. Separate Python Open WebUI tools expose 13 Space and 11 Multi-Document functions; server permissions still control calls. Capability discovery and reusable block/collection shapes are roadmap evaluations, not current features.

## How the code fits together

```text
HTTP caller → api/ auth and validation → craft/space/client.py or craft/documents/client.py
            → craft/transport.py → Craft → parsed response or sanitized error
```

Start at [main.py](src/craft_wrapper/main.py) for construction/lifecycle and [config.py](src/craft_wrapper/config.py) for settings. [api/space.py](src/craft_wrapper/api/space.py) defines routes and permanent operation IDs; [api/documents.py](src/craft_wrapper/api/documents.py) defines the Multi-Document counterpart routes; [api/documents_schemas.py](src/craft_wrapper/api/documents_schemas.py) keeps its filters separate. [api/schemas.py](src/craft_wrapper/api/schemas.py) defines shared inputs and Space filters. [craft/models.py](src/craft_wrapper/craft/models.py) and [craft/space/models.py](src/craft_wrapper/craft/space/models.py) parse responses.

[The Open WebUI tool](integrations/openwebui/craft_wrapper_tool.py) calls the wrapper over HTTP and returns request/status evidence. It is installed and updated separately from the wrapper image. The [Multi-Document tool](integrations/openwebui/craft_documents_tool.py) follows the same standalone installation model. Matching block/collection operations live in `craft/operations.py`; keep document discovery/models separate and preserve deletion status and scoped link markers. Share concrete transport behavior across future adapters; avoid a universal adapter framework or broader-connection fallbacks.

## Picking up work

Check `git status`, recent commits, and the relevant roadmap item before editing. Confirm the requested scope and inspect its upstream contract. Use [README checks](README.md#tests-and-checks) and [tests](tests/) to verify behavior with mocked responses; automatic tests need no live Craft credentials. Installed Open WebUI behavior and live Portainer deployment require separate smoke checks.

The [build script](scripts/build-image.sh) can trigger a deployment if a webhook is configured. Use `PORTAINER_WEBHOOK_URL= ./scripts/build-image.sh` for build-only work. Keep credentials, webhook URLs, private content, and local infrastructure names out of committed files. Preserve existing `.env` files.

## Versioning and releases

Version numbers identify releases, not individual commits. Our convention is patch releases for compatible fixes (`0.2.1`) and minor releases for new capabilities (`0.3.0`). Documentation/layout edits normally remain ordinary commits and accumulate toward the next release. Before 1.0, document any breaking changes explicitly. `/v1/space` identifies the HTTP contract separately from the package version.

For a release:

1. Review the notes under `## Unreleased` in `CHANGELOG.md` and choose an explicit next version.
2. Run `./scripts/prepare-release.sh X.Y.Z --dry-run`, then repeat without `--dry-run`. The command promotes the notes into a dated release and updates package, lockfile, Docker, both tools, and current-version documentation. It also syncs installed package metadata for OpenAPI `info.version`; see [local release preparation](README.md#prepare-a-release-locally) for date overrides and failure recovery.
3. Run tests, lint, formatting checks, and type checks. The version-consistency test checks package, OpenAPI, image-label, both tools, and changelog alignment.
4. Commit the release and create an annotated `vX.Y.Z` tag on that commit. Keep existing release tags unchanged; subsequent commits belong to future releases. Push the commit and tag when ready to publish: [the GitHub release workflow](README.md#github-releases) validates tagged metadata and publishes that tag's changelog notes. Use its manual trigger for older tags.

`craft-openapi-wrapper:local` is a mutable Docker tag, not an immutable release identifier. Check out a Git release tag before building an exact source release, and inspect the running image's version label as described in [README versioning](README.md#versioning). Commit/tag creation, publishing, and deployment are separate actions.

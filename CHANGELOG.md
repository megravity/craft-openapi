# Changelog

## Unreleased

- Add document-targeted Space task creation, partial updates/completion, and confirmed leaf-task deletion. Require owning context and fresh structural/native-task proofs, enforce planner document targets, and keep inbox/daily-note targets, movement, and clearing outside this checkpoint.

- Improve Python-tool deletion feedback with visible no-deletion statuses and separate cancellation, invalid callback, and callback-failure handling; clarify that ID reads omit write context. Record Space/Daily planner verification observations and the unresolved timeout.
- Add opt-in experimental read-only, planner, and expiring copy-only migration profiles with separate tokens, schemas/capabilities, approved write targets, and no legacy-route bypass.
- Verify collection membership and owning document/note structure before scoped writes, excluding collection subtrees and unsupported relation/complex property writes; share the overall verification/submission deadline.
- Add profile-aware Open WebUI tools, capability discovery, and captured-request deletion confirmations that fail closed without an explicit live approval.
- Add Space task discovery and singleton collection-item/leaf-text deletion across adapters, with protected root/type checks and uncertain-outcome handling.
- Document reviewed backlog copies, source-ID duplicate checks, explicit scheduled-task linkage, and sanitized Portainer profile setup. A follow-up pinned the title-write contract for both default/named columns using their actual top-level schema keys, with exact restoration. Title routes and schema-aware headline normalization remain unimplemented.
- Keep release metadata at 0.4.0; the next capability release is expected to be 0.5.0.

## 0.4.0 — 2026-10-04

- Add 17 Daily Notes operations and a standalone Open WebUI tool, including date-based content, scoped collection items, and native task listing/creation/update/deletion. Support all seven connection combinations with independent clients and configured-adapter allowlists.
- Rename the Space tool source to `craft_space_tool.py` without changing functions or Valves; extend release preparation to all three tools and retain historical-tag filename compatibility.
- Add `./scripts/prepare-release.sh` to promote reviewed changelog notes and align package, lockfile, Docker, Open WebUI tool, and documentation versions. Committing, tagging, and publishing remain separate steps.

## 0.3.0 — 2026-10-03

- Add 11 Multi-Document operations and a dedicated standalone Open WebUI tool, preserving selected-document scope, deletion status, and include/exclude filtering.
- Support Space-only, Multi-Document-only, and combined instances with separate connection clients and configured-adapter allowlists; share the existing wrapper token.
- Share matching block/collection mappings, response models, and errors without changing Space paths or operation IDs.
- Update Compose, configuration, installation, and handoff documentation; validate both tools' versions while retaining older-tag release support.
- Verify adapter isolation, strict inputs, route/schema availability, and document/collection workflows using mocked Craft responses.
- Extend the roadmap with multiple connections, profile-bound credentials, and an Open WebUI profile factory and management flow; these remain planned capabilities.

## 0.2.0 — 2026-10-02

- Add a standalone Open WebUI Workspace tool for all 13 wrapper operations, with HTTP request evidence, preserved errors, and no automatic retries.
- Add an optional Portainer stack webhook after successful local image builds, using `pullimage=false` and an ignored secret configuration file.
- Document tool installation/updates and webhook configuration.
- Expand the roadmap with scoped URLs, tokens, OpenAPI schemas, capability discovery, and evaluation of reusable block/collection shapes.
- Start versioned releases with matching package, OpenAPI, Open WebUI tool, and Docker image metadata.

Earlier development commits predate release tagging.

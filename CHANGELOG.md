# Changelog

## Unreleased

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

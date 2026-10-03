# Repository Guidelines

Read [PROJECT.md](PROJECT.md) for context and documentation links.

## Project Structure & Architecture

- `src/craft_wrapper/`: FastAPI application factory and configuration. `api/` owns routes, validation, authentication, and public errors; `craft/` owns HTTP transport and the Space and Multi-Document clients.
- `integrations/openwebui/`: standalone Space and Multi-Document Workspace tools. Keep the Craft client independent of FastAPI and Open WebUI.
- `tests/`: pytest suites and synthetic fixtures in `tests/fixtures/`.
- `craft-docs/`: upstream reference documents; preserve them when changing implementation.
- `scripts/build-image.sh`, `Dockerfile`, and Compose files: builds/deployment; `README.md` covers setup.

## Build, Test & Development Commands

Run from the repository root:

```sh
uv sync --locked --dev                         # Install locked dependencies
uv run --locked uvicorn craft_wrapper.main:create_app --factory --reload --no-access-log
uv run --locked pytest -q                      # Run automated tests
uv run --locked ruff check src tests integrations scripts
uv run --locked ruff format src tests integrations scripts
uvx basedpyright                               # Check types using pyproject.toml
PORTAINER_WEBHOOK_URL= ./scripts/build-image.sh # Build without triggering deployment
```

Startup requires credentials; copy `.env.example` only if `.env` is absent.

## Coding Style & Naming

Use Python 3.12+, four-space indentation, type hints, and Ruff's 100-character line limit. Use `snake_case` for functions/modules and `PascalCase` for classes. Keep existing HTTP paths and explicit `craft_space_*` and `craft_documents_*` operation IDs stable. Separate upstream request mapping from public API validation; prefer concrete helpers over universal adapter frameworks. Prefix Open WebUI helper methods with `_` to avoid exposing them as tools.

## Testing Guidelines

Name files `test_*.py` and functions `test_*`. Use HTTPX MockTransport or an in-process ASGI app; tests must not depend on live credentials. Cover changed mappings, validation, errors, permissions, and uncertain write outcomes. Validate OpenAPI after contract changes. No coverage threshold is configured. Run lint, formatting checks, and type checks before submitting.

## Commit & Pull Request Guidelines

Use concise imperative subjects, following history: `Fix collection schema parsing` or `Improve README navigation`. Keep commits focused. PRs should explain behavior, validation, limitations, and relevant issues.

## Versioning

Use patch releases for compatible fixes and minor releases for capabilities. Documentation edits normally need no version bump. Review `CHANGELOG.md`'s `Unreleased` notes, then use `./scripts/prepare-release.sh X.Y.Z --dry-run` before applying preparation. Follow [PROJECT.md's release steps](PROJECT.md#versioning-and-releases). Commit, tag, and push separately; do not move existing tags.

## Security & Configuration

Never commit `.env`, `.portainer-webhook`, connection URLs, tokens, personal identifiers, or captured private content. Use generic fixtures and sanitized errors/logs. Keep redirects and automatic retries disabled. Server permissions remain authoritative; tool visibility is not authorization. Distinguish roadmap proposals from implemented capabilities.

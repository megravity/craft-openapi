# Experimental Permission Profiles

Profiles reuse configured Craft connections and add server-side operation and write-target restrictions. This feature is **unreleased**, intended for the next capability release, **0.5.0**. Current package/tool metadata remains 0.4.0.

## What the safeguards mean

| Profile | Reads | Writes |
|---|---|---|
| `read-only` | Enabled reads through its selected adapters | None |
| `planner` | Enabled reads through its selected adapters | Approved collections and planning documents; Daily Notes content/native tasks. Deletion requires a dialog in the Python tool. |
| `migration` | Enabled reads through its selected adapters, including Space task discovery | Add rows to exactly one Space collection; no updates/deletion. A timezone-aware expiration is mandatory. |

Each profile has its own token and URL prefix. `WRAPPER_ENABLED_OPERATIONS` is still an upper bound. A profile's optional `operations` list can restrict its preset further, but cannot grant permissions outside that preset. Profiles with no collection/document targets have no corresponding Space/Multi-Document write operations. Planner cannot create documents or replace collection schemas.

These profiles restrict modification targets, **not the privacy of broad Space reads**. Shared-link membership checks are read-then-write and cannot prevent a concurrent move inside Craft atomically. Use a Craft selected-document connection when upstream isolation is required. No fallback between connections is permitted.

Dialogs are a Python-tool safeguard, not server-verified approval. A raw HTTP client holding an authorized planner token can delete permitted targets without a dialog. Do not share that credential with arbitrary HTTP or code-execution tools. OpenAPI server registration does not provide these dialogs.

## Portainer configuration

Use the current `docker-compose.portainer.yml` in the stack editor; entering a variable alone does not forward it to the container. Continue using the same Craft connection URL variables. No additional Craft URLs are required for the profiles.

Add one `WRAPPER_PROFILES_JSON` stack variable. The example below intentionally contains placeholders: replace resource IDs from discovery, select only configured adapters, and set a near-term migration expiration before use.

```json
{
  "read-only": {
    "adapters": ["space", "daily"]
  },
  "planner": {
    "adapters": ["space", "daily"],
    "writeTargets": {
      "space": {
        "documentIds": ["PLANNING_DOCUMENT_ROOT_ID"],
        "collectionIds": ["BACKLOG_COLLECTION_ID"]
      }
    }
  },
  "migration": {
    "adapters": ["space"],
    "expiresAt": "REPLACE_WITH_NEAR_TERM_TIMESTAMP",
    "writeTargets": {
      "space": {"collectionIds": ["BACKLOG_COLLECTION_ID"]}
    }
  }
}
```

Generate a UTC expiration two hours from now on the Pi with:

```sh
python3 -c 'from datetime import UTC, datetime, timedelta; print((datetime.now(UTC) + timedelta(hours=2)).isoformat())'
```

Add distinct credentials as separate variables: `WRAPPER_READ_ONLY_TOKEN`, `WRAPPER_PLANNER_TOKEN`, and `WRAPPER_MIGRATION_TOKEN`. Only enabled profiles need a credential. Missing profiles are disabled; `enabled:false` disables a configured profile. Invalid rules, unavailable adapters, invalid/duplicate IDs, unknown or disallowed operation IDs, missing required credentials, and duplicate profile credentials fail startup with a sanitized error.

Update the stack manually with image pulling disabled. Confirm the actual running image and health; webhook acceptance alone does not establish successful deployment. Rules/tokens are loaded at startup, so configuration changes and revocation require restarting/recreating with the new settings. Expiration is enforced on each request and rechecked after write verification.

When profiles are configured, unprefixed `/v1/...` routes are absent and `WRAPPER_API_TOKEN` is ignored. Existing installed tools must be updated and configured for a profile. Without `WRAPPER_PROFILES_JSON`, existing legacy routes/token behavior remains available.

For local development, the same variables work in the ignored `.env`, with environment variables taking precedence. Keep the JSON rules and credentials out of committed configuration. Do not modify an existing `.env` by copying the example over it.

## HTTP interfaces

A planner Space operation is available at `/profiles/planner/v1/space/...`; the corresponding schema is `/profiles/planner/openapi.json` and inspection UI is `/profiles/planner/docs`. Other profiles use the same structure. Public schemas contain enabled operations and bearer security, with no credentials or writable-target IDs. Root health remains public and does not verify Craft credentials.

Authenticated `GET /profiles/planner/capabilities` returns `profileId`, `adapters`, `operations`, `writeTargets`, and `expiresAt`. It is infrastructure, excluded from the Craft tool schema and API coverage counts. Tokens are bound to profiles; changing the URL cannot broaden a token's access.

| Condition | Result |
|---|---|
| Missing/wrong profile token | `401 unauthorized` |
| Profile-disallowed operation or target | `403 permission_denied` |
| Expired profile | `403 profile_expired` |
| Missing profile or globally disabled operation | `404 not_found` |
| Missing/invalid write context | `422 validation_error` |
| Malformed, incomplete, or oversized verification response | Sanitized upstream error; no mutation |

Expired profiles also refuse schema/docs access. Unconfigured adapters remain unavailable. A profile schema shows operation permissions; target restrictions are returned only by authenticated capability discovery.

## Write context and verification

Collection writes require an approved `collectionId`. When properties are supplied in profile mode, the wrapper reads the schema and accepts only known simple string-valued field types; relations, block links, and unknown/complex types are denied before mutation to avoid reciprocal writes outside the target. Craft still validates the supplied values. Updates and deletion use a fresh properties-only item read to verify that `itemId` belongs to that collection. New item deletion verifies membership in legacy mode too.

Space/Multi-Document insertion and block updates in profile mode require owning `documentId` in the query. The wrapper reads that approved root with `maxDepth=-1`, checks the returned root ID and structure, and locates the target only through actual content. IDs embedded in Markdown, links, or properties are not authority. Collection subtrees/items are excluded from document-edit permissions.

Space native-task creation requires `documentId` in the body; updates/deletion require it in the query in every mode. Planner enables these operations only with approved Space document roots. Read-only/migration cannot write tasks. Each existing task is checked in the full document structure (excluding collections/links) and fresh native `scope=document` discovery. Deletion allows only leaf text tasks; nested content is protected. Roots and verification lists must be valid/unambiguous, and expiry is rechecked before submission. Use Daily for inbox/daily-note targets; Space task movement and date clearing remain unsupported.

Daily ID-based insertion/updates in profile mode require owning `date` context. Date insertion still defaults to today. Native Daily task writes use Craft's Daily connection scope; they do not require a document/date context parameter.

All leaf-block deletion calls require context, including legacy mode. Only leaf text blocks are deletable; roots, pages, collections, whiteboards, media, descendants, and incomplete reads are protected. Deleting a collection row also removes its nested notes.

Verification is fresh, uncached, and consumes upstream request/block budgets. Verification plus submission shares the overall deadline. Expired access or failed verification prevents mutation. Errors after mutation submission can include `outcomeUnknown=true`; inspect the actual state before repeating. There are no retries, transactions, or rollback guarantees.

## Open WebUI setup

Update each installed standalone tool from its source. Keep `WRAPPER_URL` as the shared origin, set `WRAPPER_PROFILE` to `read-only`, `planner`, or `migration`, and put that profile's credential in `WRAPPER_API_TOKEN`. Leave the profile Valve empty only for a legacy server.

Each tool includes `craft_<adapter>_get_capabilities`; use it to discover enabled operations and writable targets. Profile calls also verify capabilities before execution. The Python function list is static, so discovery does not hide disabled functions; the server remains authoritative.

Deletion uses the native Python tool's `__event_call__` dialog. It reads a bounded target preview, displays exact IDs/context and consequences, and accepts only explicit `True`. The request/profile/credential are captured before prompting. Cancellation, errors, timeout after 120 seconds, browser disconnection, missing callbacks, and unreadable previews prevent deletion. No model-provided `confirmed` flag bypasses this. Unattended automations can perform ordinary permitted actions but cannot delete through these tools.

Only literal `False` is reported as `tool_confirmation_declined`; other non-boolean responses, including error dictionaries, return `tool_confirmation_invalid_response`. Callback exceptions/timeouts return `tool_confirmation_unavailable` with a fixed message identifying the condition. These local failures have no HTTP status/request ID, set `outcomeUnknown:false`, and submit no deletion. Inspect the result and do not automatically retry cancellation or failed confirmation.

Deletion functions use the reserved `__event_emitter__` callback to display a final, visible **Nothing deleted** status for confirmation/preview failures. Missing or failed status delivery leaves the structured error and no-mutation behavior intact; status delivery is bounded to five seconds. These callback arguments are supplied by Open WebUI, not the model.

See [Open WebUI events](https://docs.openwebui.com/features/extensibility/plugin/development/events/). An installed-version smoke check is still required; mocked callback tests do not certify your browser/WebSocket setup.

## Live pilot evidence

User-reported Open WebUI checks passed for Space planner collection creation/property updates, scoped text insertion/updates, canceled/approved deletion, and denial of an unapproved collection. Daily planner checks passed for inbox-task creation with scheduling/deadline fields, rescheduling with unrelated fields preserved, completion/logbook read-back, cancellation with the task retained, and approved deletion verified by listing plus `craft_not_found` on the exact block ID. One creation returned a timeout with an uncertain outcome; inspection found exactly one task and no write retry was made. The latency cause remains unconfirmed.

These checks cover the installed tool at that point, not every adapter/permission scenario. The newer visible-status/invalid-callback distinction still needs an installed-tool smoke check. The newer Space task writes still need live verification, and collection-title editing remains unavailable; this pilot does not establish complete MCP replacement.

## Delivery checkpoints

| Checkpoint | State in the working tree |
|---|---|
| 0. Title-write verification | Default title update/restore passed; named title column rejected the same HTTP payload. Both scratch rows retained their original properties/content. No title-edit endpoint is exposed. |
| 1. Read-only profiles | Configuration, credentials, profile schema/capabilities, expiry, and legacy isolation implemented. |
| 2. Planner/migration scope | Target checks and combined deadlines implemented. Migration remains copy-only. |
| 3. Python-tool safeguards | Profile discovery and fail-closed confirmation implemented, including existing Daily task deletion. |
| 4. Space task discovery | All six discovery scopes implemented; the follow-up adds approved-document creation/updates and verified leaf-task deletion. Inbox/daily-note Space targets, movement and clearing stay unavailable. |
| 5. Collection-item deletion | Singleton deletion across three adapters, membership checks, and dialog integration implemented. |
| 6. Leaf-block deletion | Scoped structural/type checks and dialog integration implemented across three adapters. |
| 7. Title editing | Unavailable: verification gate did not pass for both title-column shapes. No undocumented workaround. |
| 8. Reviewed workflow | [Backlog workflow](BACKLOG_WORKFLOW.md), mocked acceptance scenarios, setup and coverage documentation. |

These checkpoints are implementation groups, not automatically created Git commits or releases. Live deployment, real migration, release preparation, commits/tags/publishing, and broader permission management remain separate actions.

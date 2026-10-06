# Craft API Coverage Matrix

## Baseline and sources

Inventory audited **2026-10-06** against release **0.4.0** (`bd9b08e`). This is a repository snapshot, not a live Craft certification or a statement about which adapters a deployed server enables.

| Adapter | Local reference | Reference version | Public documentation |
|---|---|---|---|
| Space | [Space API](craft-docs/space-api-docs.md) | 1.0.0 | [All Documents](https://connect.craft.do/api-docs/space) |
| Multi-Document | [Multi-Document API](craft-docs/documents-api-docs.md) | 1.0.0 | [Selected Documents](https://connect.craft.do/api-docs/documents/) |
| Daily Notes | [Daily Notes API](craft-docs/daily-notes-api-docs.md) | 1.0.0 | [Daily Notes and Tasks](https://connect.craft.do/api-docs/daily-notes/) |

The local exports do not record their original retrieval dates. Counts and classifications below use those local references; current public-documentation parity was not revalidated in this audit. Refresh references before adding operations or claiming complete coverage. Preserve each adapter's scope even where upstream paths match.

## Status and counting rules

- **I — Implemented:** a wrapper equivalent exists with no identified omission in the documented inputs/example shapes for this row. Defaults, envelopes, validation, and modeled response projection remain explicit adaptations. This is not a guarantee for every live payload.
- **P — Partial:** a wrapper equivalent exists, but a documented selector, body variant, batch shape, representation, or contract ambiguity remains. Intentional restrictions still count as partial.
- **D — Deferred:** documented for this adapter, with no public wrapper equivalent or operation tests yet.
- **N/A — Not applicable:** absent from this adapter's local reference. Do not expose it by falling back to a broader connection.

Count upstream **method/path pairs separately per adapter**. Multiple wrapper routes can represent one upstream endpoint; I and P both count toward operation presence, while P blocks a full-contract claim. Infrastructure endpoints and permission profiles are not Craft operation coverage. Unconfigured adapters and disabled operations are intentionally absent from HTTP routing/OpenAPI and return 404.

## Coverage totals

| Adapter | Documented pairs | I | P | D | Represented pairs (I + P) | Public wrapper operations |
|---|---:|---:|---:|---:|---:|---:|
| Space | 44 | 2 | 10 | 32 | 12 | 13 |
| Multi-Document | 33 | 2 | 8 | 23 | 10 | 11 |
| Daily Notes | 36 | 3 | 10 | 23 | 13 | 17 |
| **Total** | **113** | **7** | **28** | **78** | **35** | **41** |

The endpoint grid has 45 distinct method/path rows: 31 are documented in all three adapters. Its N/A cells are excluded from the 113-pair denominator. Structured/Markdown read splits and Daily Notes date/ID route splits account for the difference between 35 represented upstream pairs and 41 public operations.

## Upstream endpoint grid

Each cell is independent. See the public mappings and contract notes below for I/P rows; D rows require a request/response audit against the linked local reference before design.

| Upstream method/path | Space | Multi-Document | Daily Notes |
|---|---|---|---|
| `GET /blocks` | P | P | P |
| `POST /blocks` | P | P | P |
| `DELETE /blocks` | D | D | D |
| `PUT /blocks` | P | P | P |
| `PUT /blocks/move` | D | D | D |
| `GET /collections/{collectionId}/items` | I | I | I |
| `POST /collections/{collectionId}/items` | P | P | P |
| `DELETE /collections/{collectionId}/items` | D | D | D |
| `PUT /collections/{collectionId}/items` | P | P | P |
| `PUT /collections/{collectionId}/active-view` | D | D | D |
| `GET /collections/{collectionId}/views` | D | D | D |
| `POST /collections/{collectionId}/views` | D | D | D |
| `DELETE /collections/{collectionId}/views/{viewId}` | D | D | D |
| `PUT /collections/{collectionId}/views/{viewId}` | D | D | D |
| `GET /collections` | P | P | I |
| `POST /collections` | D | D | D |
| `GET /collections/{collectionId}/schema` | P | P | P |
| `PUT /collections/{collectionId}/schema` | D | D | D |
| `POST /comments` | D | D | D |
| `GET /connection` | D | D | D |
| `GET /documents` | P | I | N/A |
| `POST /documents` | P | N/A | N/A |
| `DELETE /documents` | D | N/A | N/A |
| `PUT /documents/move` | D | N/A | N/A |
| `GET /reminders` | D | D | D |
| `POST /reminders` | D | D | D |
| `DELETE /reminders` | D | D | D |
| `PUT /reminders` | D | D | D |
| `GET /folders` | I | N/A | N/A |
| `POST /folders` | D | N/A | N/A |
| `DELETE /folders` | D | N/A | N/A |
| `PUT /folders/move` | D | N/A | N/A |
| `GET /blocks/search` | D | D | D |
| `GET /documents/search` | P | P | N/A |
| `GET /tasks` | D | N/A | I |
| `POST /tasks` | D | N/A | P |
| `DELETE /tasks` | D | N/A | P |
| `PUT /tasks` | D | N/A | P |
| `POST /upload` | D | D | D |
| `POST /whiteboards` | D | D | D |
| `GET /whiteboards/{whiteboardBlockId}/elements` | D | D | D |
| `POST /whiteboards/{whiteboardBlockId}/elements` | D | D | D |
| `DELETE /whiteboards/{whiteboardBlockId}/elements` | D | D | D |
| `PUT /whiteboards/{whiteboardBlockId}/elements` | D | D | D |
| `GET /daily-notes/search` | N/A | N/A | P |

## Public operation mappings

Paths below include the adapter prefix. Each operation ID is also a function in that adapter's standalone Open WebUI tool. The contract key links to supported input models/parameters, translation, and remaining gaps; regression evidence is listed under Verification evidence. Response model names refer to the adapter's models; the two `DocumentSummary` classes are distinct. `Items[T]` is a JSON `{items: [...]}` envelope.

### Space

Sources: [routes](src/craft_wrapper/api/space.py), [client](src/craft_wrapper/craft/space/client.py), [tool](integrations/openwebui/craft_space_tool.py).

| Operation ID | Wrapper method/path | Upstream method/path | Contract | JSON response model |
|---|---|---|---|---|
| `craft_space_list_folders` | `GET /v1/space/folders` | `GET /folders` | [F1](#f1) | `Items[Folder]` |
| `craft_space_list_documents` | `GET /v1/space/documents` | `GET /documents` | [L1](#l1) | `Items[DocumentSummary]` |
| `craft_space_search_documents` | `GET /v1/space/documents/search` | `GET /documents/search` | [S1](#s1) | `Items[DocumentSearchHit]` |
| `craft_space_create_document` | `POST /v1/space/documents` | `POST /documents` | [D1](#d1) | `DocumentSummary` |
| `craft_space_get_block` | `GET /v1/space/blocks/{blockId}` | `GET /blocks` | [B1](#b1) | `Block` |
| `craft_space_read_markdown` | `GET /v1/space/blocks/{blockId}/markdown` | `GET /blocks` | [B1](#b1) | `MarkdownContent` |
| `craft_space_insert_markdown` | `POST /v1/space/blocks/{pageId}/content` | `POST /blocks` | [B2](#b2) | `Items[Block]` |
| `craft_space_update_block_markdown` | `PATCH /v1/space/blocks/{blockId}` | `PUT /blocks` | [B3](#b3) | `Block` |
| `craft_space_list_collections` | `GET /v1/space/collections` | `GET /collections` | [C5](#c5) | `Items[CollectionSummary]` |
| `craft_space_get_collection_schema` | `GET /v1/space/collections/{collectionId}/schema` | `GET /collections/{collectionId}/schema` | [C4](#c4) | `CollectionSchema` |
| `craft_space_list_collection_items` | `GET /v1/space/collections/{collectionId}/items` | `GET /collections/{collectionId}/items` | [C1](#c1) | `Items[CollectionItem]` |
| `craft_space_add_collection_item` | `POST /v1/space/collections/{collectionId}/items` | `POST /collections/{collectionId}/items` | [C2](#c2) | `CollectionItem` |
| `craft_space_update_collection_item_properties` | `PATCH /v1/space/collections/{collectionId}/items/{itemId}` | `PUT /collections/{collectionId}/items` | [C3](#c3) | `CollectionItem` |

### Multi-Document

Sources: [routes](src/craft_wrapper/api/documents.py), [client](src/craft_wrapper/craft/documents/client.py), [tool](integrations/openwebui/craft_documents_tool.py).

| Operation ID | Wrapper method/path | Upstream method/path | Contract | JSON response model |
|---|---|---|---|---|
| `craft_documents_list_documents` | `GET /v1/documents/documents` | `GET /documents` | [L2](#l2) | `Items[DocumentSummary]` |
| `craft_documents_search_documents` | `GET /v1/documents/documents/search` | `GET /documents/search` | [S1](#s1) | `Items[DocumentSearchHit]` |
| `craft_documents_get_block` | `GET /v1/documents/blocks/{blockId}` | `GET /blocks` | [B1](#b1) | `Block` |
| `craft_documents_read_markdown` | `GET /v1/documents/blocks/{blockId}/markdown` | `GET /blocks` | [B1](#b1) | `MarkdownContent` |
| `craft_documents_insert_markdown` | `POST /v1/documents/blocks/{pageId}/content` | `POST /blocks` | [B2](#b2) | `Items[Block]` |
| `craft_documents_update_block_markdown` | `PATCH /v1/documents/blocks/{blockId}` | `PUT /blocks` | [B3](#b3) | `Block` |
| `craft_documents_list_collections` | `GET /v1/documents/collections` | `GET /collections` | [C5](#c5) | `Items[CollectionSummary]` |
| `craft_documents_get_collection_schema` | `GET /v1/documents/collections/{collectionId}/schema` | `GET /collections/{collectionId}/schema` | [C4](#c4) | `CollectionSchema` |
| `craft_documents_list_collection_items` | `GET /v1/documents/collections/{collectionId}/items` | `GET /collections/{collectionId}/items` | [C1](#c1) | `Items[CollectionItem]` |
| `craft_documents_add_collection_item` | `POST /v1/documents/collections/{collectionId}/items` | `POST /collections/{collectionId}/items` | [C2](#c2) | `CollectionItem` |
| `craft_documents_update_collection_item_properties` | `PATCH /v1/documents/collections/{collectionId}/items/{itemId}` | `PUT /collections/{collectionId}/items` | [C3](#c3) | `CollectionItem` |

### Daily Notes

Sources: [routes](src/craft_wrapper/api/daily.py), [client](src/craft_wrapper/craft/daily/client.py), [tool](integrations/openwebui/craft_daily_tool.py).

| Operation ID | Wrapper method/path | Upstream method/path | Contract | JSON response model |
|---|---|---|---|---|
| `craft_daily_get_note` | `GET /v1/daily/notes` | `GET /blocks` | [B1](#b1) | `Block` |
| `craft_daily_read_note_markdown` | `GET /v1/daily/notes/markdown` | `GET /blocks` | [B1](#b1) | `DailyMarkdownContent` |
| `craft_daily_insert_note_markdown` | `POST /v1/daily/notes/content` | `POST /blocks` | [B2](#b2) | `Items[Block]` |
| `craft_daily_search_notes` | `GET /v1/daily/notes/search` | `GET /daily-notes/search` | [S2](#s2) | `Items[DailyNoteSearchHit]` |
| `craft_daily_list_collections` | `GET /v1/daily/collections` | `GET /collections` | [C6](#c6) | `Items[DailyCollectionSummary]` |
| `craft_daily_get_block` | `GET /v1/daily/blocks/{blockId}` | `GET /blocks` | [B1](#b1) | `Block` |
| `craft_daily_read_markdown` | `GET /v1/daily/blocks/{blockId}/markdown` | `GET /blocks` | [B1](#b1) | `MarkdownContent` |
| `craft_daily_insert_markdown` | `POST /v1/daily/blocks/{pageId}/content` | `POST /blocks` | [B2](#b2) | `Items[Block]` |
| `craft_daily_update_block_markdown` | `PATCH /v1/daily/blocks/{blockId}` | `PUT /blocks` | [B3](#b3) | `Block` |
| `craft_daily_get_collection_schema` | `GET /v1/daily/collections/{collectionId}/schema` | `GET /collections/{collectionId}/schema` | [C4](#c4) | `CollectionSchema` |
| `craft_daily_list_collection_items` | `GET /v1/daily/collections/{collectionId}/items` | `GET /collections/{collectionId}/items` | [C1](#c1) | `Items[CollectionItem]` |
| `craft_daily_add_collection_item` | `POST /v1/daily/collections/{collectionId}/items` | `POST /collections/{collectionId}/items` | [C2](#c2) | `CollectionItem` |
| `craft_daily_update_collection_item_properties` | `PATCH /v1/daily/collections/{collectionId}/items/{itemId}` | `PUT /collections/{collectionId}/items` | [C3](#c3) | `CollectionItem` |
| `craft_daily_list_tasks` | `GET /v1/daily/tasks` | `GET /tasks` | [T1](#t1) | `Items[Task]` |
| `craft_daily_add_task` | `POST /v1/daily/tasks` | `POST /tasks` | [T2](#t2) | `Task` |
| `craft_daily_update_task` | `PATCH /v1/daily/tasks/{taskId}` | `PUT /tasks` | [T3](#t3) | `Task` |
| `craft_daily_delete_task` | `DELETE /v1/daily/tasks/{taskId}` | `DELETE /tasks` | [T4](#t4) | `DeletedTask` |

## Supported contracts and remaining gaps

Input types live in [shared/Space schemas](src/craft_wrapper/api/schemas.py), [Multi-Document schemas](src/craft_wrapper/api/documents_schemas.py), and [Daily Notes schemas](src/craft_wrapper/api/daily_schemas.py). Response types live in [common models](src/craft_wrapper/craft/models.py) and the [Space](src/craft_wrapper/craft/space/models.py), [Multi-Document](src/craft_wrapper/craft/documents/models.py), and [Daily Notes](src/craft_wrapper/craft/daily/models.py) model modules. Matching mappings use [operations.py](src/craft_wrapper/craft/operations.py).

All incoming models reject unknown fields. IDs are opaque nonempty strings; path IDs are safely encoded. Supported dates are valid calendar dates or `today`/`tomorrow`/`yesterday`, forwarded unchanged. Absolute reversed ranges are rejected. Upstream parsing ignores unmodeled fields; public serialization returns modeled fields, so this is not a lossless proxy. Block content, nested collection rows, previews, dynamic property values, and scoped `invalid:out_of_scope` markers are retained when modeled/returned.

Reads/updates/deletion return 200; document/item/task creation and Markdown insertion return 201. Singleton writes wrap upstream arrays and reject zero/multiple results, with uncertain-outcome handling. These adaptations do not create transactions or retry safety.

### B1

**Block reads — P in all adapters.** `Identifier` plus `BlockDepth` supports ID reads; Daily Notes also uses `DailyNoteRead` for date reads, defaulting to today. `maxDepth=1` by default, with `-1` available for all descendants. JSON reads return `Block`; Markdown reads use `Accept: text/markdown` upstream and return `{blockId, markdown}` or `{date, markdown}`. Daily date reads send only `date`, ID reads only `id`.

**Gaps:** no `fetchMetadata` selector or corresponding author/comment/timestamp block metadata. Space's documented date selector is not exposed through the Space adapter; using Daily Notes is not equivalent Space coverage. Multi-Document supports ID targeting only by its reference. Finite depth defaults are intentional, not a missing depth mode.

### B2

**Block insertion — P in all adapters.** `InsertMarkdown` accepts nonempty `markdown` and `position=start|end` (default end). JSON maps to `{markdown, position:{pageId, position}}`; Daily Notes date insertion adds `DailyNoteSelector` (default today) and uses `date` instead of `pageId`. Responses retain multiple created blocks and their IDs. Date insertion targets Craft's most recently updated note for that date; callers can use its page ID for an exact target.

**Gaps:** no structured `blocks` request array or sibling-relative positions. Space date insertion is not exposed. Daily Notes' raw `text/markdown` request-body mode is not exposed; its JSON Markdown mapping is separately tested. Additional placement/body variants need a fresh upstream audit.

### B3

**Block updates — P in all adapters.** `Identifier` plus `UpdateMarkdown` maps wrapper PATCH to `PUT /blocks` with `blocks:[{id,markdown}]`, unwrapping one returned `Block`. Empty replacement Markdown is accepted.

**Gaps:** batch updates and non-Markdown fields, including the documented `font` example, are not exposed. This updates one existing text block, not an entire document.

### C1

**Collection-item reads — I in all adapters.** `Identifier` plus `ItemDepth` forwards `maxDepth` (default 0; `-1` supported), returning `Items[CollectionItem]`. Dynamic JSON properties include scalar, array, and object values; nested content/previews are modeled. There is no documented cursor or view-execution parameter. The shallower default and modeled response projection are intentional adaptations.

### C2

**Collection-item creation — P in all adapters.** `AddCollectionItem` accepts one nonempty title and optional string-valued `properties`. It maps to `{items:[{title,properties}]}` and unwraps `CollectionItem`.

**Gaps/boundaries:** documented array input is restricted to one item. Relations, complex values, and null clearing are unsupported; legal property values are validated by Craft. Dynamic read values do not establish complex-write contracts. Verify additional write shapes before exposing them.

### C3

**Collection-item updates — P in all adapters.** `Identifier` for collection/item plus nonempty `UpdateCollectionProperties` maps PATCH to `PUT .../items` with `{itemsToUpdate:[{id,properties}]}`. Omitted properties are preserved; response is one possibly sparse `CollectionItem`.

**Gaps/boundaries:** no batch updates; string-valued property changes only. Title updates, relations, and clearing are not promised by the wrapper or inferred from the examples; verify upstream support before adding them.

### C4

**Collection-schema reads — P in all adapters.** `Identifier` maps to `format=schema` and returns `CollectionSchema`: optional key/title metadata, name, property keys/names/type strings, and option labels or name/color objects. Observed sparse schemas and option objects have synthetic regression coverage.

**Gaps:** no `json-schema-items` output mode. The duplicated `propertyDetails` field in reference examples and other unmodeled schema fields are not serialized; preserve this distinction when evaluating full response parity. Returned type strings are not normalized into a universal schema.

### C5

**Space/Multi-Document collection discovery — P.** Space `CollectionFilters` accepts optional singular `documentId`, mapping to `documentIds`; Multi-Document `DocumentsCollectionFilters` also accepts `documentFilterMode=include|exclude`, defaulting to include when an ID is supplied. Mode without ID is rejected. Both return `Items[CollectionSummary]` containing document IDs.

**Gap:** upstream multi-document array filtering is not exposed; its query encoding remains unspecified in the references. Scope selection never broadens the configured connection.

### C6

**Daily Notes collection discovery — I.** `DailyDateRange` forwards optional `startDate`/`endDate` and returns `Items[DailyCollectionSummary]` with `dailyNoteDate`, not `documentId`. This covers the documented filters; it neither executes stored views nor fabricates pagination.

### F1

**Space folder discovery — I.** No inputs; `Items[Folder]` preserves IDs, names, counts, and recursive folders, including Craft's built-in locations. Folder mutations remain deferred and are counted independently.

### L1

**Space document discovery — P (reference ambiguity).** `DocumentFilters` forwards mutually exclusive `location`/`folderId`, `fetchMetadata=false` by default, and `createdDateGte/Lte`, `lastModifiedDateGte/Lte`, `dailyNoteDateGte/Lte`. Listing with daily-note bounds requires `location=daily_notes`. `Items[DocumentSummary]` preserves title/ID, daily-note date, timestamps, and navigation links when supplied. API IDs are not extracted from navigation links.

**Open contract differences:** the local reference describes recursive folder inclusion, while wrapper documentation records direct documents only. Reverify before claiming parity. `documentIds` appears in exclusion prose but is absent from the formal parameter list; the wrapper does not invent that listing filter.

### L2

**Multi-Document document discovery — I.** `DocumentsFilters` exposes the sole documented query flag, `fetchMetadata=false` by default. Its distinct `Items[DocumentSummary]` preserves required `id`, `title`, `isDeleted`, and optional timestamps/navigation links. Deleted entries remain in the result. Space location/folder/date filters are rejected.

### S1

**Space/Multi-Document cross-document search — P.** A nonempty plain `query` maps to `include`; optional `fetchBlocks=false` returns `Items[DocumentSearchHit]` with snippets, document IDs, block IDs, and optional `Block` objects. Space accepts one of location/folder/document and the six date bounds; singular folder/document IDs map to `folderIds`/`documentIds`. Its daily-note bounds need no location selector. Multi-Document accepts one document ID plus include/exclude mode, with include defaulted only when an ID is present; Space-specific filters are rejected.

**Gaps:** array include/scope filters and `regexps` are not exposed. The reference's RE2/lookaround claims conflict and array serialization is unspecified. Craft describes relevance-ranked top-20 search; the wrapper preserves the returned list without truncating extra or repeated hits or treating it as an exhaustive inventory.

### S2

**Daily Notes search — P.** `DailySearchFilters` forwards `query` as `include`, optional start/end dates, and `fetchBlocks=false`, returning `Items[DailyNoteSearchHit]` with `dailyNoteDate` rather than document ID.

**Gaps:** array include and regex modes are not exposed. The same relevance-limit and no-pagination caveats as S1 apply; `/blocks/search` is a separate deferred operation.

### D1

**Space document creation — P.** `CreateDocument` wraps one title in `documents`; optional folder maps to `destination:{folderId}`, or `unsorted|templates` maps to `destination:{destination}`. Unspecified destination uses Craft's default. Returns one `DocumentSummary` and inserts no content implicitly.

**Gap:** documented batch creation is not exposed. Other adapters have no documented document-creation operation and remain N/A.

### T1

**Daily Notes task discovery — I.** `TaskFilters` requires one of active/upcoming/inbox/logbook and returns `Items[Task]` with ID, optional Markdown, and optional state/schedule/deadline information. Returned state strings remain unchanged. Space's document/all scopes are not Daily Notes gaps; they belong to its separately deferred task endpoint.

### T2

**Daily Notes task creation — P.** `AddTask` accepts Markdown, inbox/daily-note target, and optional schedule/deadline dates. A daily-note target defaults its date to today; inbox plus date and explicit nulls are rejected. It maps to `tasks:[{markdown,location,taskInfo?}]` and unwraps `Task`; date fields are nested in `taskInfo`.

**Gap/boundaries:** documented batch input is restricted to one task. Creation-state overrides and other task fields are not exposed; unsupported fields must be verified against an explicit upstream contract before expansion.

### T3

**Daily Notes task updates — P.** `UpdateTask` requires at least one of Markdown, todo/done/canceled state, schedule date, or deadline date. PATCH maps to `tasksToUpdate:[{id,markdown?,taskInfo?}]`; partial `Task` results are accepted. Nulls and empty updates are rejected.

**Gap/boundaries:** no documented batch shape exposed; movement and date clearing are unsupported and need explicit upstream verification rather than inferred null semantics.

### T4

**Daily Notes task deletion — P.** One task ID maps to `{idsToDelete:[taskId]}`; the singleton `Items[DeletedTask]` response is unwrapped to `{id}`. Lost, oversized, or malformed write responses retain uncertain-outcome errors.

**Gap:** upstream multiple-ID deletion is not exposed. Deletion has no automatic retry or promised rollback.

## Deferred operation groups

The D cells above have no public operation IDs or wrapper request/response models. Use each adapter's local reference for exact parameters, bodies, and outputs before implementation. Shared paths alone do not justify shared contracts.

| Group | Planning and verification requirements |
|---|---|
| Block/document/item deletion and movement | Verify target types, allowed destinations, scope filtering, batch outcomes, and uncertain write handling. Document/folder organization exists only in Space. |
| Folder mutations | Verify built-in-location restrictions, nesting, and deletion prerequisites; do not resolve conflicting deletion prose by guessing. |
| Collection creation/schema replacement | Verify property types and position selectors. Replacement must preserve intended fields/keys; never silently migrate existing data. |
| Collection views | Implement stored configuration and active-view behavior, not query execution. Verify table/gallery/kanban schemas and last-view deletion restrictions. |
| Connection info | Verify metadata/timezone/link-template shapes per adapter; never expose connection credentials. |
| In-document search | Preserve Space `blockId`, Multi-Document `documentId`, and Daily Notes `date` selectors. Verify regex semantics and context limits. |
| Comments | The references document adding comments, not a general comment CRUD API. |
| Space tasks | Implement all six scopes, including document/all, with Space-specific locations. `all` is broader than the union of the four Daily Notes scopes. |
| Reminders | Verify availability/ownership and required connection authorization separately; implement documented cursors and invalid-cursor behavior explicitly. |
| Uploads | Verify binary content negotiation and query fields; revisit appropriate limits without silently truncating payloads. |
| Whiteboards | Verify creation positions, element/assets/appState shapes, limits, and mutation semantics. |

## Verification evidence

These links identify automated regression coverage already present in the repository; they do not assert a fresh full-suite run or exhaustive live verification in this documentation audit. Deferred modes have no coverage claim. Use synthetic fixtures, HTTPX MockTransport, and in-process ASGI tests; no live credentials are needed for these suites.

| Contracts | Existing evidence |
|---|---|
| All Space mappings, including F1/L1/D1 | [test_space_api.py](tests/test_space_api.py): `test_all_endpoint_contracts`, document/read/edit and collection workflows; [test_space_client.py](tests/test_space_client.py): singleton/destination/query encoding and parsing cases. |
| All Multi-Document mappings, including L2/C5/S1 | [test_documents_api.py](tests/test_documents_api.py): `test_operation_contracts`, invalid filters, string boundary, connection isolation; [test_documents_client.py](tests/test_documents_client.py): include/exclude/default forwarding, deletion status, metadata, opaque IDs. |
| All Daily Notes mappings, including C6/S2/T1–T4 | [test_daily_api.py](tests/test_daily_api.py): `test_daily_operation_contracts`, invalid queries/writes, task scopes, uncertain singleton results, client isolation; [test_daily_client.py](tests/test_daily_client.py): ID encoding and selector separation. |
| B1/C1/C4 modeled responses and S1 result preservation | [test_space_api.py](tests/test_space_api.py): nested rows/previews, dynamic values/date strings; [test_space_client.py](tests/test_space_client.py): option objects, sparse schemas, malformed rows, known-field projection, extra/repeated search results. Names containing `live` still use mocks. |
| Public tool mappings/workflows | [test_openwebui_tool.py](tests/test_openwebui_tool.py): exact 13/11/17 function sets, all mappings, Daily Notes date/task workflow, validation forwarding and permissions. |
| Configuration/OpenAPI | [test_openapi.py](tests/test_openapi.py), [test_documents_api.py](tests/test_documents_api.py), [test_daily_api.py](tests/test_daily_api.py): configured-adapter route sets, presets, 404s for disabled routes, all seven connection combinations, bearer auth, valid OpenAPI, secret redaction. |
| Shared transport/errors | [test_transport.py](tests/test_transport.py): deadlines, phase/network failures, decoding, size limits, sanitized error mapping, Retry-After, and no retries. |

Existing live-probe scope and caveats are recorded in [README](README.md#tests-and-checks). No live Craft requests were made while building this matrix. A model/tool report alone does not establish upstream correctness or automatic-task outcomes.

## Keeping the matrix current

For each capability change, update the endpoint status, public mapping, contract notes, and regression evidence together. Recount pairs per adapter and compare every public operation ID/path with routes, presets, and standalone tools. Record the new audit date/code baseline and the reference retrieval date when known. Keep snapshot comparisons separate from deployment verification: a configured server's `/openapi.json` shows only its enabled operations.

Operation presence is complete only when no applicable D rows remain. Full documented-contract support additionally requires resolving P rows and validating response/input variants; intentional restrictions must remain visible rather than being counted as complete. Add new upstream endpoints to the inventory before revising a completeness claim. Permission profiles, factories, and reusable content shapes are separate roadmap work, not substitutes for upstream endpoint coverage.

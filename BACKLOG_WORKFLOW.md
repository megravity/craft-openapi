# Reviewed Backlog Migration

Use an existing Craft collection for undated planning items and native tasks for scheduled execution. This workflow is reviewed and performed one item at a time; the wrapper has no migration executor, durable progress store, transaction, or automatic synchronization.

## Prepare the collection

Create the backlog manually in Craft. For the current wrapper, start with the default built-in **Title** column: collection creation still sends a hardcoded top-level title and reads do not normalize named headlines. HTTP title-update probes now pass for default/named columns when using the actual schema key, but schema-aware mapping and public title-editing routes are not implemented yet. Do not assume named-column compatibility from the MCP's dynamic property handling.

Add text columns for **Source task ID** and, optionally, **Scheduled task ID**. Status and priority columns can use existing select options. Keep original task text in a text property if needed. Inspect `get_collection_schema` and use actual property keys, not assumed display names. Collection writes accept strings; the upstream validates legal values. Relations, complex writes, schema changes, and automatic collection creation remain outside this workflow.

Record the collection ID in the migration profile, set a near-term expiration, and use its own credential. The migration profile can read selected adapters but can only add rows to this one collection. Planner and migration tools must not share credentials. See [profile setup](PROFILES.md).

## Review and copy

1. Use Space `list_tasks` with `scope=all` to inventory native tasks, or `scope=document` with a project document ID. `all` includes unscheduled document tasks and is broader than the Daily scopes.
2. Read the backlog schema and existing rows. Identify the Source task ID property and existing source IDs.
3. Review an explicit list of task IDs, proposed row titles, status, and other properties. Keep scheduled tasks native; recurring-task handling is not implemented, so eligibility is a human decision.
4. Skip source IDs already present. Copy each approved task using `add_collection_item`, storing its original ID in the text property. Retain original content through the reviewed mapping; do not silently discard meaningful task text.
5. Re-read rows to verify the created row/title/properties and source ID. Stop on uncertain outcomes; inspect the collection before trying again.
6. Keep all source tasks unchanged. Review the completed copy, then revoke or let migration access expire. Removing/retiring originals is a separate explicitly authorized activity.

Source IDs help a person or agent check for duplicates; they do not create a server-enforced uniqueness constraint. Concurrent or repeated additions can still duplicate rows. The wrapper never retries writes automatically.

## Everyday scheduling

Keep the collection row as the planning record. When scheduled work should appear in native tasks, create a task through the Daily tool with an inbox/daily-note target and schedule/deadline fields. Store its returned ID in the Scheduled task ID text property and record the backlink to the backlog row in task Markdown if useful.

After completing/canceling the native task, explicitly update the row's status. Treat those as separate calls, verify their results, and report partial completion instead of claiming synchronization. Task dates are not timed reminders.

The unreleased Space adapter can create, reschedule, edit, complete/cancel, and delete native tasks within approved planning documents. Creation includes documentId in the body; updates/deletion require owning documentId query context and fresh structural/native-task membership checks. Only leaf tasks can be deleted. Keep inbox/daily-note writes on the Daily tool. Installed-tool checks passed creation, rescheduling, completion in place, canceled/approved deletion, and unapproved-root denial; see [verification observations](PROFILES.md#verification-observations--2026-10-07). Movement, date clearing, collection-title editing, and nested row-note editing remain unsupported. Do not retire MCP for workflows the pilot has not covered.

## Acceptance before retiring MCP

Verify profile discovery, backlog creation/property updates, scheduled task create/reschedule/complete, and a deletion dialog against authorized scratch data. Confirm foreign targets and expired migration access are denied and no source task changes occur during copy.

Automated scenarios use synthetic fixtures and mocked Craft responses. They verify request mappings, target/credential isolation, copy-only behavior, duplicate-review checks, read-back verification, and uncertain outcomes; live data changes require separate authorization.

# Craft – Full Space API

**Version:** 1.0.0

## Overview
The Craft Space API provides programmatic access to your entire Craft space - the top-level container for all your documents and organizational structure.

## Space Structure
A Craft space organizes content through:
- **Folders**: Hierarchical folders to organize documents
- **Documents**: Individual documents within locations
- **Blocks**: The content within documents (text, pages, collections, media)
- **Tasks**: Task management across inbox, daily notes, and documents

## Key Concepts
**Locations**: Documents exist in locations. A location is either a folder or one of the built-in locations: 'unsorted' (default for new documents), 'templates' (documents shown in Craft's Templates area and usable in-app to create new documents), or 'trash' (recently deleted).

**Document IDs**: A document ID is the same as its root block ID. Use a document ID with `GET /blocks` to fetch the document's content.

**Space Discovery**: Use `GET /folders` to see all locations, then `GET /documents` to list documents within a specific location.

**Document Organization**: Documents can be created in, moved between, and deleted from locations. Use folder and document management endpoints to organize your space.

**Tasks**: Tasks can be managed across the space. Use `GET /tasks` with scope filters (inbox, active, upcoming, logbook) to retrieve tasks, and other task endpoints to create, update, or delete them.

## Rate Limits
Rate limits apply at both public IP and Craft space scopes. The first limit reached returns HTTP `429`.

| Limit | Scope | Allowance |
|-------|-------|-----------|
| API requests | Public source IP, shared across API links and MCP connections | 50 requests per 10 seconds |
| API requests | Craft space | 100 requests per 60 seconds |
| Blocks read or written | Craft space | 20,000 blocks per 60 seconds |

Clients behind the same public IP share the per-IP limit. Space limits are shared across all API links, MCP connections, and clients in that space; they are not allocated separately per link or session. Each paginated request and retry counts separately.

Application responses expose the Craft space request budget, when available, through `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset`. Responses rejected at the public-IP limit may omit these headers.

REST block operations expose the corresponding `X-BlockBudget-*` headers after the space has recorded block usage in the current window; the first read in a new window may omit them. MCP responses do not expose the block budget as HTTP headers.

Application-generated HTTP `429` responses include `Retry-After`. MCP request-limit responses also repeat the retry delay in the error message because some MCP clients do not expose response headers. If `Retry-After` is absent, use exponential backoff with jitter.

## Reminders
Block reminders are experimental. With a Craft OAuth connection, reminders belong to the signed-in user and are available in single-user and multi-user spaces. With an ordinary link, reminders belong to the link creator and require that creator to be the space's only active participant. Document scope always applies; custom (blockless) reminders are not exposed.

Unavailable reminder endpoints are omitted from this documentation. Direct requests return an explicit availability error. Task dates notify in-app; they are not a substitute for a requested timed reminder. A reminder can schedule a notification on any block, or save it for later without a notification. These operations are available only under the conditions above.

## Craft Link Formats
| Type | Format | Description |
|------|--------|-------------|
| `clickableLink` | `craftdocs://open?spaceId={spaceId}&documentId={documentId}` | Returned in document metadata when `fetchMetadata=true`. |
| Web editor | https://docs.craft.do/editor/d/{spaceId}/{documentId} | Construct using the `spaceId` and `documentId` values from `clickableLink`. |

## Craft Markdown Extensions
The `markdown` field on blocks uses standard Markdown with the following Craft-specific extensions. These tags can appear in both input (when creating/updating blocks) and output (when reading blocks), unless noted otherwise.

### Page Structure
| Tag | Description |
|-----|-------------|
| `<page>...<\/page>` | A nested page (sub-document). Optional attributes: `textStyle` (e.g. `"card"`), `cardLayout`, `id`. |
| `<card>...<\/card>` | Shorthand for `<page textStyle="card">`. |
| `<pageTitle>...<\/pageTitle>` | The title of a `<page>`. Always the first child inside `<page>`. |
| `<content>...<\/content>` | The body content of a `<page>`, following `<pageTitle>`. |

### Block-Level Formatting
| Tag | Description |
|-----|-------------|
| `<callout>...<\/callout>` | Wraps blocks in a visually distinct callout box (similar to an admonition or aside). |
| `<caption>...<\/caption>` | Renders text in a smaller, muted caption style. |

### Inline Formatting
| Tag | Description |
|-----|-------------|
| `<highlight color="...">...<\/highlight>` | Colored text highlight. Colors: yellow, green, mint, cyan, blue, purple, pink, red, gray, gradient-blue, gradient-purple, gradient-red, gradient-yellow, gradient-brown. |
| `==text==` | Shorthand for `<highlight color="yellow">`. |
| `<comment id="...">...<\/comment>` | Marks text that has a comment thread attached. The `id` references the comment thread. |
| `$formula$` or `$$formula$$` | LaTeX math formula, rendered inline or as a block. |

### Links and Indentation
| Syntax | Description |
|--------|-------------|
| `[text](block://blockId)` | Cross-reference to another block by ID. Appears as `[text](invalid:out_of_scope)` when the target block is outside the current API scope. |
| `[text](date://YYYY-MM-DD)` | Link to a daily note for the given date. |
| 2+ leading spaces | Nesting level. Every 2 spaces represents one level of indentation. |

### Collection Tags (output-only)
These tags appear only in responses, when the result contains collection data. They are not accepted as input.

| Tag | Description |
|-----|-------------|
| `<collection>...<\/collection>` | A collection (structured database). Contains `<title>`, `<properties>`, and either `<content>` (with items) or `<itemsPreview>`. |
| `<title>...<\/title>` | The name of a collection or collection item. |
| `<properties>...<\/properties>` | Comma-separated list of property (column) keys defined on the collection. |
| `<collectionItem>...<\/collectionItem>` | A single row/item in a collection. Contains `<property>` tags, a `<title>`, and optionally `<content>` or `<contentPreview>`. |
| `<property name="key">value<\/property>` | A property value on a collection item, where `name` is the property key. |
| `<contentPreview>...<\/contentPreview>` | A truncated preview of nested content, included when the response depth limit is reached instead of the full `<content>`. |
| `<itemsPreview>...<\/itemsPreview>` | A truncated preview of collection items, included when the response depth limit is reached instead of the full item list. |

## Development Tips
- Start with `GET /folders` to discover all locations in the space
- Use `GET /documents` with a location filter to list documents in a specific location
- Create new locations with `POST /folders`
- Use `POST /documents` to create new documents in a specific location
- Access document content with `GET /blocks?id={documentId}`
- Search across the entire space with `GET /documents/search`
- Use `PUT /documents/move` to move documents between locations
- Manage tasks with `GET /tasks?scope=active` to retrieve due tasks, or use other scopes (inbox, upcoming, logbook)

## Note for AI
When implementing functionality using this API, always make actual calls to these endpoints and verify the responses. Do not simulate or mock the API interactions or use hard-coded values on the client-side - use the real endpoints to ensure proper functionality and data handling.

**IMPORTANT: This is a production server connected to real user data.** Only perform testing operations that can be safely rolled back:

- Safe: Reading data (`GET` requests), creating test content that you delete immediately after
- Safe: Modifying content if you can restore it to its original state
- Safe: Moving blocks if you can move them back to their original position
- Unsafe: Permanent deletions, modifications without backup, or any changes you cannot reverse

Always verify rollback operations work before considering a test complete.

## Servers

- https://connect.craft.do/links/{secretLinkId}/api/v1
  API Server for Full Space

---

# Endpoints

# Fetch Blocks

`GET /blocks`

Fetches content from any document in the space. Use 'id' query parameter to specify which block to fetch.

Use `Accept` header `application/json` for structured data, `text/markdown` for rendered content.

**Content Rendering:** Text blocks contain markdown formatting and may include Craft-specific structural tags (e.g. `<page>`, `<callout>`, `<highlight>`). See the **Craft Markdown Extensions** section in the API description for the full list of tags.

**Full Space Access:** This connection has access to all documents across all locations in the space. Block links and relations within the space are preserved.

**Tip:** Start with GET /folders to see all locations, then GET /documents to list documents by location. Use the returned rootBlockIds as the 'id' parameter to fetch content.

## Parameters

- **date** (query): string
  Fetches the root page of a Daily Note for the specified date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
Mutually exclusive with 'id' - use this to fetch a Daily Note's root page, or use 'id' to fetch a specific block.
- **id** (required) (query): string
  Fetches a specific page block by its ID. Use this when you want to retrieve a particular block directly.
Mutually exclusive with 'date' - omit 'date' entirely when using this parameter.
- **maxDepth** (query): number
  The maximum depth of blocks to fetch. Default is -1 (all descendants). With a depth of 0, only the specified block is fetched. With a depth of 1, only direct children are returned.
- **fetchMetadata** (query): boolean
  Whether to fetch metadata (comments, createdBy, lastModifiedBy, lastModifiedAt, createdAt) for the blocks. Default is false.

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`

```json
{
  "id": "0",
  "type": "page",
  "textStyle": "page",
  "markdown": "<page>Document Title</page>",
  "content": [
    {
      "id": "1",
      "type": "text",
      "textStyle": "h1",
      "markdown": "# Main Section"
    },
    {
      "id": "2",
      "type": "text",
      "markdown": "This is some content in the document."
    },
    {
      "id": "3",
      "type": "page",
      "textStyle": "card",
      "markdown": "Subsection",
      "content": [
        {
          "id": "4",
          "type": "text",
          "markdown": "Nested content inside subsection."
        }
      ]
    }
  ]
}
```

---

# Insert Blocks

`POST /blocks`

Insert content into any document in the space. Content can be provided as structured JSON blocks. Use position parameter to specify where to insert (via parent blockId, sibling blockId, or daily-note date). Returns the inserted blocks with their assigned block IDs for later reference.

## Request Body

**Content-Type:** `application/json`


**Example: textBlock**

Insert block into document

```json
{
  "blocks": [
    {
      "type": "text",
      "markdown": "## Section Header\n\nContent."
    }
  ],
  "position": {
    "position": "end",
    "pageId": "doc-123"
  }
}
```


**Example: markdown**

Insert markdown into daily note

```json
{
  "markdown": "## Meeting Notes\n\nDiscussed topics",
  "position": {
    "position": "end",
    "date": "today"
  }
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "15",
      "type": "text",
      "textStyle": "body",
      "markdown": "## Second Level Header\n\n- **List Item A**: Description text\n- **List Item B**: Description text"
    },
    {
      "id": "16",
      "type": "image",
      "url": "https://res.luki.io/user/full/space-id/doc/doc-id/uuid",
      "altText": "Alt text for accessibility",
      "markdown": "![Image](https://res.luki.io/user/full/space-id/doc/doc-id/uuid)"
    }
  ]
}
```

---

# Delete Blocks

`DELETE /blocks`

Delete content from any document in the space. Removes specified blocks by their IDs.

## Request Body

**Content-Type:** `application/json`

```json
{
  "blockIds": [
    "7",
    "9",
    "12"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "7"
    },
    {
      "id": "9"
    },
    {
      "id": "12"
    }
  ]
}
```

---

# Update Blocks

`PUT /blocks`

Update content in any document in the space. For text blocks, provide updated markdown content. Only the fields that are provided will be updated.

## Request Body

**Content-Type:** `application/json`

```json
{
  "blocks": [
    {
      "id": "5",
      "markdown": "## Updated Section Title\n\nThis content has been updated with new information.",
      "font": "serif"
    },
    {
      "id": "8",
      "markdown": "# New Heading"
    }
  ]
}
```

## Responses

### 200
Successfully updated resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "5",
      "type": "text",
      "textStyle": "body",
      "markdown": "## Updated Section Title\n\nThis content has been updated with new information.",
      "font": "serif"
    },
    {
      "id": "8",
      "type": "text",
      "textStyle": "h2",
      "markdown": "# New Heading"
    }
  ]
}
```

---

# Move Blocks

`PUT /blocks/move`

Move blocks to reorder them or move them between any documents across all locations in the space. Returns the moved block IDs.

## Request Body

**Content-Type:** `application/json`


**Example: moveToDoc**

Move blocks to document

```json
{
  "blockIds": [
    "5",
    "6"
  ],
  "position": {
    "position": "end",
    "pageId": "doc-123"
  }
}
```


**Example: moveToDailyNote**

Move blocks to daily note

```json
{
  "blockIds": [
    "7",
    "8"
  ],
  "position": {
    "position": "end",
    "date": "today"
  }
}
```

## Responses

### 200
Successfully moved resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "5"
    },
    {
      "id": "6"
    }
  ]
}
```

---

# Get Collection Items

`GET /collections/{collectionId}/items`

Get all items from a collection

## Parameters

- **maxDepth** (query): number
  The maximum depth of nested content to fetch for each collection item. Default is -1 (all descendants). With a depth of 0, only the item properties are fetched without nested content.
- **collectionId** (required) (path): string

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "item1",
      "title": "Task 1",
      "properties": {
        "status": "In Progress",
        "priority": "High",
        "assignee": "John Doe"
      },
      "content": [
        {
          "id": "1",
          "type": "text",
          "markdown": "Detailed description of the task."
        }
      ]
    },
    {
      "id": "item2",
      "title": "Task 2",
      "properties": {
        "status": "Done",
        "priority": "Low",
        "assignee": "Jane Smith"
      }
    }
  ]
}
```

---

# Add Collection Items

`POST /collections/{collectionId}/items`

Add new items to a collection. Two-way relations are synced automatically in the background - only set one side for consistency.

## Parameters

- **collectionId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "title": "Space Task",
      "properties": {
        "status": "Todo",
        "priority": "High"
      }
    }
  ]
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "item3",
      "title": "New Task",
      "properties": {
        "status": "Todo",
        "priority": "Medium"
      }
    }
  ]
}
```

---

# Delete Collection Items

`DELETE /collections/{collectionId}/items`

Delete collection items (also deletes content inside items)

## Parameters

- **collectionId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "idsToDelete": [
    "item1",
    "item2",
    "item3"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "item1"
    },
    {
      "id": "item2"
    },
    {
      "id": "item3"
    }
  ]
}
```

---

# Update Collection Items

`PUT /collections/{collectionId}/items`

Update collection items. Two-way relations are synced automatically in the background - only set one side for consistency.

## Parameters

- **collectionId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "itemsToUpdate": [
    {
      "id": "item1",
      "properties": {
        "status": "Done"
      }
    }
  ]
}
```

## Responses

### 200
Successfully updated resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "item1",
      "title": "Updated Task",
      "properties": {
        "status": "Done",
        "priority": "High"
      }
    }
  ]
}
```

---

# Set Active Collection View

`PUT /collections/{collectionId}/active-view`

Set the collection-level activeViewId to one existing collection view ID. This only changes which stored view is marked active; it does not execute the view or change collection items.

## Parameters

- **collectionId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "viewId": "view-board"
}
```

## Responses

### 200
Success

**Content-Type:** `application/json`

```json
{
  "id": "view-board",
  "name": "Delivery Board",
  "type": "kanban",
  "filters": [],
  "sortBy": [],
  "groupBy": [
    {
      "propertyId": "prop_status",
      "propertyKey": "status",
      "propertyName": "Status",
      "ascending": true
    }
  ],
  "hiddenProperties": [],
  "customPropertyOrder": [],
  "columnWidth": {},
  "calculations": {},
  "kanban": {
    "columnOrder": [
      "Todo",
      "Doing",
      "Done"
    ]
  },
  "isActive": true
}
```

---

# List Collection Views

`GET /collections/{collectionId}/views`

List table, gallery, and kanban view definitions for a collection. This returns configuration only; it does not execute filters/sorts/groups or return collection items. If activeViewId is missing or invalid, the first stored view is treated as active.

## Parameters

- **collectionId** (required) (path): string

## Responses

### 200
Success

**Content-Type:** `application/json`

```json
{
  "collectionBlockId": "collection1",
  "activeViewId": "view-board",
  "views": [
    {
      "id": "view-table",
      "name": "Table",
      "type": "table",
      "filters": [],
      "sortBy": [],
      "groupBy": [],
      "hiddenProperties": [],
      "customPropertyOrder": [],
      "columnWidth": {},
      "calculations": {},
      "isActive": false
    },
    {
      "id": "view-board",
      "name": "Delivery Board",
      "type": "kanban",
      "filters": [],
      "sortBy": [],
      "groupBy": [
        {
          "propertyId": "prop_status",
          "propertyKey": "status",
          "propertyName": "Status",
          "ascending": true
        }
      ],
      "hiddenProperties": [],
      "customPropertyOrder": [],
      "columnWidth": {},
      "calculations": {
        "prop_estimate": {
          "propertyId": "prop_estimate",
          "propertyKey": "estimate",
          "propertyName": "Estimate",
          "type": "number_sum"
        }
      },
      "isCalculationsRowVisible": true,
      "kanban": {
        "columnOrder": [
          "Todo",
          "Doing",
          "Done"
        ],
        "visibleFields": [
          {
            "propertyId": "prop_owner",
            "propertyKey": "owner",
            "propertyName": "Owner"
          }
        ]
      },
      "isActive": true
    }
  ]
}
```

---

# Create Collection View

`POST /collections/{collectionId}/views`

Create a collection view definition. Use type table for the regular/default table layout, gallery for card layouts, or kanban for grouped boards. This creates configuration only; it does not create or return collection items. Kanban requires exactly one group rule.

## Parameters

- **collectionId** (required) (path): string

## Request Body

**Content-Type:** `application/json`


**Example: kanban**

Create a kanban collection view

Creates a stored view definition only. Kanban views require exactly one groupBy rule; collection items are fetched through the item endpoints.

```json
{
  "view": {
    "name": "Delivery Board",
    "type": "kanban",
    "filters": [
      {
        "property": "status",
        "filterType": "select_isNoneOf",
        "filterValue": [
          "Done"
        ]
      }
    ],
    "sortBy": [
      {
        "property": "dueDate",
        "ascending": true
      }
    ],
    "groupBy": [
      {
        "property": "status",
        "ascending": true
      }
    ],
    "fields": {
      "order": [
        "title",
        "status",
        "owner",
        "estimate"
      ],
      "hidden": [
        "notes"
      ],
      "widths": {
        "estimate": "120"
      }
    },
    "calculations": {
      "estimate": "number_sum",
      "owner": "count_unique"
    },
    "isCalculationsRowVisible": true,
    "kanban": {
      "columnOrder": [
        "Todo",
        "Doing",
        "Done"
      ],
      "hiddenGroupValues": [
        "Archived"
      ],
      "showsColumnColors": true,
      "visibleFields": [
        "owner",
        "estimate"
      ]
    }
  }
}
```


**Example: gallery**

Create a gallery collection view

Creates a stored gallery view definition only. The gallery object is only valid when type is gallery.

```json
{
  "view": {
    "name": "Gallery",
    "type": "gallery",
    "sortBy": [
      {
        "property": "created",
        "ascending": false
      }
    ],
    "gallery": {
      "cardSize": "large",
      "previewType": "fill",
      "visibleFields": [
        "status",
        "owner"
      ]
    }
  }
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "id": "view1",
  "name": "Delivery Board",
  "type": "kanban",
  "filters": [
    {
      "propertyId": "prop_status",
      "propertyKey": "status",
      "propertyName": "Status",
      "filterType": "select_isNoneOf",
      "filterValue": [
        "status-done"
      ]
    }
  ],
  "sortBy": [
    {
      "propertyId": "prop_due",
      "propertyKey": "dueDate",
      "propertyName": "Due Date",
      "ascending": true
    }
  ],
  "groupBy": [
    {
      "propertyId": "prop_status",
      "propertyKey": "status",
      "propertyName": "Status",
      "ascending": true
    }
  ],
  "hiddenProperties": [
    {
      "propertyId": "prop_notes",
      "propertyKey": "notes",
      "propertyName": "Notes"
    }
  ],
  "customPropertyOrder": [
    {
      "propertyId": "com.craft.title",
      "propertyKey": "title",
      "propertyName": "Title"
    },
    {
      "propertyId": "prop_status",
      "propertyKey": "status",
      "propertyName": "Status"
    },
    {
      "propertyId": "prop_owner",
      "propertyKey": "owner",
      "propertyName": "Owner"
    },
    {
      "propertyId": "prop_estimate",
      "propertyKey": "estimate",
      "propertyName": "Estimate"
    }
  ],
  "columnWidth": {
    "estimate": "120"
  },
  "calculations": {
    "prop_estimate": {
      "propertyId": "prop_estimate",
      "propertyKey": "estimate",
      "propertyName": "Estimate",
      "type": "number_sum"
    },
    "prop_owner": {
      "propertyId": "prop_owner",
      "propertyKey": "owner",
      "propertyName": "Owner",
      "type": "count_unique"
    }
  },
  "isCalculationsRowVisible": true,
  "kanban": {
    "columnOrder": [
      "Todo",
      "Doing",
      "Done"
    ],
    "hiddenGroupValues": [
      "Archived"
    ],
    "showsColumnColors": true,
    "visibleFields": [
      {
        "propertyId": "prop_owner",
        "propertyKey": "owner",
        "propertyName": "Owner"
      },
      {
        "propertyId": "prop_estimate",
        "propertyKey": "estimate",
        "propertyName": "Estimate"
      }
    ]
  },
  "isActive": true
}
```

---

# Delete Collection View

`DELETE /collections/{collectionId}/views/{viewId}`

Delete one collection view definition by view ID. Cannot delete the last stored view in a collection. If the active view is deleted, the first remaining stored view becomes active.

## Parameters

- **collectionId** (required) (path): string
- **viewId** (required) (path): string

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "deletedViewId": "view-board",
  "activeViewId": "view-table"
}
```

---

# Update Collection View

`PUT /collections/{collectionId}/views/{viewId}`

Update one collection view definition by view ID. Omitted settings are preserved. Pass empty arrays or objects to clear list-like settings. Gallery settings are only valid for gallery views; kanban settings are only valid for kanban views.

## Parameters

- **collectionId** (required) (path): string
- **viewId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "view": {
    "name": "Delivery Board",
    "sortBy": [
      {
        "property": "dueDate",
        "ascending": true
      }
    ],
    "kanban": {
      "columnOrder": [
        "Todo",
        "Doing",
        "Done"
      ],
      "showsColumnColors": true
    }
  }
}
```

## Responses

### 200
Successfully updated resource

**Content-Type:** `application/json`

```json
{
  "id": "view-board",
  "name": "Delivery Board",
  "type": "kanban",
  "filters": [],
  "sortBy": [
    {
      "propertyId": "prop_due",
      "propertyKey": "dueDate",
      "propertyName": "Due Date",
      "ascending": true
    }
  ],
  "groupBy": [
    {
      "propertyId": "prop_status",
      "propertyKey": "status",
      "propertyName": "Status",
      "ascending": true
    }
  ],
  "hiddenProperties": [],
  "customPropertyOrder": [],
  "columnWidth": {},
  "calculations": {},
  "kanban": {
    "columnOrder": [
      "Todo",
      "Doing",
      "Done"
    ],
    "showsColumnColors": true
  },
  "isActive": true
}
```

---

# List Collections

`GET /collections`

List all collections across the entire space. Returns collections from all documents regardless of their location.

## Parameters

- **documentIds** (query): string
  The document IDs to filter. If not provided, collections in all documents will be listed. Can be a single string or array of strings.

## Responses

### 200
Success

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "col1",
      "name": "Tasks",
      "itemCount": 5,
      "documentId": "doc1"
    },
    {
      "id": "col2",
      "name": "Notes",
      "itemCount": 3,
      "documentId": "doc2"
    }
  ]
}
```

---

# Create Collection

`POST /collections`

Create a new collection (structured table) in any document in the space. Define the schema with columns and their types.

## Request Body

**Content-Type:** `application/json`

```json
{
  "schema": {
    "name": "Tasks",
    "contentPropDetails": {
      "name": "Title"
    },
    "properties": [
      {
        "name": "Status",
        "type": "singleSelect",
        "options": [
          {
            "name": "Not Started"
          },
          {
            "name": "In Progress"
          },
          {
            "name": "Completed"
          }
        ]
      },
      {
        "name": "Priority",
        "type": "singleSelect",
        "options": [
          {
            "name": "Low"
          },
          {
            "name": "Medium"
          },
          {
            "name": "High"
          }
        ]
      },
      {
        "name": "Due Date",
        "type": "date"
      }
    ]
  },
  "position": {
    "position": "end"
  }
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "collectionBlockId": "abc123",
  "name": "Tasks",
  "schema": {
    "name": "Tasks",
    "contentPropDetails": {
      "key": "title",
      "name": "Title"
    },
    "properties": [
      {
        "key": "status",
        "name": "Status",
        "type": "singleSelect",
        "options": [
          {
            "name": "Not Started",
            "color": "yellow"
          },
          {
            "name": "In Progress",
            "color": "sky-blue"
          },
          {
            "name": "Completed",
            "color": "mint-green"
          }
        ]
      },
      {
        "key": "priority",
        "name": "Priority",
        "type": "singleSelect",
        "options": [
          {
            "name": "Low",
            "color": "gray"
          },
          {
            "name": "Medium",
            "color": "yellow"
          },
          {
            "name": "High",
            "color": "red"
          }
        ]
      },
      {
        "key": "dueDate",
        "name": "Due Date",
        "type": "date"
      }
    ]
  }
}
```

---

# Get Collection Schema

`GET /collections/{collectionId}/schema`

Get collection schema in JSON Schema format

## Parameters

- **format** (query): string
  The format to return the schema in. Default: json-schema-items. - 'schema': Returns the collection schema structure that can be edited - 'json-schema-items': Returns JSON Schema for addCollectionItems/updateCollectionItems validation
- **collectionId** (required) (path): string

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`


**Example: schemaFormat**

Schema format response

```json
{
  "key": "tasks",
  "name": "Tasks",
  "contentPropDetails": {
    "key": "title",
    "name": "Title"
  },
  "properties": [
    {
      "key": "status",
      "name": "Status",
      "type": "select",
      "options": [
        "Not Started",
        "In Progress",
        "Completed"
      ]
    },
    {
      "key": "priority",
      "name": "Priority",
      "type": "select",
      "options": [
        "Low",
        "Medium",
        "High"
      ]
    },
    {
      "key": "dueDate",
      "name": "Due Date",
      "type": "date"
    }
  ],
  "propertyDetails": [
    {
      "key": "status",
      "name": "Status",
      "type": "select",
      "options": [
        "Not Started",
        "In Progress",
        "Completed"
      ]
    },
    {
      "key": "priority",
      "name": "Priority",
      "type": "select",
      "options": [
        "Low",
        "Medium",
        "High"
      ]
    },
    {
      "key": "dueDate",
      "name": "Due Date",
      "type": "date"
    }
  ]
}
```

**Example: jsonSchemaFormat**

JSON Schema format (for validation)

```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string",
            "description": "The title of the collection item"
          },
          "properties": {
            "type": "object",
            "properties": {
              "status": {
                "type": "string",
                "enum": [
                  "Not Started",
                  "In Progress",
                  "Completed"
                ],
                "description": "Status"
              },
              "priority": {
                "type": "string",
                "enum": [
                  "Low",
                  "Medium",
                  "High"
                ],
                "description": "Priority"
              },
              "dueDate": {
                "type": "string",
                "description": "Due Date"
              }
            }
          }
        },
        "required": [
          "title"
        ]
      }
    }
  },
  "required": [
    "items"
  ],
  "additionalProperties": false
}
```

---

# Update Collection Schema

`PUT /collections/{collectionId}/schema`

Update the collection schema. Replaces the existing schema entirely - include all fields you want to keep. Keep property keys stable for existing properties.

## Parameters

- **collectionId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "schema": {
    "name": "Tasks",
    "contentPropDetails": {
      "name": "Title"
    },
    "properties": [
      {
        "key": "status",
        "name": "Status",
        "type": "singleSelect",
        "options": [
          {
            "name": "Not Started"
          },
          {
            "name": "In Progress"
          },
          {
            "name": "Completed"
          },
          {
            "name": "Blocked"
          }
        ]
      },
      {
        "key": "priority",
        "name": "Priority",
        "type": "singleSelect",
        "options": [
          {
            "name": "Low"
          },
          {
            "name": "Medium"
          },
          {
            "name": "High"
          }
        ]
      },
      {
        "key": "dueDate",
        "name": "Due Date",
        "type": "date"
      },
      {
        "name": "Assignee",
        "type": "text"
      }
    ]
  }
}
```

## Responses

### 200
Successfully updated resource

**Content-Type:** `application/json`

```json
{
  "collectionBlockId": "abc123",
  "schema": {
    "name": "Tasks",
    "contentPropDetails": {
      "key": "title",
      "name": "Title"
    },
    "properties": [
      {
        "key": "status",
        "name": "Status",
        "type": "singleSelect",
        "options": [
          {
            "name": "Not Started",
            "color": "yellow"
          },
          {
            "name": "In Progress",
            "color": "sky-blue"
          },
          {
            "name": "Completed",
            "color": "mint-green"
          },
          {
            "name": "Blocked",
            "color": "red"
          }
        ]
      },
      {
        "key": "priority",
        "name": "Priority",
        "type": "singleSelect",
        "options": [
          {
            "name": "Low",
            "color": "gray"
          },
          {
            "name": "Medium",
            "color": "yellow"
          },
          {
            "name": "High",
            "color": "red"
          }
        ]
      },
      {
        "key": "dueDate",
        "name": "Due Date",
        "type": "date"
      },
      {
        "key": "assignee",
        "name": "Assignee",
        "type": "text"
      }
    ]
  }
}
```

---

# Add comments

`POST /comments`

Add comments to blocks.

## Request Body

**Content-Type:** `application/json`

```json
{
  "comments": [
    {
      "blockId": "abc123",
      "content": "This is a comment."
    }
  ]
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "commentId": "abc123-def456"
    }
  ]
}
```

---

# Get Connection Info

`GET /connection`

Returns connection metadata including space ID, space name, timezone, current time, and URL templates for constructing deep links to blocks.

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`

```json
{
  "space": {
    "id": "string",
    "name": "string",
    "timezone": "string",
    "time": "string",
    "friendlyDate": "string"
  },
  "utc": {
    "time": "string"
  },
  "urlTemplates": {
    "app": "string"
  }
}
```

---

# List Documents

`GET /documents`

List documents in the space. Without location or folderIds filters, returns ALL documents (may be large). Recommended: use GET /folders first to see available locations and document counts.

## Parameters

- **location** (query): string
  Filter by virtual location: 'unsorted', 'trash', 'templates', or 'daily_notes'. Cannot be used together with 'folderId' or 'documentIds'. If neither 'location' nor 'folderId' is specified, searches/lists all documents.
- **folderId** (query): string
  Filter by specific folder (includes subfolders recursively). Cannot be used together with 'location' or 'documentIds'. If neither 'location' nor 'folderId' is specified, lists all documents.
- **fetchMetadata** (query): boolean
  Whether to include metadata (lastModifiedAt, createdAt, clickableLink) in the response. Default is false.
- **createdDateGte** (query): string
  Only include documents created on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **createdDateLte** (query): string
  Only include documents created on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **lastModifiedDateGte** (query): string
  Only include documents modified on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **lastModifiedDateLte** (query): string
  Only include documents modified on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **dailyNoteDateGte** (query): string
  Only include daily notes on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **dailyNoteDateLte** (query): string
  Only include daily notes on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.

## Responses

### 200
Success

**Content-Type:** `application/json`


**Example: unsorted**

Documents in unsorted

```json
{
  "items": [
    {
      "id": "doc-123",
      "title": "Meeting Notes"
    },
    {
      "id": "doc-456",
      "title": "Project Ideas"
    }
  ]
}
```

**Example: dailyNotes**

Daily notes with dates

```json
{
  "items": [
    {
      "id": "dn-123",
      "title": "Wednesday, January 15, 2025",
      "dailyNoteDate": "2025-01-15"
    },
    {
      "id": "dn-456",
      "title": "Tuesday, January 14, 2025",
      "dailyNoteDate": "2025-01-14"
    }
  ]
}
```

**Example: withMetadata**

Documents with metadata

```json
{
  "items": [
    {
      "id": "doc-123",
      "title": "Meeting Notes",
      "lastModifiedAt": "2025-01-15T14:30:00Z",
      "createdAt": "2025-01-10T09:00:00Z",
      "clickableLink": "craftdocs://open?spaceId=space-uuid&documentId=doc-uuid-123"
    }
  ]
}
```

---

# Create Documents

`POST /documents`

Create one or more documents in the space. Specify location as 'unsorted' (default), 'templates' (in-app template docs), or provide a folderId. Cannot create in 'trash'.

## Request Body

**Content-Type:** `application/json`


**Example: unsorted**

Create documents in unsorted

```json
{
  "documents": [
    {
      "title": "New Document 1"
    },
    {
      "title": "New Document 2"
    }
  ]
}
```


**Example: folder**

Create documents in a folder

```json
{
  "documents": [
    {
      "title": "Project Plan"
    }
  ],
  "destination": {
    "folderId": "abc123"
  }
}
```


**Example: templates**

Create template documents

```json
{
  "documents": [
    {
      "title": "Weekly Report Template"
    }
  ],
  "destination": {
    "destination": "templates"
  }
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "doc-new-1",
      "title": "New Document 1",
      "clickableLink": "craftdocs://open?spaceId=space-uuid&documentId=doc-uuid-1"
    },
    {
      "id": "doc-new-2",
      "title": "New Document 2",
      "clickableLink": "craftdocs://open?spaceId=space-uuid&documentId=doc-uuid-2"
    }
  ]
}
```

---

# Delete Documents

`DELETE /documents`

Soft-delete documents by moving them to trash. Use documents_move to restore.

## Request Body

**Content-Type:** `application/json`

```json
{
  "documentIds": [
    "doc-123",
    "doc-456"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "items": [
    "doc-123",
    "doc-456"
  ]
}
```

---

# Move Documents

`PUT /documents/move`

Move documents between locations in the space. Destination cannot be 'trash' - use documents_delete instead. Use this to restore documents from trash. Note: Daily notes cannot be moved.

## Request Body

**Content-Type:** `application/json`


**Example: toFolder**

Move documents to a folder

```json
{
  "documentIds": [
    "doc-123",
    "doc-456"
  ],
  "destination": {
    "folderId": "abc123"
  }
}
```


**Example: toUnsorted**

Move documents to unsorted

```json
{
  "documentIds": [
    "doc-789"
  ],
  "destination": {
    "destination": "unsorted"
  }
}
```


**Example: restoreFromTrash**

Restore documents from trash

```json
{
  "documentIds": [
    "doc-deleted"
  ],
  "destination": {
    "destination": "unsorted"
  }
}
```

## Responses

### 200
Successfully moved resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "doc-123",
      "destination": {
        "folderId": "abc123"
      }
    },
    {
      "id": "doc-456",
      "destination": {
        "folderId": "abc123"
      }
    }
  ]
}
```

---

# List Reminders

`GET /reminders`

Experimental: list block reminders within this connection's document scope. See the Reminders section for availability and ownership.

## Parameters

- **status** (query): string
  List filter. Defaults to incomplete, including Save for later and overdue reminders. Upcoming includes incomplete reminders with a future time or no time (Save for later). All includes incomplete and completed reminders within this connection's scope.
- **limit** (query): integer
  Page size, defaults to 50. Results are ordered by creation time, then ID.
- **cursor** (query): string
  Continuation cursor from the previous response; keep the same status filter. If the cursor becomes invalid, restart without it.

## Responses

### 200
Success

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "string",
      "title": "string",
      "blockId": "string",
      "remindAt": "2024-01-01T00:00:00Z",
      "isCompleted": false,
      "completedAt": "2024-01-01T00:00:00Z"
    }
  ],
  "pagination": {
    "cursor": "string"
  }
}
```

---

# Create Reminders

`POST /reminders`

Experimental: set or replace reminders on blocks within this connection's document scope. Omit the time to Save for later.

## Request Body

**Content-Type:** `application/json`


**Example: scheduled**

Schedule a notification (replace the example block ID)

```json
{
  "reminders": [
    {
      "blockId": "00000000-0000-4000-8000-000000000001",
      "remindAt": "2030-01-15T10:00:00+01:00"
    }
  ]
}
```


**Example: saved**

Save for later without a notification

```json
{
  "reminders": [
    {
      "blockId": "00000000-0000-4000-8000-000000000001"
    }
  ]
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`


**Example: scheduled**

Scheduled reminder

```json
{
  "items": [
    {
      "id": "00000000-0000-4000-8000-000000000002",
      "blockId": "00000000-0000-4000-8000-000000000001",
      "title": "Call Alex",
      "isCompleted": false,
      "remindAt": "2030-01-15T09:00:00Z"
    }
  ]
}
```

**Example: saved**

Saved for later

```json
{
  "items": [
    {
      "id": "00000000-0000-4000-8000-000000000002",
      "blockId": "00000000-0000-4000-8000-000000000001",
      "title": "Call Alex",
      "isCompleted": false
    }
  ]
}
```

---

# Delete Reminders

`DELETE /reminders`

Experimental: delete block reminders within this connection's document scope. The blocks themselves are not deleted.

## Request Body

**Content-Type:** `application/json`

```json
{
  "idsToDelete": [
    "00000000-0000-4000-8000-000000000002"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "items": [
    "string"
  ]
}
```

---

# Update Reminders

`PUT /reminders`

Experimental: update block reminders within this connection's document scope. Only provided fields are changed.

## Request Body

**Content-Type:** `application/json`


**Example: clear**

Clear the notification time, keeping Save for later

```json
{
  "remindersToUpdate": [
    {
      "id": "00000000-0000-4000-8000-000000000002",
      "remindAt": null
    }
  ]
}
```


**Example: complete**

Complete without changing the time

```json
{
  "remindersToUpdate": [
    {
      "id": "00000000-0000-4000-8000-000000000002",
      "isCompleted": true
    }
  ]
}
```


**Example: reschedule**

Change the notification time

```json
{
  "remindersToUpdate": [
    {
      "id": "00000000-0000-4000-8000-000000000002",
      "remindAt": "2030-01-15T10:00:00+01:00"
    }
  ]
}
```

## Responses

### 200
Successfully updated resource

**Content-Type:** `application/json`


**Example: saved**

Time cleared

```json
{
  "items": [
    {
      "id": "00000000-0000-4000-8000-000000000002",
      "blockId": "00000000-0000-4000-8000-000000000001",
      "title": "Call Alex",
      "isCompleted": false
    }
  ]
}
```

**Example: scheduled**

Time updated

```json
{
  "items": [
    {
      "id": "00000000-0000-4000-8000-000000000002",
      "blockId": "00000000-0000-4000-8000-000000000001",
      "title": "Call Alex",
      "isCompleted": false,
      "remindAt": "2030-01-15T09:00:00Z"
    }
  ]
}
```

---

# List Folders

`GET /folders`

Get all locations in the space with document counts. Returns built-in locations (Unsorted, Trash, Templates) and user-created folders with their hierarchical structure.

## Responses

### 200
Success

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "unsorted",
      "name": "Unsorted",
      "documentCount": 42,
      "folders": []
    },
    {
      "id": "trash",
      "name": "Recently Deleted",
      "documentCount": 3,
      "folders": []
    },
    {
      "id": "templates",
      "name": "Templates",
      "documentCount": 5,
      "folders": []
    },
    {
      "id": "abc123",
      "name": "Projects",
      "documentCount": 10,
      "folders": [
        {
          "id": "def456",
          "name": "Work",
          "documentCount": 5,
          "folders": []
        }
      ]
    }
  ]
}
```

---

# Create Folders

`POST /folders`

Create one or more folders. Supports creating at root level or nested inside existing folders. Cannot create inside built-in locations.

## Request Body

**Content-Type:** `application/json`


**Example: createRootFolder**

Create folder at root level

```json
{
  "folders": [
    {
      "name": "New Project"
    }
  ]
}
```


**Example: createNestedFolder**

Create nested folder inside another folder

```json
{
  "folders": [
    {
      "name": "Subproject",
      "parentFolderId": "abc123"
    }
  ]
}
```


**Example: createMultipleFolders**

Create multiple folders at once

```json
{
  "folders": [
    {
      "name": "Marketing"
    },
    {
      "name": "Engineering"
    },
    {
      "name": "Q1 Planning",
      "parentFolderId": "abc123"
    }
  ]
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "xyz789",
      "name": "New Project"
    },
    {
      "id": "mno345",
      "name": "Subproject",
      "parentFolderId": "abc123"
    }
  ]
}
```

---

# Delete Folders

`DELETE /folders`

Delete folders. Documents and subfolders are moved to the parent folder, or Unsorted if deleting a top-level folder. Cannot delete built-in locations.

## Request Body

**Content-Type:** `application/json`

```json
{
  "folderIds": [
    "abc123",
    "def456"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "items": [
    "abc123",
    "def456"
  ]
}
```

---

# Move Folders

`PUT /folders/move`

Move folders within the hierarchy. Supports moving to root or inside another folder. Cannot move built-in locations.

## Request Body

**Content-Type:** `application/json`


**Example: moveToRoot**

Move folders to root level

```json
{
  "folderIds": [
    "abc123"
  ],
  "destination": "root"
}
```


**Example: moveToParent**

Move folders inside another folder

```json
{
  "folderIds": [
    "abc123",
    "def456"
  ],
  "destination": {
    "parentFolderId": "xyz789"
  }
}
```

## Responses

### 200
Successfully moved resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "abc123",
      "destination": "root"
    },
    {
      "id": "def456",
      "destination": {
        "parentFolderId": "xyz789"
      }
    }
  ]
}
```

---

# Search in Document

`GET /blocks/search`

Search within a single document. Use documents_search first to find documents, then this tool for more context with before/after blocks.

## Parameters

- **blockId** (required) (query): string
  The block ID (document or page) to search within.
- **pattern** (required) (query): string
  The search patterns to look for. Patterns must follow RE2-compatible syntax, which supports most common regular-expression features (literal text, character classes, grouping alternation, quantifiers, lookaheads, and fixed-width lookbehinds.
- **caseSensitive** (query): boolean
  Whether the search should be case sensitive. Default is false.
- **beforeBlockCount** (query): number
  The number of blocks to include before the matched block.
- **afterBlockCount** (query): number
  The number of blocks to include after the matched block.
- **fetchBlocks** (query): boolean
  Whether to include the full matched blocks with styling in the response. Default is false.

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`


**Example: withContext**

Search for 'Description' with context blocks

```json
{
  "items": [
    {
      "blockId": "109",
      "markdown": "List Item A: Description text",
      "pageBlockPath": [
        {
          "id": "0",
          "content": "Document Title"
        }
      ],
      "beforeBlocks": [
        {
          "blockId": "108",
          "markdown": "## Second Level Header"
        }
      ],
      "afterBlocks": [
        {
          "blockId": "110",
          "markdown": "List Item B: Description text"
        },
        {
          "blockId": "111",
          "markdown": "List Item C: Description text"
        }
      ]
    }
  ]
}
```

**Example: deeplyNested**

Search in deeply nested structure

```json
{
  "items": [
    {
      "blockId": "15",
      "markdown": "Match found here",
      "pageBlockPath": [
        {
          "id": "0",
          "content": "Document Title"
        },
        {
          "id": "12",
          "content": "Section Card"
        },
        {
          "id": "14",
          "content": "Nested Card"
        }
      ],
      "beforeBlocks": [
        {
          "blockId": "13",
          "markdown": "Previous content"
        }
      ],
      "afterBlocks": [
        {
          "blockId": "16",
          "markdown": "Following content"
        }
      ]
    }
  ]
}
```

---

# Search across Documents

`GET /documents/search`

Search content across all documents in the space using relevance-based ranking. Supports flat date filter fields (createdDateGte, createdDateLte, lastModifiedDateGte, lastModifiedDateLte, dailyNoteDateGte, dailyNoteDateLte) for time-based queries and location object for filtering by folder.

- Searches the entire space (all locations)
- Relevance-based ranking (top 20 results)
- Content snippets with match highlighting
- Filter by date ranges or location

**Example Use Cases:**
- Find all mentions of a topic anywhere in the space
- Search for specific content across all documents
- Search documents within a specific location or folder

## Parameters

- **include** (query): string
  Search terms to include in the search. Can be a single string or array of strings.
- **regexps** (query): string
  Search terms to include in the search. Patterns must follow RE2-compatible syntax, which supports most common regular-expression features (literal text, character classes, grouping alternation, quantifiers, lookaheads, and fixed-width lookbehinds.
- **documentIds** (query): string
  The document IDs to filter. Cannot be used together with 'location' or 'folderIds'. If not provided, all documents will be searched. Can be a single string or array of strings.
- **fetchBlocks** (query): boolean
  Whether to include the full matched blocks with styling and block IDs in each search result. Default is false.
- **location** (query): string
  Filter by virtual location: 'unsorted', 'trash', 'templates', or 'daily_notes'. Cannot be used together with 'folderId' or 'documentIds'. If neither 'location' nor 'folderId' is specified, searches/lists all documents.
- **folderIds** (query): string
  Filter by specific folders (includes subfolders recursively). Cannot be used together with 'location' or 'documentIds'. If neither 'location' nor 'folderIds' is specified, searches all documents. Can be a single string or array of strings.
- **createdDateGte** (query): string
  Only include documents created on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **createdDateLte** (query): string
  Only include documents created on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **lastModifiedDateGte** (query): string
  Only include documents modified on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **lastModifiedDateLte** (query): string
  Only include documents modified on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **dailyNoteDateGte** (query): string
  Only include daily notes on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **dailyNoteDateLte** (query): string
  Only include daily notes on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`


**Example: basicSearch**

Search for 'API' across all documents

```json
{
  "items": [
    {
      "documentId": "doc-123",
      "markdown": "The **API** endpoints are documented...",
      "blockIds": [
        "block-abc-123",
        "block-def-456"
      ]
    },
    {
      "documentId": "doc-456",
      "markdown": "**API** authentication requires...",
      "blockIds": [
        "block-ghi-789"
      ]
    }
  ]
}
```

**Example: filteredSearch**

Search with document filtering

```json
{
  "items": [
    {
      "documentId": "doc-123",
      "markdown": "Authentication **token** is required...",
      "blockIds": [
        "block-jkl-012"
      ]
    }
  ]
}
```

**Example: withMatchedBlocks**

Search with fetchBlocks=true

```json
{
  "items": [
    {
      "documentId": "doc-123",
      "markdown": "The **API** endpoints are documented...",
      "blockIds": [
        "block-abc-123"
      ],
      "blocks": [
        {
          "id": "block-abc-123",
          "type": "text",
          "markdown": "The API endpoints are documented in the developer guide"
        }
      ]
    }
  ]
}
```

---

# Get Tasks

`GET /tasks`

Retrieve tasks from across the space. Use scope='document' with documentId to get tasks from a specific document. scope='all' returns every task block in the full space, across all documents and states; it is not a union of active, upcoming, inbox, and logbook.

## Parameters

- **scope** (required) (query): string
  Filter tasks by scope: - 'active': Open tasks whose task date (schedule date when present, otherwise deadline date) is on or before today - 'upcoming': Open tasks whose task date (schedule date when present, otherwise deadline date) is tomorrow or later - 'inbox': Tasks in the task inbox - 'logbook': Tasks in the task logbook (completed/cancelled) - 'document': Tasks in a specific document (requires documentId) - 'all': Every task block in the full space, across all documents and states, including unscheduled document tasks and completed/cancelled tasks. It is not the union of active, upcoming, inbox, and logbook.
- **documentId** (query): string
  Required when scope is 'document'. The ID of the document to list tasks from.

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "task-doc-1",
      "markdown": "Review launch checklist",
      "taskInfo": {
        "state": "todo"
      },
      "location": {
        "type": "document",
        "title": "Project Plan",
        "documentId": "doc-123"
      }
    },
    {
      "id": "task-daily-1",
      "markdown": "Send weekly update",
      "taskInfo": {
        "state": "done",
        "scheduleDate": "2025-01-15"
      },
      "location": {
        "type": "dailyNote",
        "date": "2025-01-15"
      },
      "completedAt": "2025-01-15T09:30:00.000Z"
    },
    {
      "id": "task-inbox-1",
      "markdown": "Triage partner feedback",
      "taskInfo": {
        "state": "canceled"
      },
      "location": {
        "type": "inbox"
      },
      "canceledAt": "2025-01-16T17:45:00.000Z"
    }
  ]
}
```

---

# Add Tasks

`POST /tasks`

Create new tasks in inbox, daily notes, or specific documents. Location types: 'inbox', 'dailyNote' (with date), or 'document' (with documentId). Tasks can include schedule dates and deadlines.

## Request Body

**Content-Type:** `application/json`


**Example: addToInbox**

Add task to inbox

```json
{
  "tasks": [
    {
      "markdown": "Prepare presentation slides",
      "taskInfo": {
        "scheduleDate": "tomorrow"
      },
      "location": {
        "type": "inbox"
      }
    }
  ]
}
```


**Example: addToDailyNote**

Add task to a daily note

```json
{
  "tasks": [
    {
      "markdown": "Follow up on meeting action items",
      "taskInfo": {
        "scheduleDate": "2025-01-20",
        "deadlineDate": "2025-01-22"
      },
      "location": {
        "type": "dailyNote",
        "date": "today"
      }
    }
  ]
}
```


**Example: addToDocument**

Add task to a specific document

```json
{
  "tasks": [
    {
      "markdown": "Research findings task",
      "location": {
        "type": "document",
        "documentId": "doc-456"
      }
    }
  ]
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "task-new-1",
      "markdown": "Prepare presentation slides",
      "taskInfo": {
        "state": "todo",
        "scheduleDate": "2025-01-16"
      }
    }
  ]
}
```

---

# Delete Tasks

`DELETE /tasks`

Delete tasks by their IDs from any location in the space.

## Request Body

**Content-Type:** `application/json`

```json
{
  "idsToDelete": [
    "task-1",
    "task-2"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "task-1"
    },
    {
      "id": "task-2"
    }
  ]
}
```

---

# Update Tasks

`PUT /tasks`

Update existing tasks across the space. Can modify task content, state, schedule dates, deadlines, and location (to move tasks). Location types: 'inbox', 'dailyNote' (with date), or 'document' (with documentId). Marking inbox tasks as done/canceled moves them to logbook.

## Request Body

**Content-Type:** `application/json`


**Example: markDone**

Mark task as done

```json
{
  "tasksToUpdate": [
    {
      "id": "task-1",
      "taskInfo": {
        "state": "done"
      }
    }
  ]
}
```


**Example: updateContent**

Update task content and schedule

```json
{
  "tasksToUpdate": [
    {
      "id": "task-2",
      "markdown": "Updated task description",
      "taskInfo": {
        "scheduleDate": "2025-01-20"
      }
    }
  ]
}
```

## Responses

### 200
Successfully updated resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "task-1",
      "taskInfo": {
        "state": "done"
      }
    }
  ]
}
```

---

# Upload File

`POST /upload`

Upload a file (image, video, or document) and insert it at the specified position. Requires explicit target (pageId, siblingId, or date). Send raw binary data in request body with Content-Type header.

## Parameters

- **fileName** (query): string
  Optional filename, including extension (for example, report.pdf), used as the file attachment title. Left empty when omitted. Does not change the file type determined by Content-Type; ignored for image and video blocks.
- **position** (required) (query): string
  Where to insert: 'start' or 'end' for page/date positions, 'before' or 'after' for sibling positions.
- **pageId** (query): string
  Page block ID to insert into. Required when position is 'start' or 'end' (unless date is specified).
- **date** (query): string
  Daily note date. Accepts 'today', 'yesterday', 'tomorrow', or ISO date (YYYY-MM-DD). Use with position 'start' or 'end'.
- **siblingId** (query): string
  Block ID to insert relative to. Required when position is 'before' or 'after'.

## Request Body

**Content-Type:** `application/octet-stream`

```text
string
```

## Responses

### 200
Success

**Content-Type:** `application/json`

```json
{
  "blockId": "string",
  "assetUrl": "string"
}
```

---

# Create Whiteboard

`POST /whiteboards`

Create a new empty whiteboard block at the specified position. Returns the whiteboard block ID. Use whiteboardElements_add to populate it.

## Request Body

**Content-Type:** `application/json`

```json
{
  "position": {
    "position": "start",
    "pageId": "string"
  }
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "whiteboardBlockId": "string"
}
```

---

# Get Whiteboard Elements

`GET /whiteboards/{whiteboardBlockId}/elements`

Get all Excalidraw elements and appState from a whiteboard block.

## Parameters

- **whiteboardBlockId** (required) (path): string

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`

```json
{
  "elements": [
    {
      "id": "string",
      "type": "string",
      "x": 0,
      "y": 0,
      "width": 0,
      "height": 0,
      "text": "string",
      "points": [
        [
          0
        ]
      ],
      "additionalProp": "<any>"
    }
  ],
  "assets": {
    "additionalProp": "<any>"
  },
  "appState": {
    "additionalProp": "<any>"
  }
}
```

---

# Add Whiteboard Elements

`POST /whiteboards/{whiteboardBlockId}/elements`

Append elements to an existing whiteboard without removing existing ones.

## Parameters

- **whiteboardBlockId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "elements": [
    {
      "id": "string",
      "type": "string",
      "x": 0,
      "y": 0,
      "width": 0,
      "height": 0,
      "text": "string",
      "points": [
        [
          0
        ]
      ],
      "additionalProp": "<any>"
    }
  ]
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "elements": [
    {
      "id": "string",
      "type": "string",
      "x": 0,
      "y": 0,
      "width": 0,
      "height": 0,
      "text": "string",
      "points": [
        [
          0
        ]
      ],
      "additionalProp": "<any>"
    }
  ],
  "assets": {
    "additionalProp": "<any>"
  },
  "appState": {
    "additionalProp": "<any>"
  }
}
```

---

# Delete Whiteboard Elements

`DELETE /whiteboards/{whiteboardBlockId}/elements`

Remove elements from a whiteboard by their Excalidraw element IDs.

## Parameters

- **whiteboardBlockId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "elementIds": [
    "string"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "deletedCount": 0,
  "remainingCount": 0
}
```

---

# Update Whiteboard Elements

`PUT /whiteboards/{whiteboardBlockId}/elements`

Update specific elements in a whiteboard by their ID. Elements not included in the request remain unchanged.

## Parameters

- **whiteboardBlockId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "elements": [
    {
      "id": "string",
      "type": "string",
      "x": 0,
      "y": 0,
      "width": 0,
      "height": 0,
      "text": "string",
      "points": [
        [
          0
        ]
      ],
      "additionalProp": "<any>"
    }
  ]
}
```

## Responses

### 200
Successfully updated resource

**Content-Type:** `application/json`

```json
{
  "elements": [
    {
      "id": "string",
      "type": "string",
      "x": 0,
      "y": 0,
      "width": 0,
      "height": 0,
      "text": "string",
      "points": [
        [
          0
        ]
      ],
      "additionalProp": "<any>"
    }
  ],
  "assets": {
    "additionalProp": "<any>"
  },
  "appState": {
    "additionalProp": "<any>"
  }
}
```

---

# Pipeline and supported transforms

A pipeline is an object with `steps`, a nonempty ordered array of objects containing
only `name` and optional `args` (an object, default `{}`). Use the exact supported
names below. A working pipeline has exactly one `map.*` step, in final position.
Each preceding step changes the parsed message seen by subsequent steps.

Compilation checks step structure, supported step names, multiple/misplaced mappers,
custom mapper schema, and required chat destination arguments. It does not execute
the pipeline: a missing mapper and many argument errors are caught only later.
Unknown pipeline-level properties are ignored; do not emit them.

## Non-mapping steps

### `remove_fields`

Required `paths` is an array of strings; an empty array does nothing. Supported paths:

| Path | Result |
| --- | --- |
| `subject`, `text`, `html` | Set the selected value to null. |
| `headers.<name>` | Remove that entry from `headers`; name is trimmed and lowercased. |
| `attachments` | Clear the attachment list. |
| `attachments[*].filename`, `.content_type`, `.sha256`, `.blob_key` | Set that field to an empty string on every attachment. |
| `attachments[*].size` | Set size to zero on every attachment. |

The shorthand `.field` above means the full `attachments[*].field` path. Other
paths are silently ignored, including attachment IDs, individual array indices,
and `headers.*` as a wildcard. Clearing `headers` entries does not clear
`headers_multi`. This step is not a general JSON deletion operation.

### `replace_values`

Required `set` is an object mapping writable paths to values. Writable paths are
only `subject`, `text`, `html`, and `headers.<name>`; unsupported paths fail.
Values become strings; null clears the first three fields and becomes an empty
header value. Header names are trimmed and lowercased. Assignments run in object
insertion order, so later assignments can read earlier changes.

Strings support `{{ path }}` substitutions. Readable paths are only:

- `subject`, `text`, `html`, `headers.<name>`;
- `from[i].email`, `from[i].name`, `to[i].email`, `to[i].name` for an existing nonnegative index;
- `ctx.route_id`, `ctx.project_id`, `ctx.source_type`, `ctx.raw_size_bytes`.

Unresolved substitutions remain verbatim. Missing subject/text/html become empty
strings. This tiny substitution system is separate from custom JSON expressions;
there are no template filters, arithmetic, or `message.*` paths here.

### `html_to_text`

| Argument | Default | Contract |
| --- | --- | --- |
| `prefer` | `"html"` | `"html"` or `"text"`; either value converts whenever HTML is present. Selecting `"text"` does not preserve existing text. |
| `width` | `80` | Integer wrap width; zero or negative disables wrapping. |
| `preserve_links` | `true` | Retain link destinations in text. |
| `collapse_whitespace` | `true` | Collapse spaces while retaining table tabs. |
| `keep_tables` | `false` | Render tables in text with tab-separated cells. |

Replaces `text` from nonempty `html`; without HTML, leaves existing text unchanged.
Pass correctly typed JSON values even where runtime coercion exists. To choose
between existing text and converted HTML conditionally, use custom expressions
and `call.transform.html_to_text` instead.

### `strip_attachments_if`

| Argument | Contract |
| --- | --- |
| `mime_in` | Optional array of MIME glob strings. Any matching pattern satisfies this condition; empty adds no condition. |
| `max_size_kb` | Optional nonnegative integer. Matches size **greater than** this value times 1024 bytes; equality is retained. |
| `filename_regex` | Optional nonempty, valid, safe regex, searched in the filename. Case-sensitive unless flags are embedded. |

Supply at least one effective condition. An attachment is removed only if **all**
supplied conditions match. Use separate steps to remove attachments under an OR
of different conditions. MIME patterns use case-sensitive glob matching on the
stored content type. Unsafe/invalid filename regexes fail; they are not fallback
matching rules. All four non-mapping steps ignore extra argument keys, so an
unrecognized option cannot add behavior.

## Terminal mappers

| Name | Arguments | Output |
| --- | --- | --- |
| `map.generic_json` | `{}`; configuration is ignored. | Fixed generic envelope described below. |
| `map.slack_simple` | Required nonempty string `channel`; common chat options below. | Object containing `channel` and `text`. |
| `map.telegram_simple` | Required nonempty string `chat_id`; common chat options below. | Object containing `chat_id` and `text`. |
| `map.custom_json` | Required `version` and `output`; optional `vars` and `meta`. | Configured object; see [custom-json-pipeline.md](custom-json-pipeline.md). |

Common chat options: `max_chars` is an integer (default `800`, negative means no
truncation); `include_from` is a boolean (default `true`); `prefix` is a string
(default `""`, null also acts as empty). Output text contains a subject line,
optional first-sender line, and the body. When text is empty but HTML exists, the
mapper converts HTML. Prefix precedes the subject, and truncation applies to the
entire rendered string. `max_chars: 0` leads to an empty string that fails the
output schema. Destination strings are trimmed. Extra options are ignored.
Chat mappers emit no attachments. Endpoint credentials and URLs are not mapper
arguments; choosing a mapper does not provision a destination.

### Generic JSON envelope

| Output block | Fields |
| --- | --- |
| `schema` | `name: "mailwebhook.generic"`, `version: "1"`. |
| `event` | `id`, `project_id`, `route_id`, `created_at`. |
| `message` | `message_id`, `message_id_type` (`original` or `synthetic`), `subject`, `date`, `from`, `to`; optional nonempty `reply_to`, `cc`, `bcc`, `headers`. |
| `body` | `attachments`; optional nonblank `text`, `html`. |
| `envelope` | Optional `mail_from` and/or `rcpt_to` when supplied by ingestion. |
| `meta` | `source`, `raw_size_bytes`, `received_at`; optional `spam`. |

Addresses contain `email` and optional `name`; emails are lowercased, trimmed,
sorted, and blank entries omitted. Header names are normalized, values unfolded,
and blank entries omitted. Text, HTML and subject are edge-trimmed. Dates are UTC
RFC3339 strings with whole seconds. Missing message date falls back to received
time, then the context time.

Attachments contain `id`, `filename`, `content_type`, `size`, `is_inline`, and
optional `content_id`, `sha256`; they are sorted by filename then size. They do
not contain `blob_key` or attachment bytes. Envelope recipients are normalized,
deduplicated, and sorted. Spam metadata can include `flag`, `status`, `score`,
`quarantined`, and `details` (including unparsed flag/score, level and scan data).
These are ingestion-provided fields, not route configuration. Use a custom
mapper for another payload shape.

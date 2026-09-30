# Custom JSON mapper

Use `map.custom_json` as the single final mapper in `pipeline.steps`. Earlier
transforms change the parsed message that this mapper sees. This reference covers
the mapper document and its input/output boundary; read [expressions.md](expressions.md)
for the complete DSL and [extraction-helpers.md](extraction-helpers.md) for helper
arguments and result shapes.

## Mapper arguments

The [mapper configuration schema](schemas/custom-json-mapper.schema.json) uses
JSON Schema Draft 2020-12. Validate the `args` object of a `map.custom_json` step
against it, not the whole step, pipeline, route, or emitted payload. Its references
are contained within the schema; no remote schema retrieval is needed.

| Key | Contract |
| --- | --- |
| `version` | Required; exactly `"v1"`. |
| `vars` | Optional ordered array, default `[]`. Each entry requires `name` and `expr`; optional `description` is a string. No other entry keys. |
| `output` | Required JSON template or expression; author an object-valued final result. See the runtime restriction below. |
| `meta` | Optional static object. Values are not evaluated as expressions. Read them through `meta.*`; they are not automatically added to the webhook body. |

No other top-level argument keys are allowed. Variable names match
`^[A-Za-z_][A-Za-z0-9_]*$` and must be unique within their array. They evaluate in
order, so `vars.<name>` can read an earlier entry. Forward references are missing
values, not dependency resolution. Duplicate top-level names fail at execution;
do not rely on successful compilation to detect them.

Top-level `vars[].expr` has a narrower schema than `output`: it accepts scalars,
arrays of expressions, and recognized single-key operators. A direct plain object
or scoped block is rejected there. Build a computed object with `merge`, put
static data in `meta`, or place a scoped block inside an operator payload. For
example, `{"merge":[{"status":"received"}]}` is an object-valued expression.

This original minimal pipeline reads parsed fields and adds a computed value:

```json
{
  "steps": [
    {
      "name": "map.custom_json",
      "args": {
        "version": "v1",
        "vars": [
          {
            "name": "sender_address",
            "expr": {"string.lower": {"var": "message.from[0].email"}}
          }
        ],
        "meta": {"workflow": "support-intake"},
        "output": {
          "event": {"var": "ctx.event_id"},
          "sender": {"var": "vars.sender_address"},
          "subject": {"var": "message.subject"},
          "workflow": {"var": "meta.workflow"}
        }
      }
    }
  ]
}
```

## Complete evaluation root

These paths refer to the parsed message after preceding pipeline transforms.
They are not the nested payload produced by `map.generic_json`.

| Root/path | Value |
| --- | --- |
| `message.message_id` | String identifier. |
| `message.message_id_is_synthetic` | Boolean, default `false`. |
| `message.subject` | String or `null`. |
| `message.date` | Parsed message date or `null`. |
| `message.received_at` | Required receipt timestamp. |
| `message.from`, `message.from_` | Equivalent arrays of sender objects. Prefer `from` for new configurations. |
| `message.to`, `message.reply_to`, `message.cc`, `message.bcc` | Address arrays, empty when absent. Each item has `email` (string) and `name` (string or `null`). |
| `message.headers` | Map of normalized lowercase header names to strings. Header selection/deduplication follows the MIME parser. |
| `message.headers_multi` | Map of lowercase names to arrays of strings when repeated headers exist; otherwise `null`. |
| `message.text`, `message.html` | Body strings or `null`. |
| `message.attachments` | Array of attachment metadata objects, described below. |
| `ctx.event_id`, `ctx.project_id`, `ctx.route_id` | UUID strings supplied by the application. |
| `ctx.source_type` | Source string; application sources are `imap`, `gmail`, `ms365`, and `hosted`. |
| `ctx.raw_size_bytes` | Integer raw MIME size. |
| `ctx.now` | Application-supplied time converted to UTC RFC3339 with `Z`, no fractional seconds. |
| `meta` | Static mapper metadata object, default `{}`. |
| `vars` | Computed variables; local scoped blocks can overlay this mapping. |

Every attachment exposes `id`, `filename`, `content_type`, `size` (bytes),
`blob_key`, `sha256`, `is_inline` (boolean, default `false`), and `content_id`
(string or `null`). `blob_key` is the stored object key, not a download URL.
No file bytes are provided to the DSL. Selecting attachment metadata in the
custom output does not inline or fetch the attachment content.

`message.date` and `message.received_at` are timestamp values in the evaluator;
passing them directly through an object is supported by the application's JSON
serialization. They do not share `ctx.now`'s explicit UTC/precision normalization.
String operations coerce them using their string representation; there is no
date-formatting operator.

Only the six listed `ctx` fields are exposed. SMTP envelope and spam metadata
are not available through this mapper's context. The DSL has no implicit
attachment download URL, raw MIME, or external state access.

## Output and validation boundaries

Build an object at the top level. Nested arrays, scalars, objects, and `null`
values are supported. Scalar and array results at the top level fail execution,
even if configuration validation accepts them.
Wrap an array as an object property such as `{"records": <expression>}`.

Literal `"output": null` passes the schema but fails mapper execution as missing
output. An expression that evaluates to `null` produces `{}`. Use an explicit
object result to make the intended webhook contract clear.

The mapper validates its configuration at compile time and again when executed.
The included schema checks configuration structure; it does not fully validate
operator argument shapes, helper options, variable dependencies or uniqueness,
scoped-block behavior, or the type of the evaluated output. Schema `default`
annotations do not insert omitted values into JSON.
Schema acceptance alone does not establish correct runtime behavior: invalid
operator payloads can evaluate to `null`; unsupported dotted operator names in
an output template can fail only during execution; duplicate top-level variables
also fail only at execution. Verify both the pipeline execution and the actual
serialized output with representative input. There is no automatic omission of
null-valued output properties.

The emitted body is the evaluated `output`, without an automatically added
generic envelope, context, mapper metadata, schema version, or attachment field.
Preceding attachment filters still apply to the message's attachments.

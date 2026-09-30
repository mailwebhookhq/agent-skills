# Route and delivery-target contracts

A route combines a matching [rule](rule.md), a transform
[pipeline](pipeline.md), and one existing endpoint in the same
authenticated project. Every enabled matching route receives its own event;
there is no first-match rule, route priority, mailbox binding, or stop flag in
the route JSON contract.

## Ordinary route API

`POST /v1/routes` accepts this complete writable surface:

| Key | Create contract | PATCH behavior |
| --- | --- | --- |
| `name` | Required string. Use a meaningful name of at most 200 characters. | Replaces the name when non-null. |
| `endpoint_id` | Required UUID string identifying an endpoint in this project. | Replaces the destination after the same ownership check. |
| `signing_secret_kid` | Optional nonempty string or `null`; omitted/null selects the active project signing secret. Use at most 64 characters. | A non-null string replaces the KID; null/omitted preserves it. PATCH can accept an empty string; still author a real nonempty KID. |
| `rule` | Required object. `{}` explicitly means match-all. | Replaces the entire rule, not a recursive merge. |
| `pipeline` | Required pipeline object. Must compile successfully. | Replaces the entire pipeline and is compiled again. |
| `enabled` | Optional boolean, default `true`. | Non-null `true`/`false` sets the flag. |

All PATCH fields are optional; omitted or explicit `null` values leave existing
values unchanged. `{"rule":{}}` actively replaces a filter with match-all;
`{"rule":null}` does not. A partial nested rule/pipeline is not a patch to that
nested object.

Example create payload (replace the illustrative endpoint UUID with a real ID):

```json
{
  "name": "Vendor invoices",
  "endpoint_id": "f49c6149-3a6c-4f3b-b9d3-8f5c8a1e71a0",
  "rule": {
    "from_domains": ["vendor.example"],
    "subject_contains": ["invoice"]
  },
  "pipeline": {
    "steps": [
      {
        "name": "map.custom_json",
        "args": {
          "version": "v1",
          "output": {
            "subject": {"var": "message.subject"},
            "event_id": {"var": "ctx.event_id"}
          }
        }
      }
    ]
  },
  "enabled": true
}
```

Create returns `201`; GET list returns `200` plus an array; GET
`/v1/routes/{route_id}` and PATCH return `200` plus one route. A response has all
six writable keys plus server-generated `id`; `signing_secret_kid` is always a
string. Returned rules/pipelines can include defaults and normalized values.
DELETE returns `204` and removes the route and its associated events.

Use only the listed writable route keys. Do not send response-only `id`, inline
endpoint URL/headers, or invented retry settings as route fields. Unknown envelope
keys are ignored, not extensions.

Creation enforces the project's route limit and endpoint ownership. Important
failures include `route.endpoint_invalid` (400),
`route.signing_secret_unavailable` (400), `pipeline.invalid` (400, with nested
transform details), and `route.not_found` (404). Request validation can fail
before these checks. Pipeline compilation is necessary but does not prove
success on real messages, and rule parsing does not fully validate nested rules
or regex behavior.

## Endpoint linkage and signing

An endpoint is a separate resource. `POST /v1/endpoints` takes required `url`
(HTTP or HTTPS URL), optional `headers` (string map, default `{}`), and optional
`timeout_s` (integer, default `10`). GET/list responses contain those fields plus
`id`; PATCH replaces each non-null supplied field (including the complete header
map). An in-use endpoint cannot be deleted. A route references the resulting
endpoint ID, never an inline endpoint. Credentials required by the receiver
belong in endpoint headers or provider-specific configuration, not custom JSON
payloads unless the user's receiver contract explicitly requires them.

`signing_secret_kid` identifies a webhook HMAC signing key; it is not a secret
value or API key. Prefer omitting it on creation. An explicitly provided KID is
currently accepted even if no secret exists, so API success is not proof that
delivery signing will work. API keys authenticate calls to MailWebhook and are
separate from outbound signing secrets. Creating pending rotation leaves route
KIDs unchanged; activating it updates every project route to the active KID.
The lifecycle endpoints are GET `/v1/project/signing-secret`, POST
`/v1/project/signing-secret/rotate`, POST
`/v1/project/signing-secret/activate`, and DELETE
`/v1/project/signing-secret/pending`. Authoring route JSON does not require
rotating secrets or sending a webhook.

## UI JSON editor

The route UI's `config_json` value is only
`{"rule": {...}, "pipeline": {...}}`. Name, endpoint selection, and enabled
state are separate form fields. This is not the ordinary API create envelope.
The UI supplies a match-all rule for an empty rule and a `map.generic_json`
pipeline when steps are missing/empty, but explicit complete JSON is safer and
portable to the API. UI forms choose the active signing KID. Prefer the JSON
editor over the simplified form when authoring capabilities beyond its small
set of controls.

## Optional combined provisioning requests

These are separate endpoint+route APIs, not extra fields in `/v1/routes`.
Both reject unknown top-level keys, select the active project signing secret,
reuse resources by exact persisted shape, and enforce route limits when a new
route is needed. Responses contain `endpoint_id`, `route_id`,
`endpoint_reused`, and `route_reused`; chat also returns `provider`. Status is
`200` if both resources were reused, otherwise `201`.

`POST /v1/onboarding/https-route-pairs` accepts:

| Key | Contract |
| --- | --- |
| `route_name` | Required string, 1–200 characters, trimmed and nonempty. |
| `endpoint_url` | Required string, 1–2048 characters, trimmed; public HTTPS destination passing the outbound URL policy. |
| `endpoint_headers` | Optional string map, default `{}`; trimmed header names must be nonempty. |
| `timeout_s` | Integer, 1–60, default `10`. |
| `rule` | Optional object/null; omitted/null means match-all. |
| `pipeline` | Optional object/null; omitted/null defaults to one `map.generic_json` step. An explicit invalid/empty pipeline is not the default. |
| `enabled` | Boolean, default `true`. |

`POST /v1/onboarding/chat-route-pairs` accepts:

| Key | Contract |
| --- | --- |
| `provider` | Required `"slack"` or `"telegram"`. |
| `route_name` | Required string, 1–200 characters, trimmed and nonempty. |
| `endpoint_name` | Optional string/null, at most 200 characters; accepted but not persisted. |
| `bot_api_key` | Required nonempty string, trimmed; provider credential. |
| `channel_id` | Required for Slack; uppercase letters/digits only, at least two characters, no `#`; omit for Telegram. |
| `chat_id` | Required nonempty string for Telegram; omit for Slack. |
| `rule` | Optional object/null, default match-all. |
| `enabled` | Boolean, default `true`. |

Chat provisioning fixes the pipeline to one provider mapper:
`map.slack_simple` with `channel`, or `map.telegram_simple` with `chat_id`.
Slack places the bot credential in an Authorization header; Telegram places it
in its API endpoint URL. Provider URL overrides are deployment settings, not
request keys. For additional transforms or a custom payload, use ordinary
route creation/update with the appropriate endpoint instead. The fixed chat
pair request has no pipeline field.

## Preview and testing

Validate the rule against representative metadata and execute the pipeline
against representative parsed messages before claiming correctness. There is
no `/v1/routes/preview` or `/v1/routes/validate` endpoint in this contract.
The route UI's `/ui/routes/{route_id}/send-test` queues a synthetic event for
real transform/delivery; it bypasses rule matching and is not a read-only
preview. Onboarding's selected-event sample preview runs generic/suggested
pipelines locally in an active onboarding session; it is not an arbitrary route
JSON validation endpoint. Authoring JSON alone does not authorize delivery.

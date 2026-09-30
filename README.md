# MailWebhook Agent Skills

Agent skills for building MailWebhook routes, matching rules, transform pipelines, and custom JSON payloads.

## Available skills

| Skill | Description |
| --- | --- |
| [author-mailwebhook-route-json](skills/author-mailwebhook-route-json/SKILL.md) | Author, explain, review, and repair route configurations, matching rules, transform pipelines, and custom JSON mapper expressions. |

The skill includes references for route creation and updates, rule composition,
pipeline steps, expression operators, and extraction helpers. A JSON Schema
supports validation of custom JSON mapper arguments, alongside guidance for
checking matching behavior and emitted payloads.

## Using the skill

Make the skill available in your agent's skill environment, then ask it to use
`author-mailwebhook-route-json`. Provide the matching intent, representative
email content, and desired output shape. For a complete route, include the
destination endpoint ID; for an update, include the existing configuration.

Example request:

> Use author-mailwebhook-route-json to build a route that matches invoices from
> vendor.example and emits the subject, sender address, and extracted order ID.
> Here is a sample email and the destination endpoint ID.

The skill can return a complete route or an individual rule, pipeline, or mapper
configuration. Authoring configuration does not publish a route or send a webhook.

## Licence

Licensed under the [MIT License](LICENCE).

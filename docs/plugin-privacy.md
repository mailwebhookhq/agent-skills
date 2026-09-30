# Plugin privacy section draft

Proposed addition to the existing [MailWebhook privacy policy](https://www.mailwebhook.com/privacy).
This file is a website handoff, not a published policy or a plugin archive member.

## Proposed policy text

### MailWebhook agent skills and ChatGPT plugin

The MailWebhook plugin provides instructions and reference material for authoring
routes, matching rules, transform pipelines, and custom JSON payloads. The
distributed package has no MailWebhook service connection, executable scripts,
or telemetry. Using its instructions to generate or review configuration does
not, by itself, send your conversation, email samples, or generated configuration
to MailWebhook. We do not receive, retain, or share those materials through the
package itself.

When you use the plugin in ChatGPT, OpenAI processes the content you provide and
the resulting conversation under the applicable OpenAI terms, privacy notices,
and your account or workspace settings. This processing is separate from
MailWebhook's hosted email-processing service. Use the controls provided by your
agent platform to manage that conversation data.

If you separately use our website or hosted service, ask an agent to call
MailWebhook's API through other available tools, or contact us for support, we
may receive information through those interactions. The information, purposes,
recipients, retention, and rights described elsewhere in this policy apply to
those interactions. For example, support requests include the contact details
and content you choose to send us. Generating configuration with the skill does
not itself apply it to your MailWebhook account.

For privacy questions or requests concerning information held by MailWebhook,
contact **privacy@mailwebhook.com**. Requests about data held by your agent
platform should be directed to that provider.

## Before publishing

Confirm whether OpenAI or another distributor supplies installation or usage
analytics to MailWebhook outside the plugin package. The package cannot establish
whether such reports exist. If MailWebhook receives them, add the actual data
categories, purposes, recipients, retention periods, and user controls to this
section; do not describe them as collection by the static package.

Check the text against the version being submitted, incorporate it into the live
policy, and update that policy's revision date. Future tools, integrations, or
telemetry require a corresponding policy update.

The distinction between public policy requirements and skills-only ZIP validation
comes from OpenAI's [privacy guidelines](https://developers.openai.com/plugins/plugin-guidelines#privacy)
and [listing metadata reference](https://developers.openai.com/plugins/deploy/submission#listing-metadata).

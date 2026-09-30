# MailWebhook Agent Skills

Agent skills for building MailWebhook routes, matching rules, transform pipelines, and custom JSON payloads.

## Install

With Node.js and npm installed, run this from your project directory:

```sh
npx skills add mailwebhookhq/agent-skills \
  --skill author-mailwebhook-route-json
```

The [Skills CLI](https://github.com/vercel-labs/skills) downloads the skill from
GitHub. Follow its prompts to select your coding agent. Supported agents include
Claude Code, Codex, Cursor, and GitHub Copilot. Installation defaults to the
current project; add `--global` to make the skill available across projects.

Other installation options:

```sh
# List available skills without installing
npx skills add mailwebhookhq/agent-skills --list

# Install for Claude Code
npx skills add mailwebhookhq/agent-skills \
  --skill author-mailwebhook-route-json --agent claude-code

# Install across projects
npx skills add mailwebhookhq/agent-skills \
  --skill author-mailwebhook-route-json --global
```

To update an installed copy:

```sh
npx skills update author-mailwebhook-route-json
```

See the [CLI reference](https://github.com/vercel-labs/skills#options) for agent
selection and scope options. GitHub installation reads this repository directly;
the [release archives and website index](#skill-releases) provide another
discovery route.

## Available skills

| Skill | Description |
| --- | --- |
| [author-mailwebhook-route-json](skills/author-mailwebhook-route-json/SKILL.md) | Author, explain, review, and repair route configurations, matching rules, transform pipelines, and custom JSON mapper expressions. |

The skill includes references for route creation and updates, rule composition,
pipeline steps, expression operators, and extraction helpers. A JSON Schema
supports validation of custom JSON mapper arguments, alongside guidance for
checking matching behavior and emitted payloads.

## Using the skill

After installation, ask your agent to use `author-mailwebhook-route-json`.
Provide the matching intent, representative email content, and desired output
shape. For a complete route, include the destination endpoint ID; for an update,
include the existing configuration.

**Matching rule**

> Use author-mailwebhook-route-json to write a matching rule for emails from
> billing@example.com whose subject contains "Invoice". Return the rule JSON
> and explain which of these sample emails should match.

**Custom JSON pipeline**

> Use author-mailwebhook-route-json to build a pipeline that extracts invoice
> number, total, and currency from these email samples. Emit
> {"invoice_number": "INV-1042", "total": 125.50, "currency": "USD"}, with a
> numeric total and null for missing values. Here are the sample emails.

**Route review and repair**

> Use author-mailwebhook-route-json to review this route JSON against these
> sample emails and expected payloads. Fix unsupported rule keys and pipeline
> expressions, preserve unrelated settings, and explain each correction.

The skill can return a complete route or an individual rule, pipeline, or mapper
configuration. Authoring configuration does not publish a route or send a webhook.

## Skill releases

The [skills.sh FAQ](https://www.skills.sh/docs/faq) describes directory listings
and rankings driven by installation telemetry from the Skills CLI. The website
discovery index below supplies versioned archives and digests to agents that use
the site's discovery endpoint.

The **Release skills** GitHub Actions workflow publishes two package layouts
from the same maintained skill files:

| Release asset | Purpose | Archive layout |
| --- | --- | --- |
| `author-mailwebhook-route-json.zip` | Website skill discovery | `SKILL.md` at the ZIP root |
| `mailwebhook-plugin.zip` | Manual ChatGPT plugin upload | Root `plugin.json`, assets, and skills under `skills/` |

Each directory in `skills/` gets its own standalone ZIP with this layout:

```text
SKILL.md
LICENCE
agents/
references/
```

Other skill resources, such as `assets/` and `scripts/`, are included when present.
The repository licence is included unless a skill supplies its own `LICENCE`.
Hidden files, caches, and editor backups are excluded; symlinks are rejected.
The skill folder name must match the `name` in its frontmatter.

The plugin ZIP includes every skill and the existing MailWebhook icon:

```text
plugin.json
LICENCE
assets/icon.png
skills/
  author-mailwebhook-route-json/
    SKILL.md
    LICENCE
    agents/
    references/
```

[plugin.json](plugin.json) contains the portable identity and OpenAI listing
metadata. The build snapshots the skill files once for both layouts. During
release, the packaged plugin version comes from the tag with its leading `v`
removed; the source manifest stays unchanged. Plugin releases require a semantic
version such as `v1.2.3` or `v1.2.3-rc.1`.

Download `mailwebhook-plugin.zip` from the
[GitHub release](https://github.com/mailwebhookhq/agent-skills/releases) and use
the skills-only upload path described in
[OpenAI's submission guide](https://developers.openai.com/plugins/deploy/submission).
The package includes listing text, starter prompts, and an icon, and contains no
MCP server. Upload, developer identity verification, review, and directory
publication are separate manual steps. Building or releasing this archive does
not submit it to OpenAI.

The listing links to MailWebhook's [privacy policy](https://www.mailwebhook.com/privacy)
and [terms of service](https://www.mailwebhook.com/terms). The build validates these
URLs as HTTPS, without embedded credentials, and at most 1024 characters long.
OpenAI's [public directory guidelines](https://developers.openai.com/plugins/plugin-guidelines#privacy)
require a published privacy policy, even though skills-only upload validation
allows the policy URL to be omitted. The terms URL is optional for this
skills-only package; both links are included in the manifest.

Before public submission, complete the [plugin privacy section draft](docs/plugin-privacy.md)
and publish it on the existing privacy-policy page. The draft distinguishes the
static package's behavior from ChatGPT processing and separately requested
MailWebhook service use. Confirm any publisher analytics before publishing that
section. This repository's release workflow does not change either policy page.

To publish:

1. Merge and pass the checks on `main`, including the release workflow itself.
2. Create and push a version tag, for example `v1.0.0`. Tags beginning with `v`
   trigger publication. Alternatively, run **Release skills** manually and supply
   an existing version tag. For plugin releases, use an optional `v` prefix
   followed by a semantic version. Build metadata such as `v1.2.3+build.1` is
   supported.
3. Wait for the entire workflow to succeed. Download its verified `index.json`
   artifact, or the same file attached to that release.
4. Manually publish the index at
   `https://www.mailwebhook.com/.well-known/agent-skills/index.json`. Preserve
   unrelated skills if the website already lists other entries. Verify the
   website serves the updated JSON and that its archive links are accessible.

The website's `index.json` lists only standalone skill ZIPs; the plugin ZIP is
published alongside them and is excluded from that index.

The workflow builds the ZIPs once and hashes their final bytes. It uploads them
with `application/zip` and generates the discovery index with versioned download
URLs, `sha256:` digests, and descriptions from skill frontmatter. ZIPs and
`index.json` are staged in a draft before publication, supporting immutable
releases. When GitHub returns temporary `untagged-*` draft URLs, the staged index
uses their final version-tag URLs. After publishing, the workflow refreshes asset
metadata and confirms the final URLs and asset identities. Uploads and stored
asset metadata must use `application/zip` for ZIPs and `application/json` for the
index. Anonymous downloads accept that media type or GitHub's generic
`application/octet-stream` response, and must match the exact size and digest.
Only successful verification exports the website handoff artifact. The website
is not updated automatically.

The repository must be public. The workflow uses its `GITHUB_TOKEN` with
`contents: write`; no separate release secret is needed. Pinned action revisions
and dependency versions keep the tooling controlled. Existing identical assets
can be reused on a rerun. Conflicting or incomplete assets stop the run; published
assets are never replaced. Resolve an incomplete draft upload or use a new tag.
If a run fails after publication, rerun the same tag to verify it; do not update
the website until verification succeeds.

The workflow checks out its requested tag, including the release tooling. If a
failure requires a tooling fix, commit and push the fix before creating a new
version tag (for example, `v1.0.1`). Rerunning an older tag still runs the old
tooling. An unpublished draft from a failed run does not prevent releasing a new
tag; leave its tag unchanged.

## Local development

Use Python 3.12 or newer:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pytest
.venv/bin/python -m release_tools build --plugin plugin.json
```

The build writes standalone skill ZIPs, `mailwebhook-plugin.zip`, and an exact-byte
`manifest.json` into `dist/archives`. The local manifest distinguishes the plugin
artifact from discoverable skills. Omit `--plugin` to build only standalone ZIPs.
It performs no network requests and requires no credentials. Use a new or empty
output directory for each build; `--output` selects another location.

The local plugin build uses the source manifest's version unless `--tag` is
provided. For release builds, specify the same tag when building and publishing:

```sh
.venv/bin/python -m release_tools build --plugin plugin.json --tag v1.2.3 \
  --output dist/v1.2.3
.venv/bin/python -m release_tools publish --tag v1.2.3 --archives dist/v1.2.3
```

Publishing creates or publishes a GitHub release. It requires `GITHUB_TOKEN` and
`GITHUB_REPOSITORY` (or `--repository owner/name`).
The repository and tag must already exist. Run it with the archives built from
that tag. `.env.example` lists the token, repository, and HTTPS service-origin
settings; environment files are not loaded automatically. The verified website
index is written to `dist/website/index.json`. Select a new `--index` path if a
previous handoff already exists. Local archive manifests and tooling stay outside
the skill ZIPs.

Plugin packaging validates the supported skills-only manifest fields, semantic
version, referenced PNG icons, and archive paths and size limits. It follows
[OpenAI's package layout](https://developers.openai.com/plugins/build/plugins);
the submission portal performs its own metadata and skill checks.

## Licence

Licensed under the [MIT License](LICENCE).

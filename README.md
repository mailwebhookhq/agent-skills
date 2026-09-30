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

## Skill releases

The **Release skills** GitHub Actions workflow publishes every directory in
`skills/` as a separate release asset. Each archive has this layout:

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

To publish:

1. Merge and pass the checks on `main`, including the release workflow itself.
2. Create and push a version tag, for example `v1.0.0`. Tags beginning with `v`
   trigger publication. Alternatively, run **Release skills** manually and supply
   an existing version tag. Tags use letters, digits, dots, underscores, and
   hyphens, beginning with a letter or digit.
3. Wait for the entire workflow to succeed. Download its verified `index.json`
   artifact, or the same file attached to that release.
4. Manually publish the index at
   `https://www.mailwebhook.com/.well-known/agent-skills/index.json`. Preserve
   unrelated skills if the website already lists other entries. Verify the
   website serves the updated JSON and that its archive links are accessible.

The workflow builds the ZIPs once and hashes their final bytes. It uploads them
with `application/zip`, uses GitHub's returned versioned download URLs, and
generates the discovery index with `sha256:` digests and descriptions from skill
frontmatter. ZIPs and `index.json` are staged in a draft before publication,
supporting immutable releases. The workflow then downloads every asset without
authentication and checks its content type, size, and digest. Only successful
verification exports the website handoff artifact. The website is not updated
automatically.

The repository must be public. The workflow uses its `GITHUB_TOKEN` with
`contents: write`; no separate release secret is needed. Pinned action revisions
and dependency versions keep the tooling controlled. Existing identical assets
can be reused on a rerun. Conflicting or incomplete assets stop the run; published
assets are never replaced. Resolve an incomplete draft upload or use a new tag.
If a run fails after publication, rerun the same tag to verify it; do not update
the website until verification succeeds.

## Local development

Use Python 3.12 or newer:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pytest
.venv/bin/python -m release_tools build
```

The build writes ZIPs and an exact-byte `manifest.json` into `dist/archives`.
It performs no network requests and requires no credentials. Use a new or empty
output directory for each build; `--output` selects another location.

Publishing is a separate command and creates or publishes a GitHub release:

```sh
.venv/bin/python -m release_tools publish --tag v1.0.0
```

It requires `GITHUB_TOKEN` and `GITHUB_REPOSITORY` (or `--repository owner/name`).
The repository and tag must already exist. Run it with the archives built from
that tag. `.env.example` lists the token, repository, and HTTPS service-origin
settings; environment files are not loaded automatically. The verified website
index is written to `dist/website/index.json`. Select a new `--index` path if a
previous handoff already exists. Local archive manifests and tooling stay outside
the skill ZIPs.

## Licence

Licensed under the [MIT License](LICENCE).

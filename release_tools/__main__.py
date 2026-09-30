"""Expose separate local-build and authenticated-publish commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import TypeAdapter

from release_tools.archives import build_archives
from release_tools.models import ReleaseArtifact
from release_tools.publish import (
    GitHubClient,
    GitHubSettings,
    PublishError,
    publish_archives,
    validate_tag,
)


def main(argv: list[str] | None = None) -> int:
    """Run the requested release stage and report failures without credential traces.

    Args:
        argv: Optional argument list for tests; otherwise read process arguments.

    Returns:
        Zero on success, or one when validation, packaging, or publication fails.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build ZIPs and their exact-byte manifest locally")
    build.add_argument("--skills", type=Path, default=Path("skills"))
    build.add_argument("--licence", type=Path, default=Path("LICENCE"))
    build.add_argument("--output", type=Path, default=Path("dist/archives"))
    build.add_argument(
        "--plugin", type=Path, help="Also bundle a portable plugin from this manifest"
    )
    build.add_argument("--tag", help="Set the bundled plugin version from this release tag")
    publish = commands.add_parser("publish", help="Publish and export a verified discovery index")
    publish.add_argument("--archives", type=Path, default=Path("dist/archives"))
    publish.add_argument("--index", type=Path, default=Path("dist/website/index.json"))
    publish.add_argument("--tag", required=True)
    publish.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            if args.tag and not args.plugin:
                raise ValueError("--tag requires --plugin when building")
            version = validate_tag(args.tag).removeprefix("v") if args.tag else None
            artifacts = build_archives(
                args.skills,
                args.licence,
                args.output,
                plugin_path=args.plugin,
                plugin_version=version,
            )
            manifest = [artifact.model_dump(mode="json") for artifact in artifacts]
            (args.output / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            print(f"Built {len(artifacts)} release ZIP(s) in {args.output}")
        else:
            if not args.repository:
                raise ValueError("Set GITHUB_REPOSITORY or pass --repository owner/repository")
            token = os.environ.get("GITHUB_TOKEN", "")
            if not token:
                raise ValueError("Set GITHUB_TOKEN to publish; local builds need no token")
            artifacts = TypeAdapter(list[ReleaseArtifact]).validate_json(
                (args.archives / "manifest.json").read_bytes()
            )
            settings = GitHubSettings(
                repository=args.repository,
                token=token,
                api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
                uploads_url=os.environ.get(
                    "SKILL_RELEASE_UPLOADS_URL", "https://uploads.github.com"
                ),
                server_url=os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
            )
            client = GitHubClient(settings)
            try:
                publish_archives(client, artifacts, args.archives, args.tag, args.index)
            finally:
                client.close()
            print(f"Public release verified. Website handoff: {args.index}")
    except (OSError, ValueError, PublishError) as exc:
        print(f"Release failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

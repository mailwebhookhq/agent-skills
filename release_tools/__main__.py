"""Expose separate local-build and authenticated-publish commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import TypeAdapter

from release_tools.archives import build_archives
from release_tools.models import ArchiveArtifact
from release_tools.publish import GitHubClient, GitHubSettings, PublishError, publish_archives


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
    publish = commands.add_parser("publish", help="Publish and export a verified discovery index")
    publish.add_argument("--archives", type=Path, default=Path("dist/archives"))
    publish.add_argument("--index", type=Path, default=Path("dist/website/index.json"))
    publish.add_argument("--tag", required=True)
    publish.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            artifacts = build_archives(args.skills, args.licence, args.output)
            manifest = [artifact.model_dump(mode="json") for artifact in artifacts]
            (args.output / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            print(f"Built {len(artifacts)} skill ZIP(s) in {args.output}")
        else:
            if not args.repository:
                raise ValueError("Set GITHUB_REPOSITORY or pass --repository owner/repository")
            token = os.environ.get("GITHUB_TOKEN", "")
            if not token:
                raise ValueError("Set GITHUB_TOKEN to publish; local builds need no token")
            artifacts = TypeAdapter(list[ArchiveArtifact]).validate_json(
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

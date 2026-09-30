"""Publish skill archives and withhold the website index until public verification."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import requests
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator

from release_tools.models import ArchiveArtifact, DiscoveryEntry, DiscoveryIndex


class PublishError(RuntimeError):
    """Report an unsafe or incomplete release without exposing authentication data."""


class GitHubSettings(BaseModel):
    """Validate credentials and explicitly configured GitHub service origins."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    token: SecretStr = Field(min_length=1)
    api_url: str
    uploads_url: str
    server_url: str

    @field_validator("api_url", "uploads_url", "server_url")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        """Accept an HTTPS origin only, preventing credential-bearing upload redirects."""
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("GitHub service URLs must be HTTPS origins without credentials")
        return value.rstrip("/")


class Release(BaseModel):
    """Keep the release fields used for ordering and idempotent publication."""

    id: int = Field(gt=0)
    tag_name: str
    draft: bool
    upload_url: str
    html_url: HttpUrl


class Asset(BaseModel):
    """Validate the server's asset identity, media type, and content metadata."""

    id: int = Field(gt=0)
    name: str
    state: str
    content_type: str
    size: int = Field(ge=0)
    digest: str | None = None
    browser_download_url: HttpUrl


def content_digest(data: bytes) -> str:
    """Return the discovery digest of the exact byte sequence supplied."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def validate_tag(tag: str) -> str:
    """Accept a portable version tag without ambiguous path or ref syntax."""
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", tag)
        or ".." in tag
        or tag.endswith((".", ".lock"))
    ):
        raise ValueError("Use an existing version tag such as v1.0.0")
    return tag


class GitHubClient:
    """Access authenticated release APIs separately from anonymous asset downloads."""

    def __init__(self, settings: GitHubSettings) -> None:
        """Create separate sessions so public verification cannot inherit credentials."""
        self.settings = settings
        self.api = requests.Session()
        self.api.trust_env = False
        self.public = requests.Session()
        self.public.trust_env = False
        self.repo_path = f"/repos/{settings.repository}"

    def close(self) -> None:
        """Release both HTTP connection pools."""
        self.api.close()
        self.public.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        data: bytes | None = None,
        content_type: str = "application/json",
        upload: bool = False,
        allow_missing: bool = False,
    ) -> Any:
        """Call one trusted API origin without retrying ambiguous mutations.

        Raises:
            PublishError: If transport, HTTP status, or JSON decoding fails.
        """
        origin = self.settings.uploads_url if upload else self.settings.api_url
        headers = {
            "Authorization": f"Bearer {self.settings.token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "Content-Type": content_type,
        }
        try:
            with self.api.request(
                method,
                origin + path,
                headers=headers,
                json=payload,
                data=data,
                timeout=(10, 120),
                allow_redirects=False,
            ) as response:
                if allow_missing and response.status_code == 404:
                    return None
                if not 200 <= response.status_code < 300:
                    raise PublishError(f"GitHub {method} failed with HTTP {response.status_code}")
                return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise PublishError(
                f"GitHub {method} request failed; rerun to reconcile the release"
            ) from exc

    def _list(self, path: str) -> list[dict[str, Any]]:
        """Read all pages of a release or asset collection."""
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            items = self._request("GET", f"{path}?per_page=100&page={page}")
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise PublishError("GitHub returned an invalid collection")
            result.extend(items)
            if len(items) < 100:
                return result
            page += 1

    def prepare_release(self, tag: str) -> Release:
        """Find or create a draft only after checking public visibility and tag existence."""
        validate_tag(tag)
        repo = self._request("GET", self.repo_path)
        if not isinstance(repo, dict) or repo.get("private") is not False:
            raise PublishError("Skill discovery requires a public GitHub repository")
        self._request("GET", f"{self.repo_path}/git/ref/tags/{quote(tag, safe='')}")
        candidates = self._list(f"{self.repo_path}/releases")
        matching = [item for item in candidates if item.get("tag_name") == tag]
        if len(matching) > 1:
            raise PublishError("Multiple releases use this tag; resolve them before publishing")
        raw = (
            matching[0]
            if matching
            else self._request(
                "POST",
                f"{self.repo_path}/releases",
                payload={
                    "tag_name": tag,
                    "name": tag,
                    "draft": True,
                    "prerelease": False,
                    "body": "Individual MailWebhook skill ZIPs and their discovery index.",
                },
            )
        )
        release = Release.model_validate(raw)
        if release.tag_name != tag:
            raise PublishError("GitHub returned a release for another tag")
        return release

    def assets(self, release: Release) -> dict[str, Asset]:
        """Return uniquely named assets, including incomplete uploads for failure detection."""
        assets = [
            Asset.model_validate(item)
            for item in self._list(f"{self.repo_path}/releases/{release.id}/assets")
        ]
        if len({asset.name for asset in assets}) != len(assets):
            raise PublishError("Release contains duplicate asset names")
        return {asset.name: asset for asset in assets}

    def ensure_asset(
        self,
        release: Release,
        assets: dict[str, Asset],
        filename: str,
        data: bytes,
        media_type: str,
    ) -> Asset:
        """Upload exact bytes or reuse an identical asset without ever replacing one."""
        expected_path = f"{self.repo_path}/releases/{release.id}/assets"
        if filename in assets:
            asset = assets[filename]
        else:
            if not release.draft:
                raise PublishError("Published release is missing an asset; use a new tag")
            upload_url = release.upload_url.split("{", 1)[0]
            if upload_url != self.settings.uploads_url + expected_path:
                raise PublishError("Unexpected upload URL; refusing to send credentials")
            raw = self._request(
                "POST",
                expected_path + "?name=" + quote(filename, safe=""),
                data=data,
                content_type=media_type,
                upload=True,
            )
            asset = Asset.model_validate(raw)
        if (
            asset.name != filename
            or asset.state != "uploaded"
            or asset.content_type != media_type
            or asset.size != len(data)
        ):
            raise PublishError(f"Asset {filename} is incomplete or has conflicting metadata")
        expected_digest = content_digest(data)
        if asset.digest is not None:
            if asset.digest != expected_digest:
                raise PublishError(f"Asset {filename} has different bytes; use a new tag")
        else:
            # Older assets can lack a server digest. Verify their authenticated
            # download instead of guessing from name, size, or the source tree.
            self._check_download(
                self.api,
                self.settings.api_url + f"{self.repo_path}/releases/assets/{asset.id}",
                expected_digest,
                len(data),
                None,
                headers={
                    "Authorization": f"Bearer {self.settings.token.get_secret_value()}",
                    "Accept": "application/octet-stream",
                },
            )
        url = urlsplit(str(asset.browser_download_url))
        expected_origin = urlsplit(self.settings.server_url)
        expected_download = (
            f"/{self.settings.repository}/releases/download/{release.tag_name}/{filename}"
        )
        if (
            url.scheme != "https"
            or url.netloc != expected_origin.netloc
            or unquote(url.path) != expected_download
            or url.query
            or url.fragment
        ):
            raise PublishError(f"Asset {filename} does not have a versioned release URL")
        assets[filename] = asset
        return asset

    def publish(self, release: Release) -> None:
        """Publish only after every ZIP and the discovery index have been uploaded."""
        if release.draft:
            updated = Release.model_validate(
                self._request(
                    "PATCH",
                    f"{self.repo_path}/releases/{release.id}",
                    payload={"draft": False},
                )
            )
            if updated.draft or updated.id != release.id or updated.tag_name != release.tag_name:
                raise PublishError("GitHub did not publish the expected release")

    def _check_download(
        self,
        session: requests.Session,
        url: str,
        digest: str,
        size: int,
        media_type: str | None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Hash streamed bytes and reject wrong media types, truncation, or excess bytes."""
        try:
            with session.get(url, headers=headers, timeout=(10, 60), stream=True) as response:
                response.raise_for_status()
                if urlsplit(response.url).scheme != "https":
                    raise PublishError("Asset download redirected to a non-HTTPS URL")
                actual_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if media_type and actual_type != media_type:
                    raise PublishError("Public asset has an unexpected Content-Type")
                hasher = hashlib.sha256()
                received = 0
                for chunk in response.iter_content(chunk_size=65536):
                    received += len(chunk)
                    if received > size:
                        raise PublishError("Downloaded asset is larger than the uploaded bytes")
                    hasher.update(chunk)
                if received != size or "sha256:" + hasher.hexdigest() != digest:
                    raise PublishError("Downloaded asset does not match the uploaded bytes")
        except requests.RequestException as exc:
            raise PublishError("Release asset is not yet publicly downloadable") from exc

    def verify_public(self, asset: Asset, data: bytes, *, attempts: int = 6) -> None:
        """Require anonymous HTTPS downloads, with bounded retries for publication delay."""
        if attempts < 1:
            raise ValueError("Verification requires at least one attempt")
        for attempt in range(attempts):
            try:
                self._check_download(
                    self.public,
                    str(asset.browser_download_url),
                    content_digest(data),
                    len(data),
                    asset.content_type,
                )
                return
            except PublishError:
                if attempt + 1 == attempts:
                    raise
                time.sleep(2)


def publish_archives(
    client: GitHubClient,
    artifacts: list[ArchiveArtifact],
    archive_dir: Path,
    tag: str,
    index_path: Path,
) -> DiscoveryIndex:
    """Publish ZIPs and export the index only after anonymous byte verification.

    Args:
        client: Authenticated client with a separate anonymous download session.
        artifacts: Validated manifest records from the archive builder.
        archive_dir: Directory holding the already-finalized ZIP files.
        tag: Existing version tag identifying this release.
        index_path: New output path for the verified manual website handoff.

    Returns:
        The validated discovery index also uploaded as a release asset.

    Raises:
        PublishError: If bytes, assets, visibility, or public verification disagree.
        ValueError: If a manifest is empty, duplicated, or output already exists.
    """
    if not artifacts or len({item.name for item in artifacts}) != len(artifacts):
        raise ValueError("Manifest must contain unique skill names")
    if index_path.exists() or index_path.is_symlink():
        raise ValueError("Index output already exists; choose a new handoff path")
    # Read and validate once. These exact buffers are uploaded and hashed; no ZIP
    # is regenerated or reopened after the bytes have been accepted here.
    pending: list[tuple[ArchiveArtifact, bytes]] = []
    for artifact in sorted(artifacts, key=lambda item: item.name):
        artifact = ArchiveArtifact.model_validate(artifact.model_dump())
        path = archive_dir / artifact.filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Archive is not a regular file: {artifact.filename}")
        data = path.read_bytes()
        if len(data) != artifact.size or content_digest(data) != artifact.digest:
            raise PublishError(f"Archive changed after packaging: {artifact.filename}")
        pending.append((artifact, data))

    release = client.prepare_release(tag)
    assets = client.assets(release)
    expected_names = {item.filename for item, _ in pending} | {"index.json"}
    if set(assets) - expected_names:
        raise PublishError("Release contains unexpected assets; use a dedicated new tag")
    entries: list[DiscoveryEntry] = []
    verified_assets: list[tuple[Asset, bytes]] = []
    for artifact, data in pending:
        asset = client.ensure_asset(release, assets, artifact.filename, data, "application/zip")
        entries.append(
            DiscoveryEntry(
                name=artifact.name,
                description=artifact.description,
                url=asset.browser_download_url,
                digest=content_digest(data),
            )
        )
        verified_assets.append((asset, data))
    index = DiscoveryIndex(skills=entries)
    index_bytes = (
        json.dumps(index.model_dump(mode="json", by_alias=True), indent=2) + "\n"
    ).encode()
    index_asset = client.ensure_asset(
        release, assets, "index.json", index_bytes, "application/json"
    )
    # Stage index before publishing so an immutable release can contain it.
    client.publish(release)
    for asset, data in [*verified_assets, (index_asset, index_bytes)]:
        client.verify_public(asset, data)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("xb") as output:
        output.write(index_bytes)
    return index

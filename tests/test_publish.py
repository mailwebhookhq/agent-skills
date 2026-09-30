"""Exercise release publication against mocked GitHub and anonymous HTTP endpoints."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
import requests
import responses
from pydantic import ValidationError
from responses import matchers

from release_tools.models import ArchiveArtifact
from release_tools.publish import (
    Asset,
    GitHubClient,
    GitHubSettings,
    PublishError,
    Release,
    publish_archives,
    validate_tag,
)

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
SERVER = "https://github.com"
REPOSITORY = "mailwebhookhq/agent-skills"
REPO_URL = f"{API}/repos/{REPOSITORY}"
RELEASE_URL = f"{REPO_URL}/releases/7"
UPLOAD_URL = f"{UPLOADS}/repos/{REPOSITORY}/releases/7/assets"
TAG = "v1.2.3"
DRAFT_TAG = "untagged-0123456789abcdef0123"
TOKEN = "fixture-token-not-a-secret"


def digest(data: bytes) -> str:
    """Calculate expected hashes independently from the publishing implementation."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def download_url(filename: str) -> str:
    """Return the public version-specific URL expected from this fixture release."""
    return f"{SERVER}/{REPOSITORY}/releases/download/{TAG}/{filename}"


def release_json(*, draft: bool = True) -> dict[str, Any]:
    """Represent the minimal GitHub release contract used by the publisher."""
    return {
        "id": 7,
        "tag_name": TAG,
        "draft": draft,
        "upload_url": UPLOAD_URL + "{?name,label}",
        "html_url": f"{SERVER}/{REPOSITORY}/releases/tag/{DRAFT_TAG if draft else TAG}",
    }


def asset_json(
    filename: str, data: bytes, *, asset_id: int = 11, draft: bool = False
) -> dict[str, Any]:
    """Represent a successful upload, binding its metadata to supplied bytes."""
    return {
        "id": asset_id,
        "name": filename,
        "state": "uploaded",
        "content_type": "application/zip" if filename.endswith(".zip") else "application/json",
        "size": len(data),
        "digest": digest(data),
        "browser_download_url": download_url(filename).replace(
            f"/download/{TAG}/", f"/download/{DRAFT_TAG if draft else TAG}/"
        ),
    }


def index_bytes(artifact: ArchiveArtifact, *, url: str | None = None) -> bytes:
    """Serialize the documented discovery index, independently of publisher models."""
    document = {
        "$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
        "skills": [
            {
                "name": artifact.name,
                "description": artifact.description,
                "type": "archive",
                "url": url or download_url(artifact.filename),
                "digest": artifact.digest,
            }
        ],
    }
    return (json.dumps(document, indent=2) + "\n").encode()


@pytest.fixture
def client() -> Iterator[GitHubClient]:
    """Provide real isolated sessions while responses blocks external networking."""
    instance = GitHubClient(
        GitHubSettings(
            repository=REPOSITORY,
            token=TOKEN,
            api_url=API,
            uploads_url=UPLOADS,
            server_url=SERVER,
        )
    )
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> Iterator[responses.RequestsMock]:
    """Block all unregistered requests and make bounded publication retries immediate."""
    monkeypatch.setattr("release_tools.publish.time.sleep", lambda _: None)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mocked:
        yield mocked


@pytest.fixture
def archive(tmp_path: Path) -> tuple[ArchiveArtifact, bytes]:
    """Write a small valid ZIP and its exact byte manifest to a temporary directory."""
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as zipped:
        zipped.writestr("SKILL.md", "---\nname: sample-skill\ndescription: Sample.\n---\n")
        zipped.writestr("LICENCE", "Fixture license")
    data = buffer.getvalue()
    artifact = ArchiveArtifact(
        name="sample-skill",
        description="Author a sample MailWebhook route.",
        filename="sample-skill.zip",
        digest=digest(data),
        size=len(data),
    )
    (tmp_path / artifact.filename).write_bytes(data)
    return artifact, data


def add_prepare(
    http: responses.RequestsMock,
    *,
    existing_release: dict[str, Any] | None = None,
    assets: list[dict[str, Any]] | None = None,
) -> None:
    """Register public visibility, existing tag, release discovery, and asset listing."""
    http.get(REPO_URL, json={"private": False})
    http.get(f"{REPO_URL}/git/ref/tags/{TAG}", json={"ref": f"refs/tags/{TAG}"})
    http.get(
        f"{REPO_URL}/releases",
        json=[] if existing_release is None else [existing_release],
        match=[matchers.query_param_matcher({"per_page": "100", "page": "1"})],
    )
    if existing_release is None:
        http.post(f"{REPO_URL}/releases", json=release_json(), status=201)
    http.get(f"{RELEASE_URL}/assets", json=assets or [])


def add_upload(
    http: responses.RequestsMock,
    filename: str,
    data: bytes,
    *,
    result: dict[str, Any] | None = None,
) -> None:
    """Require the exact upload body and explicit MIME type at the trusted origin."""
    media_type = "application/zip" if filename.endswith(".zip") else "application/json"

    def matches_bytes(request: requests.PreparedRequest) -> tuple[bool, str]:
        """Compare binary ZIP bodies without applying a text decoding transformation."""
        return request.body == data, "Upload body must equal the finalized artifact bytes"

    http.post(
        UPLOAD_URL,
        json=result or asset_json(filename, data, draft=True),
        status=201,
        match=[
            matchers.query_param_matcher({"name": filename}),
            matches_bytes,
            matchers.header_matcher(
                {"Authorization": f"Bearer {TOKEN}", "Content-Type": media_type}
            ),
        ],
    )


def add_public_downloads(
    http: responses.RequestsMock,
    artifact: ArchiveArtifact,
    data: bytes,
    *,
    manifest_bytes: bytes | None = None,
) -> None:
    """Provide final anonymous downloads for both the ZIP and generated index."""
    http.get(download_url(artifact.filename), body=data, content_type="application/zip")
    http.get(
        download_url("index.json"),
        body=manifest_bytes or index_bytes(artifact),
        content_type="application/json",
    )


def add_publication(http: responses.RequestsMock, assets: list[dict[str, Any]]) -> None:
    """Expose final asset URLs only in the metadata fetched after publication."""
    http.patch(RELEASE_URL, json=release_json(draft=False))
    http.get(f"{RELEASE_URL}/assets", json=assets)


def add_new_release(http: responses.RequestsMock, artifact: ArchiveArtifact, data: bytes) -> None:
    """Stage a complete new draft release and its publish response."""
    add_prepare(http)
    add_upload(http, artifact.filename, data)
    add_upload(http, "index.json", index_bytes(artifact))
    add_publication(
        http, [asset_json(artifact.filename, data), asset_json("index.json", index_bytes(artifact))]
    )


def test_publish_uploads_exact_bytes_before_exposing_verified_index(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Publish only after staging every asset, then export only after anonymous checks."""
    artifact, data = archive
    output = tmp_path / "handoff" / "index.json"
    add_new_release(http, artifact, data)
    add_public_downloads(http, artifact, data)

    observed_urls: list[str] = []

    def observe_response(response: requests.Response) -> requests.Response:
        """Ensure even the final public request precedes writing the handoff index."""
        assert not output.exists()
        observed_urls.append(response.url)
        return response

    http.response_callback = observe_response
    result = publish_archives(client, [artifact], tmp_path, TAG, output)

    assert output.read_bytes() == index_bytes(artifact)
    assert result.skills[0].digest == digest(data)
    assert observed_urls[-1] == download_url("index.json")
    calls = [(call.request.method, call.request.url) for call in http.calls]
    assert calls == [
        ("GET", REPO_URL),
        ("GET", f"{REPO_URL}/git/ref/tags/{TAG}"),
        ("GET", f"{REPO_URL}/releases?per_page=100&page=1"),
        ("POST", f"{REPO_URL}/releases"),
        ("GET", f"{RELEASE_URL}/assets?per_page=100&page=1"),
        ("POST", f"{UPLOAD_URL}?name={artifact.filename}"),
        ("POST", f"{UPLOAD_URL}?name=index.json"),
        ("PATCH", RELEASE_URL),
        ("GET", f"{RELEASE_URL}/assets?per_page=100&page=1"),
        ("GET", download_url(artifact.filename)),
        ("GET", download_url("index.json")),
    ]
    created = json.loads(http.calls[3].request.body)
    assert created["draft"] is True
    assert created["tag_name"] == TAG
    for call in http.calls[-2:]:
        assert "Authorization" not in call.request.headers


@pytest.mark.parametrize("draft", [True, False])
def test_identical_release_retry_reuses_assets_without_reuploading(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    draft: bool,
) -> None:
    """Recover matching drafts or published releases without replacing any asset."""
    artifact, data = archive
    add_prepare(
        http,
        existing_release=release_json(draft=draft),
        assets=[
            asset_json(artifact.filename, data, draft=draft),
            asset_json("index.json", index_bytes(artifact), draft=draft),
        ],
    )
    if draft:
        add_publication(
            http,
            [asset_json(artifact.filename, data), asset_json("index.json", index_bytes(artifact))],
        )
    add_public_downloads(http, artifact, data)
    output = tmp_path / "index.json"

    publish_archives(client, [artifact], tmp_path, TAG, output)

    mutations = [call.request.method for call in http.calls if call.request.method != "GET"]
    assert mutations == (["PATCH"] if draft else [])
    assert output.read_bytes() == index_bytes(artifact)


@pytest.mark.parametrize("existing_zip", [False, True])
def test_temporary_draft_urls_are_resolved_before_staging_index(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    existing_zip: bool,
) -> None:
    """Publish new drafts and recover ZIP-only drafts without exporting temporary URLs."""
    artifact, data = archive
    draft_zip = asset_json(artifact.filename, data, draft=True)
    add_prepare(
        http,
        existing_release=release_json() if existing_zip else None,
        assets=[draft_zip] if existing_zip else [],
    )
    if not existing_zip:
        add_upload(http, artifact.filename, data, result=draft_zip)
    add_upload(
        http,
        "index.json",
        index_bytes(artifact),
        result=asset_json("index.json", index_bytes(artifact), asset_id=12, draft=True),
    )
    add_publication(
        http,
        [
            asset_json(artifact.filename, data),
            asset_json("index.json", index_bytes(artifact), asset_id=12),
        ],
    )
    add_public_downloads(http, artifact, data)
    output = tmp_path / "index.json"

    publish_archives(client, [artifact], tmp_path, TAG, output)

    assert output.read_bytes() == index_bytes(artifact)
    assert DRAFT_TAG.encode() not in output.read_bytes()
    assert not any(DRAFT_TAG in call.request.url for call in http.calls)
    uploads = [call.request.url for call in http.calls if call.request.method == "POST"]
    assert (f"{UPLOAD_URL}?name={artifact.filename}" in uploads) is not existing_zip
    assert sum(call.request.method == "PATCH" for call in http.calls) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 99),
        ("digest", "sha256:" + "0" * 64),
        ("state", "starter"),
        ("content_type", "text/html"),
        ("size", 0),
        ("browser_download_url", download_url("sample-skill.zip").replace(TAG, DRAFT_TAG)),
        ("browser_download_url", download_url("sample-skill.zip").replace(TAG, "v9.9.9")),
        ("browser_download_url", "https://untrusted.example/sample-skill.zip"),
    ],
)
def test_changed_asset_after_publication_withholds_handoff(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """Require final GitHub metadata to confirm the staged identity, URL, and bytes."""
    artifact, data = archive
    add_prepare(http)
    add_upload(http, artifact.filename, data)
    add_upload(http, "index.json", index_bytes(artifact))
    changed = asset_json(artifact.filename, data)
    changed[field] = value
    add_publication(http, [changed, asset_json("index.json", index_bytes(artifact))])
    output = tmp_path / "index.json"

    with pytest.raises(PublishError):
        publish_archives(client, [artifact], tmp_path, TAG, output)

    assert not output.exists()
    assert not any(call.request.url.startswith(SERVER) for call in http.calls)
    assert sum(call.request.method == "PATCH" for call in http.calls) == 1


@pytest.mark.parametrize("unexpected", [False, True])
def test_changed_asset_inventory_after_publication_withholds_handoff(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    unexpected: bool,
) -> None:
    """Reject missing or newly added assets after publication without uploading again."""
    artifact, data = archive
    add_prepare(http)
    add_upload(http, artifact.filename, data)
    add_upload(http, "index.json", index_bytes(artifact))
    final_assets = [asset_json(artifact.filename, data)]
    if unexpected:
        final_assets.extend(
            [asset_json("index.json", index_bytes(artifact)), asset_json("extra.zip", b"extra")]
        )
    add_publication(http, final_assets)
    output = tmp_path / "index.json"

    with pytest.raises(PublishError, match="assets differ"):
        publish_archives(client, [artifact], tmp_path, TAG, output)

    assert not output.exists()
    assert http.calls[-1].request.method == "GET"


@pytest.mark.parametrize("private", [True, None, "false"])
def test_private_or_unproven_visibility_rejects_before_release_creation(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    private: object,
) -> None:
    """Require an explicitly public repository before attempting any publication."""
    artifact, _ = archive
    http.get(REPO_URL, json={"private": private})
    with pytest.raises(PublishError, match="public"):
        publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    assert len(http.calls) == 1


def test_missing_tag_is_not_created_by_publisher(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Fail on an absent source tag before any release or tag mutations."""
    artifact, _ = archive
    http.get(REPO_URL, json={"private": False})
    http.get(f"{REPO_URL}/git/ref/tags/{TAG}", status=404)
    with pytest.raises(PublishError, match="404"):
        publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    assert all(call.request.method == "GET" for call in http.calls)


def test_changed_local_bytes_fail_before_network(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Reject same-length changes instead of publishing a stale packaging digest."""
    artifact, data = archive
    (tmp_path / artifact.filename).write_bytes(bytes([data[0] ^ 1]) + data[1:])
    with pytest.raises(PublishError, match="changed"):
        publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    assert not http.calls


@pytest.mark.parametrize("existing_kind", ["file", "symlink", "dangling-symlink"])
def test_existing_index_is_not_overwritten_or_followed(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    existing_kind: str,
) -> None:
    """Preserve previous handoffs and reject symbolic links before networking."""
    artifact, _ = archive
    output = tmp_path / "index.json"
    previous = b"previous-release-index"
    target = tmp_path / "target.json"
    if existing_kind == "file":
        output.write_bytes(previous)
    else:
        if existing_kind == "symlink":
            target.write_bytes(previous)
        output.symlink_to(target)
    with pytest.raises(ValueError, match="already exists"):
        publish_archives(client, [artifact], tmp_path, TAG, output)
    assert not http.calls
    if existing_kind != "dangling-symlink":
        assert output.read_bytes() == previous


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "starter"),
        ("digest", "sha256:" + "0" * 64),
        ("content_type", "application/octet-stream"),
        ("size", 0),
    ],
)
def test_conflicting_existing_assets_are_never_overwritten(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """Leave incomplete or conflicting uploads untouched and withhold the index."""
    artifact, data = archive
    conflicting = asset_json(artifact.filename, data)
    conflicting[field] = value
    add_prepare(http, existing_release=release_json(), assets=[conflicting])
    output = tmp_path / "index.json"
    with pytest.raises(PublishError):
        publish_archives(client, [artifact], tmp_path, TAG, output)
    assert not output.exists()
    assert all(call.request.method == "GET" for call in http.calls)


def test_upload_server_digest_mismatch_prevents_publishing(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Reject a server response that fails to attest to the exact uploaded bytes."""
    artifact, data = archive
    add_prepare(http)
    wrong = asset_json(artifact.filename, data)
    wrong["digest"] = "sha256:" + "f" * 64
    add_upload(http, artifact.filename, data, result=wrong)
    with pytest.raises(PublishError, match="different bytes"):
        publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    assert not any(call.request.method == "PATCH" for call in http.calls)


@pytest.mark.parametrize("problem", ["corruption", "truncated", "oversized", "mime", "404"])
def test_public_verification_failure_never_exports_index(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    problem: str,
) -> None:
    """Withhold the website handoff until anonymous downloads match bytes and media."""
    artifact, data = archive
    add_new_release(http, artifact, data)
    body = data
    if problem == "corruption":
        body = bytes([data[0] ^ 1]) + data[1:]
    elif problem == "truncated":
        body = data[:-1]
    elif problem == "oversized":
        body = data + b"!"
    http.get(
        download_url(artifact.filename),
        body=body,
        status=404 if problem == "404" else 200,
        content_type="text/html" if problem == "mime" else "application/zip",
    )
    output = tmp_path / "index.json"
    with pytest.raises(PublishError):
        publish_archives(client, [artifact], tmp_path, TAG, output)
    assert not output.exists()
    public_calls = [call for call in http.calls if call.request.url.startswith(SERVER)]
    assert len(public_calls) == 6
    assert all("Authorization" not in call.request.headers for call in public_calls)


def test_public_index_corruption_also_withholds_handoff(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Verify the published discovery index itself before exporting its local copy."""
    artifact, data = archive
    add_new_release(http, artifact, data)
    http.get(download_url(artifact.filename), body=data, content_type="application/zip")
    http.get(download_url("index.json"), body=b"{}", content_type="application/json")
    output = tmp_path / "index.json"
    with pytest.raises(PublishError):
        publish_archives(client, [artifact], tmp_path, TAG, output)
    assert not output.exists()


def test_public_redirects_never_include_authorization(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Follow GitHub asset CDN redirects without exposing the API token."""
    artifact, data = archive
    add_new_release(http, artifact, data)
    cdn = "https://release-assets.githubusercontent.com/example/sample-skill.zip?signature=test"
    http.get(download_url(artifact.filename), status=302, headers={"Location": cdn})
    http.get(cdn, body=data, content_type="application/zip")
    http.get(
        download_url("index.json"), body=index_bytes(artifact), content_type="application/json"
    )
    publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    for call in http.calls:
        if call.request.url.startswith((SERVER, "https://release-assets.githubusercontent.com")):
            assert "Authorization" not in call.request.headers


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://untrusted.example/uploads{?name,label}",
        UPLOAD_URL.replace("/7/", "/8/") + "{?name,label}",
        UPLOAD_URL + "?unexpected=true",
        UPLOAD_URL.replace("https:", "http:") + "{?name,label}",
    ],
)
def test_tampered_upload_url_is_rejected_before_credentials_are_sent(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    unsafe_url: str,
) -> None:
    """Require the release-specific upload URL to match the configured trusted origin."""
    artifact, _ = archive
    release = release_json()
    release["upload_url"] = unsafe_url
    add_prepare(http, existing_release=release)
    with pytest.raises(PublishError, match="upload URL"):
        publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    assert all(call.request.method == "GET" for call in http.calls)


def test_missing_server_digest_requires_authenticated_byte_verification(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Reuse older assets only after checking authenticated and anonymous downloads."""
    artifact, data = archive
    legacy = asset_json(artifact.filename, data)
    legacy["digest"] = None
    add_prepare(
        http,
        existing_release=release_json(draft=False),
        assets=[legacy, asset_json("index.json", index_bytes(artifact), asset_id=12)],
    )
    asset_api = f"{REPO_URL}/releases/assets/11"
    cdn = "https://release-assets.githubusercontent.com/legacy.zip"
    http.get(
        asset_api,
        status=302,
        headers={"Location": cdn},
        match=[
            matchers.header_matcher(
                {"Authorization": f"Bearer {TOKEN}", "Accept": "application/octet-stream"}
            )
        ],
    )
    http.get(cdn, body=data, content_type="application/octet-stream")
    add_public_downloads(http, artifact, data)
    publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    redirected = [call for call in http.calls if call.request.url == cdn]
    assert len(redirected) == 1
    assert "Authorization" not in redirected[0].request.headers
    assert all(call.request.method == "GET" for call in http.calls)


def test_paginated_releases_find_existing_draft_on_second_page(
    http: responses.RequestsMock, client: GitHubClient
) -> None:
    """Avoid creating a duplicate release when its tag is absent from page one."""
    http.get(REPO_URL, json={"private": False})
    http.get(f"{REPO_URL}/git/ref/tags/{TAG}", json={"ref": f"refs/tags/{TAG}"})
    http.get(
        f"{REPO_URL}/releases",
        json=[{"tag_name": f"old-{number}"} for number in range(100)],
        match=[matchers.query_param_matcher({"per_page": "100", "page": "1"})],
    )
    http.get(
        f"{REPO_URL}/releases",
        json=[release_json()],
        match=[matchers.query_param_matcher({"per_page": "100", "page": "2"})],
    )
    assert client.prepare_release(TAG).id == 7
    assert len(http.calls) == 4
    assert all(call.request.method == "GET" for call in http.calls)


@pytest.mark.parametrize("draft", [True, False])
def test_unexpected_assets_fail_without_mutation(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    draft: bool,
) -> None:
    """Prevent attaching discovery metadata to unrelated release contents."""
    artifact, _ = archive
    add_prepare(
        http,
        existing_release=release_json(draft=draft),
        assets=[asset_json("unrelated.zip", b"unexpected")],
    )
    with pytest.raises(PublishError, match="unexpected assets"):
        publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    assert all(call.request.method == "GET" for call in http.calls)


def test_published_release_missing_index_is_not_modified(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Require a fresh tag when an already published release lacks required assets."""
    artifact, data = archive
    add_prepare(
        http,
        existing_release=release_json(draft=False),
        assets=[asset_json(artifact.filename, data)],
    )
    with pytest.raises(PublishError, match="missing an asset"):
        publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    assert all(call.request.method == "GET" for call in http.calls)


@pytest.mark.parametrize(
    "tag", ["", "../main", "v1/branch", "v1..2", "v1.lock", "-v1", "v1.", "v1\n"]
)
def test_invalid_tags_rejected_at_client_boundary(
    http: responses.RequestsMock, client: GitHubClient, tag: str
) -> None:
    """Reject ambiguous or unsafe ref inputs before performing network requests."""
    with pytest.raises(ValueError):
        client.prepare_release(tag)
    assert not http.calls


def test_portable_tag_is_accepted() -> None:
    """Allow ordinary semantic version tags with prerelease suffixes."""
    assert validate_tag("v1.2.3-rc.1") == "v1.2.3-rc.1"


@pytest.mark.parametrize(
    "origin",
    ["http://api.example", "https://user:password@api.example", "https://api.example/path"],
)
def test_settings_require_trusted_https_origins(origin: str) -> None:
    """Reject unencrypted origins, embedded credentials, and ambiguous URL prefixes."""
    with pytest.raises(ValidationError):
        GitHubSettings(
            repository=REPOSITORY,
            token=TOKEN,
            api_url=origin,
            uploads_url=UPLOADS,
            server_url=SERVER,
        )


def test_verification_requires_a_positive_attempt_count(
    http: responses.RequestsMock, client: GitHubClient
) -> None:
    """Reject a disabled verification loop instead of silently treating it as success."""
    asset = Asset.model_validate(asset_json("sample.zip", b"bytes"))
    with pytest.raises(ValueError, match="at least one"):
        client.verify_public(asset, b"bytes", attempts=0)
    assert not http.calls


def test_duplicate_asset_names_are_rejected(
    http: responses.RequestsMock, client: GitHubClient
) -> None:
    """Refuse ambiguous server collections instead of silently keeping one asset."""
    item = asset_json("sample.zip", b"bytes")
    http.get(f"{RELEASE_URL}/assets", json=[item, item])
    with pytest.raises(PublishError, match="duplicate"):
        client.assets(Release.model_validate(release_json()))


def test_index_preserves_returned_versioned_download_url(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Use GitHub's returned URL spelling instead of reconstructing a release link."""
    artifact, data = archive
    returned = download_url(artifact.filename).replace("/sample-skill.zip", "/%73ample-skill.zip")
    upload_result = asset_json(artifact.filename, data)
    upload_result["browser_download_url"] = returned
    expected_index = index_bytes(artifact, url=returned)
    add_prepare(http)
    add_upload(http, artifact.filename, data, result=upload_result)
    add_upload(http, "index.json", expected_index)
    add_publication(http, [upload_result, asset_json("index.json", expected_index)])
    # Requests normalizes unreserved URL escapes on the wire. The index must
    # still retain the versioned URL supplied by the GitHub metadata response.
    http.get(download_url(artifact.filename), body=data, content_type="application/zip")
    http.get(download_url("index.json"), body=expected_index, content_type="application/json")
    output = tmp_path / "index.json"

    publish_archives(client, [artifact], tmp_path, TAG, output)

    assert json.loads(output.read_bytes())["skills"][0]["url"] == returned


def test_transient_public_unavailability_recovers_before_handoff(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Allow eventual public availability without publishing the draft twice."""
    artifact, data = archive
    add_new_release(http, artifact, data)
    http.get(download_url(artifact.filename), status=404)
    add_public_downloads(http, artifact, data)
    output = tmp_path / "index.json"

    publish_archives(client, [artifact], tmp_path, TAG, output)

    assert output.read_bytes() == index_bytes(artifact)
    assert sum(call.request.method == "PATCH" for call in http.calls) == 1
    assert sum(call.request.url == download_url(artifact.filename) for call in http.calls) == 2


def test_legacy_asset_corruption_prevents_publish(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Reject legacy same-size corrupted assets when no server digest is available."""
    artifact, data = archive
    legacy = asset_json(artifact.filename, data)
    legacy.pop("digest")
    add_prepare(http, existing_release=release_json(), assets=[legacy])
    corrupted = bytes([data[0] ^ 1]) + data[1:]
    http.get(
        f"{REPO_URL}/releases/assets/11", body=corrupted, content_type="application/octet-stream"
    )
    with pytest.raises(PublishError, match="does not match"):
        publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    assert all(call.request.method == "GET" for call in http.calls)


@pytest.mark.parametrize(
    "replacement",
    [
        "https://github.com/mailwebhookhq/agent-skills/releases/latest/download/sample-skill.zip",
        "https://untrusted.example/sample-skill.zip",
        download_url("sample-skill.zip") + "?version=latest",
    ],
)
def test_nonversioned_or_untrusted_download_urls_reject_before_publication(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    replacement: str,
) -> None:
    """Reject server metadata that could disconnect a digest from its release URL."""
    artifact, data = archive
    asset = asset_json(artifact.filename, data)
    asset["browser_download_url"] = replacement
    add_prepare(http, existing_release=release_json(), assets=[asset])
    with pytest.raises(PublishError, match="versioned release URL"):
        publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    assert all(call.request.method == "GET" for call in http.calls)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("asset", download_url("sample-skill.zip").replace(TAG, "untagged-another")),
        ("asset", download_url("another.zip").replace(TAG, DRAFT_TAG)),
        (
            "asset",
            download_url("sample-skill.zip").replace(TAG, DRAFT_TAG) + "?unexpected=true",
        ),
        (
            "asset",
            download_url("sample-skill.zip").replace(TAG, DRAFT_TAG) + "#unexpected",
        ),
        ("release", f"https://untrusted.example/{REPOSITORY}/releases/tag/{DRAFT_TAG}"),
        ("release", f"{SERVER}/another/repository/releases/tag/{DRAFT_TAG}"),
        ("release", f"{SERVER}/{REPOSITORY}/releases/tag/{DRAFT_TAG}?unexpected=true"),
        ("release", f"{SERVER}/{REPOSITORY}/releases/tag/{DRAFT_TAG}#unexpected"),
    ],
)
def test_temporary_url_must_match_its_draft_release(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    """Resolve only this draft's exact asset path on the trusted GitHub origin."""
    artifact, data = archive
    release = release_json()
    asset = asset_json(artifact.filename, data, draft=True)
    if field == "asset":
        asset["browser_download_url"] = replacement
    else:
        release["html_url"] = replacement
    add_prepare(http, existing_release=release, assets=[asset])
    output = tmp_path / "index.json"

    with pytest.raises(PublishError, match="versioned release URL"):
        publish_archives(client, [artifact], tmp_path, TAG, output)

    assert not output.exists()
    assert all(call.request.method == "GET" for call in http.calls)


def test_failed_upload_is_not_retried_or_replaced_automatically(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
) -> None:
    """Leave ambiguous upstream upload failures available for explicit reconciliation."""
    artifact, _ = archive
    add_prepare(http)
    http.post(UPLOAD_URL, status=502)
    with pytest.raises(PublishError, match="502"):
        publish_archives(client, [artifact], tmp_path, TAG, tmp_path / "index.json")
    upload_calls = [call for call in http.calls if call.request.url.startswith(UPLOADS)]
    assert len(upload_calls) == 1
    assert not any(call.request.method in {"DELETE", "PATCH"} for call in http.calls)


@pytest.mark.parametrize("problem", ["empty", "duplicate"])
def test_invalid_manifest_rejected_before_network(
    http: responses.RequestsMock,
    client: GitHubClient,
    archive: tuple[ArchiveArtifact, bytes],
    tmp_path: Path,
    problem: str,
) -> None:
    """Require a nonempty unambiguous skill inventory before creating a release."""
    artifact, _ = archive
    artifacts = [] if problem == "empty" else [artifact, artifact]
    with pytest.raises(ValueError, match="unique skill names"):
        publish_archives(client, artifacts, tmp_path, TAG, tmp_path / "index.json")
    assert not http.calls

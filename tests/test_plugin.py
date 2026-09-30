"""Verify portable plugin packaging without diverging from standalone skills."""

import hashlib
import io
import json
import os
import stat
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from PIL import Image
from pydantic import TypeAdapter, ValidationError

from release_tools.archives import build_archives
from release_tools.models import ArchiveArtifact, PluginArchiveArtifact, ReleaseArtifact
from release_tools.plugin import (
    PluginManifest,
    parse_plugin_manifest,
    validate_plugin_icon,
    validate_plugin_members,
)


@pytest.fixture
def manifest() -> dict[str, Any]:
    """Provide supported listing metadata with one shared branding asset."""
    return {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": "mailwebhook",
        "version": "1.0.0",
        "description": "Create and review MailWebhook route JSON.",
        "license": "MIT",
        "author": {"name": "MailWebhook", "url": "https://www.mailwebhook.com"},
        "homepage": "https://www.mailwebhook.com",
        "repository": "https://github.com/mailwebhookhq/agent-skills",
        "keywords": ["email", "json"],
        "extensions": {
            "com.openai": {
                "interface": {
                    "displayName": "MailWebhook",
                    "shortDescription": "Author email route JSON",
                    "longDescription": "Create and review MailWebhook routes and pipelines.",
                    "developerName": "MailWebhook",
                    "category": "Developer Tools",
                    "websiteURL": "https://www.mailwebhook.com",
                    "privacyPolicyURL": "https://www.mailwebhook.com/privacy",
                    "termsOfServiceURL": "https://www.mailwebhook.com/terms",
                    "composerIcon": "./assets/icon.png",
                    "logo": "./assets/icon.png",
                    "defaultPrompt": [
                        "Draft a route for incoming invoices.",
                        "Review my pipeline.",
                    ],
                }
            }
        },
    }


def _png(size: tuple[int, int] = (48, 48), *, format: str = "PNG") -> bytes:
    """Generate a complete small image fixture in the requested format."""
    stream = io.BytesIO()
    Image.new("RGB", size, color="#127c99").save(stream, format=format)
    return stream.getvalue()


def _write_manifest(root: Path, manifest: dict[str, Any]) -> None:
    """Persist one test's manifest without changing other fixture inputs."""
    (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def plugin_project(tmp_path: Path, manifest: dict[str, Any]) -> Path:
    """Create two skills so integration checks cover complete plugin discovery."""
    (tmp_path / "LICENCE").write_text("MIT licence fixture\n", encoding="utf-8")
    for name in ("alpha", "zeta"):
        skill = tmp_path / "skills" / name
        (skill / "references").mkdir(parents=True)
        (skill / "agents").mkdir()
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Author {name}.\n---\n\nBuild useful JSON.\n",
            encoding="utf-8",
        )
        (skill / "references" / "contract.json").write_bytes(b'{"type":"object"}\n')
        (skill / "agents" / "openai.yaml").write_text(
            "interface:\n  display_name: Example\n  short_description: Author JSON\n",
            encoding="utf-8",
        )
    (tmp_path / "skills" / "zeta" / "LICENCE").write_bytes(b"Specific licence\n")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "icon.png").write_bytes(_png())
    (tmp_path / "assets" / "private.txt").write_bytes(b"not part of the distribution")
    _write_manifest(tmp_path, manifest)
    return tmp_path


def _build(root: Path, output: str = "dist", **changes: Any) -> list[ReleaseArtifact]:
    """Call the public builder with the test repository's explicit plugin input."""
    options: dict[str, Any] = {"plugin_path": root / "plugin.json"}
    options.update(changes)
    return build_archives(root / "skills", root / "LICENCE", root / output, **options)


def test_plugin_has_root_manifest_and_identical_complete_skills(plugin_project: Path) -> None:
    """Bundle all skill bytes under skills/ without changing their standalone ZIPs."""
    root = plugin_project
    plain = build_archives(root / "skills", root / "LICENCE", root / "plain")
    artifacts = _build(root)
    assert artifacts[:2] == plain
    assert [artifact.filename for artifact in artifacts] == [
        "alpha.zip",
        "zeta.zip",
        "mailwebhook-plugin.zip",
    ]
    plugin_artifact = artifacts[-1]
    assert isinstance(plugin_artifact, PluginArchiveArtifact)
    data = (root / "dist" / plugin_artifact.filename).read_bytes()
    assert plugin_artifact.size == len(data)
    assert plugin_artifact.digest == "sha256:" + hashlib.sha256(data).hexdigest()
    with zipfile.ZipFile(io.BytesIO(data)) as plugin:
        assert plugin.namelist() == sorted(plugin.namelist())
        assert plugin.testzip() is None
        assert plugin.read("LICENCE") == (root / "LICENCE").read_bytes()
        assert plugin.read("assets/icon.png") == (root / "assets/icon.png").read_bytes()
        assert "assets/private.txt" not in plugin.namelist()
        assert "SKILL.md" not in plugin.namelist()
        assert "mcp.json" not in plugin.namelist()
        manifest = PluginManifest.model_validate_json(plugin.read("plugin.json"))
        assert manifest.version == "1.0.0"
        for artifact in plain:
            assert (root / "plain" / artifact.filename).read_bytes() == (
                root / "dist" / artifact.filename
            ).read_bytes()
            with zipfile.ZipFile(root / "dist" / artifact.filename) as standalone:
                for name in standalone.namelist():
                    bundled_name = f"skills/{artifact.name}/{name}"
                    assert standalone.read(name) == plugin.read(bundled_name)
                    assert (
                        standalone.getinfo(name).external_attr
                        == plugin.getinfo(bundled_name).external_attr
                    )
        for member in plugin.infolist():
            assert member.date_time == (1980, 1, 1, 0, 0, 0)
            assert stat.S_ISREG(member.external_attr >> 16)


def test_plugin_reuses_skill_snapshot_if_source_changes_mid_build(plugin_project: Path) -> None:
    """A concurrent edit cannot make plugin skill bytes disagree with the standalone ZIP."""
    original = Path.read_bytes
    root = plugin_project
    skill = root / "skills" / "alpha" / "SKILL.md"
    reads = 0

    def changing_read(path: Path) -> bytes:
        """Change the source immediately after its first content snapshot."""
        nonlocal reads
        content = original(path)
        if path == skill:
            reads += 1
            path.write_bytes(content + b"Concurrent edit\n")
        return content

    with patch.object(Path, "read_bytes", changing_read):
        _build(root)
    assert reads == 1
    with (
        zipfile.ZipFile(root / "dist" / "alpha.zip") as standalone,
        zipfile.ZipFile(root / "dist" / "mailwebhook-plugin.zip") as plugin,
    ):
        assert standalone.read("SKILL.md") == plugin.read("skills/alpha/SKILL.md")
        assert b"Concurrent edit" not in standalone.read("SKILL.md")


def test_version_override_only_changes_plugin_archive(plugin_project: Path) -> None:
    """Stamp release SemVer without modifying sources or standalone skill digests."""
    root = plugin_project
    original = (root / "plugin.json").read_bytes()
    before = _build(root, "first")
    after = _build(root, "second", plugin_version="2.3.4-rc.1+build.07")
    assert (root / "plugin.json").read_bytes() == original
    assert before[:2] == after[:2]
    assert before[-1].digest != after[-1].digest
    assert after[-1].version == "2.3.4-rc.1+build.07"
    with zipfile.ZipFile(root / "second" / "mailwebhook-plugin.zip") as archive:
        assert json.loads(archive.read("plugin.json"))["version"] == "2.3.4-rc.1+build.07"


def test_plugin_build_is_reproducible_despite_source_metadata(plugin_project: Path) -> None:
    """Exclude filesystem mtimes and non-executable permissions from every artifact."""
    root = plugin_project
    first = _build(root, "first")
    for path in [root / "plugin.json", root / "assets" / "icon.png"]:
        path.chmod(0o600)
        os.utime(path, (1_000_000_000, 1_000_000_000))
    second = _build(root, "second")
    assert first == second
    for artifact in first:
        assert (root / "first" / artifact.filename).read_bytes() == (
            root / "second" / artifact.filename
        ).read_bytes()


@pytest.mark.parametrize("version", ["0.0.0", "1.2.3", "1.2.3-a.0-b.9+01.build", "1.2.3+metadata"])
def test_semver_accepts_full_version_grammar(manifest: dict[str, Any], version: str) -> None:
    """Allow canonical SemVer including prerelease and build identifiers."""
    assert parse_plugin_manifest(json.dumps(manifest).encode(), version).version == version


@pytest.mark.parametrize(
    "version",
    [
        "v1.2.3",
        "1.2",
        "01.2.3",
        "1.02.3",
        "1.2.03",
        "1.2.3-01",
        "1.2.3-alpha.01",
        "1.2.3-",
        "1.2.3+",
        "1.2.3+build..2",
        "1.2.3+a_b",
        "1.2.3\n",
        "1.2.3+" + "a" * 60,
        123,
    ],
)
def test_invalid_semver_prevents_output(plugin_project: Path, version: Any) -> None:
    """Reject versions ChatGPT cannot compare and never leave partial releases."""
    with pytest.raises(ValidationError):
        _build(plugin_project, plugin_version=version)
    assert not (plugin_project / "dist").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("displayName", "x" * 31),
        ("displayName", " "),
        ("shortDescription", "x" * 31),
        ("longDescription", "x" * 4001),
        ("developerName", "x" * 81),
        ("category", "Made Up Category"),
        ("websiteURL", "http://example.com"),
        ("defaultPrompt", ["one", "two", "three", "four"]),
        ("defaultPrompt", ["x" * 129]),
        ("defaultPrompt", ["Run", " run "]),
        ("defaultPrompt", ["Create", "Ｃｒｅａｔｅ"]),
        ("defaultPrompt", ["Use @mailwebhook"]),
        ("defaultPrompt", ["one\ntwo"]),
        ("defaultPrompt", [" "]),
        ("defaultPrompt", [123]),
        ("screenshots", ["./assets/screenshot.png"]),
        ("composerIcon", "assets/icon.png"),
        ("composerIcon", "./assets/../icon.png"),
        ("composerIcon", "./assets//icon.png"),
        ("composerIcon", "./assets/./icon.png"),
        ("composerIcon", "./assets/\\icon.png"),
        ("composerIcon", "./assets/c:icon.png"),
        ("composerIcon", "./assets/icon.png "),
        ("composerIcon", "./assets/icon\x00.png"),
        ("composerIcon", "/assets/icon.png"),
        ("composerIcon", "https://example.com/icon.png"),
        ("composerIcon", "./assets/icon.svg"),
    ],
)
def test_listing_contract_rejects_invalid_values(
    manifest: dict[str, Any], field: str, value: Any
) -> None:
    """Validate listing fields and reject unsupported content rather than omitting it."""
    manifest["extensions"]["com.openai"]["interface"][field] = value
    with pytest.raises(ValidationError):
        parse_plugin_manifest(json.dumps(manifest).encode())


@pytest.mark.parametrize("field", ["websiteURL", "privacyPolicyURL", "termsOfServiceURL"])
@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-url",
        "http://example.com/policy",
        "https://user:secret@example.com/policy",
        "https://user@example.com/policy",
        "https://example.com/" + "x" * 1005,
        123,
    ],
)
def test_listing_urls_reject_invalid_values(
    manifest: dict[str, Any], field: str, value: Any
) -> None:
    """Apply the same HTTPS, credential, and length rules to all listing URLs."""
    manifest["extensions"]["com.openai"]["interface"][field] = value
    with pytest.raises(ValidationError):
        parse_plugin_manifest(json.dumps(manifest).encode())


@pytest.mark.parametrize("field", ["websiteURL", "privacyPolicyURL", "termsOfServiceURL"])
def test_listing_urls_accept_maximum_length(manifest: dict[str, Any], field: str) -> None:
    """Preserve valid HTTPS listing URLs at the documented 1024-character limit."""
    prefix = "https://example.com/"
    value = prefix + "x" * (1024 - len(prefix))
    manifest["extensions"]["com.openai"]["interface"][field] = value
    parsed = parse_plugin_manifest(json.dumps(manifest).encode())
    serialized = json.loads(parsed.model_dump_json(by_alias=True, exclude_none=True))
    assert serialized["extensions"]["com.openai"]["interface"][field] == value


def test_policy_links_can_be_omitted_from_skills_only_manifest(manifest: dict[str, Any]) -> None:
    """Keep upload validation distinct from the public directory's policy requirement."""
    interface = manifest["extensions"]["com.openai"]["interface"]
    del interface["privacyPolicyURL"]
    del interface["termsOfServiceURL"]
    parsed = parse_plugin_manifest(json.dumps(manifest).encode())
    serialized = json.loads(parsed.model_dump_json(by_alias=True, exclude_none=True))
    assert "privacyPolicyURL" not in serialized["extensions"]["com.openai"]["interface"]
    assert "termsOfServiceURL" not in serialized["extensions"]["com.openai"]["interface"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("$schema", "https://example.com/schema.json"),
        ("name", "../escape"),
        ("description", ""),
        ("description", "x" * 1025),
        ("author", {"name": "x", "unknown": "field"}),
        ("license", " "),
        ("repository", "file:///tmp/repo"),
        ("homepage", "not-a-url"),
        ("keywords", [False]),
        ("keywords", []),
        ("skills", "./other-skills"),
        ("mcpServers", {}),
        ("extensions", {"com.openai": {"hooks": "./hooks.json"}}),
        ("extensions", {"example.com": {}}),
    ],
)
def test_manifest_contract_rejects_invalid_values(
    manifest: dict[str, Any], field: str, value: Any
) -> None:
    """Fail closed for unsupported portable fields and integration declarations."""
    manifest[field] = value
    with pytest.raises(ValidationError):
        parse_plugin_manifest(json.dumps(manifest).encode())


@pytest.mark.parametrize("data", [b"[]", b"null", b"{", b"\xff", b'{"name":"a","name":"b"}'])
def test_invalid_manifest_bytes(data: bytes) -> None:
    """Require unambiguous JSON encoded as UTF-8."""
    with pytest.raises(ValueError):
        parse_plugin_manifest(data)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not an image",
        b"x" * (5 * 1024 * 1024 + 1),
        _png((47, 47)),
        _png((48, 49)),
        _png((4097, 4097)),
        _png(format="JPEG"),
        _png()[:-12],
    ],
)
def test_invalid_icon_bytes(data: bytes) -> None:
    """Validate actual PNG contents, dimensions, completeness, and size."""
    with pytest.raises(ValueError):
        validate_plugin_icon(data)


def test_missing_or_corrupt_icons_leave_no_artifacts(plugin_project: Path) -> None:
    """Do not publish otherwise valid skill ZIPs if plugin branding is unusable."""
    icon = plugin_project / "assets" / "icon.png"
    icon.write_bytes(b"invalid PNG")
    with pytest.raises(ValueError, match="PNG"):
        _build(plugin_project)
    assert not (plugin_project / "dist").exists()
    icon.unlink()
    with pytest.raises(ValueError, match="does not exist"):
        _build(plugin_project)
    assert not (plugin_project / "dist").exists()


@pytest.mark.parametrize("relative", ["plugin.json", "assets", "assets/icon.png", "skills/alpha"])
def test_symlink_plugin_inputs_are_rejected(plugin_project: Path, relative: str) -> None:
    """Reject linked manifests, assets, and directories before dereferencing inputs."""
    target = plugin_project / relative
    original = target.with_name(target.name + "-original")
    target.rename(original)
    target.symlink_to(original, target_is_directory=original.is_dir())
    with pytest.raises(ValueError, match="symlink"):
        _build(plugin_project)
    assert not (plugin_project / "dist").exists()


def test_selected_paths_allow_aliases_above_their_roots(plugin_project: Path) -> None:
    """Allow explicit parent aliases, including the normal macOS /tmp symlink."""
    root = plugin_project
    (root / "real-output").mkdir()
    (root / "linked-output").symlink_to(root / "real-output", target_is_directory=True)
    artifacts = _build(root, "linked-output/dist")
    assert len(artifacts) == 3
    assert (root / "real-output" / "dist" / "mailwebhook-plugin.zip").is_file()


def test_selected_plugin_root_must_not_be_a_symlink(plugin_project: Path) -> None:
    """Reject a linked plugin root even though aliases above a root are permitted."""
    root = plugin_project
    link = root / "linked-root"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        _build(root, plugin_path=link / "plugin.json")
    assert not (root / "dist").exists()


def test_artifact_filename_collision_is_rejected(plugin_project: Path) -> None:
    """A skill called mailwebhook-plugin cannot overwrite the plugin ZIP."""
    root = plugin_project
    skill = root / "skills" / "alpha"
    renamed = skill.with_name("mailwebhook-plugin")
    skill.rename(renamed)
    (renamed / "SKILL.md").write_text(
        "---\nname: mailwebhook-plugin\ndescription: Example\n---\nBody\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="filenames must not conflict"):
        _build(root)
    assert not (root / "dist").exists()


def test_plugin_skill_identity_length_is_checked(
    plugin_project: Path, manifest: dict[str, Any]
) -> None:
    """Apply the plugin namespace length limit before ChatGPT submission."""
    manifest["name"] = "a" * 60
    _write_manifest(plugin_project, manifest)
    with pytest.raises(ValueError, match="combined plugin:skill name"):
        _build(plugin_project)


def test_late_plugin_failure_is_atomic(plugin_project: Path) -> None:
    """Remove staged skill ZIPs too when writing the final plugin archive fails."""
    root = plugin_project
    (root / "dist").mkdir()
    original = zipfile.ZipFile.writestr

    def fail_plugin_write(archive: zipfile.ZipFile, *args: Any, **kwargs: Any) -> None:
        """Simulate failure after all standalone skill ZIPs have been written."""
        if str(archive.filename).endswith("mailwebhook-plugin.zip"):
            raise OSError("simulated plugin write failure")
        original(archive, *args, **kwargs)

    with (
        patch.object(zipfile.ZipFile, "writestr", fail_plugin_write),
        pytest.raises(OSError, match="simulated"),
    ):
        _build(root)
    assert list((root / "dist").iterdir()) == []
    assert not list(root.glob(".skill-archives-*"))


@pytest.mark.parametrize(
    "files",
    [
        {"A.txt": 1, "a.txt": 1},
        {"é.txt": 1, "e\u0301.txt": 1},
        {"file": 1, "FILE/child": 1},
        {"file/child": 1, "FILE": 1},
        {"../file": 1},
        {"/file": 1},
        {"a\\file": 1},
        {"a//file": 1},
        {"a/./file": 1},
        {"a/\x01file": 1},
        {"a/ ": 1},
        {"/".join(["a"] * 21): 1},
        {"file": 100 * 1024 * 1024 + 1},
        {str(index): 100 * 1024 * 1024 for index in range(6)},
        {str(index): 1 for index in range(5001)},
    ],
)
def test_plugin_member_limits_and_portability(files: dict[str, int]) -> None:
    """Catch unsafe extraction layouts and documented archive size limits."""
    with pytest.raises(ValueError):
        validate_plugin_members(files)


def test_actual_skill_path_normalization_collision_fails(plugin_project: Path) -> None:
    """Exercise normalization checks on real files before any ZIP is published."""
    reference = plugin_project / "skills" / "alpha" / "references"
    # Distinct spellings are supported even on case-insensitive host filesystems.
    (reference / "ｃontract.json").write_bytes(b"ambiguous")
    with pytest.raises(ValueError, match="collide"):
        _build(plugin_project)
    assert not (plugin_project / "dist").exists()


def test_plugin_version_requires_manifest_input(plugin_project: Path) -> None:
    """Avoid silently dropping a version when the plugin build was not requested."""
    with pytest.raises(ValueError, match="requires a plugin_path"):
        _build(plugin_project, plugin_path=None, plugin_version="1.2.3")


def test_release_artifact_union_round_trips_plugin_and_legacy_skill_records() -> None:
    """Keep old manifests compatible while distinguishing plugin-only assets."""
    common = {"description": "Useful", "digest": "sha256:" + "a" * 64, "size": 100}
    payload = [
        {**common, "name": "alpha", "filename": "alpha.zip"},
        {
            **common,
            "name": "mailwebhook",
            "version": "1.0.0",
            "kind": "plugin",
            "filename": "mailwebhook-plugin.zip",
        },
    ]
    artifacts = TypeAdapter(list[ReleaseArtifact]).validate_python(payload)
    assert isinstance(artifacts[0], ArchiveArtifact)
    assert isinstance(artifacts[1], PluginArchiveArtifact)
    assert [artifact.model_dump() for artifact in artifacts] == payload
    with pytest.raises(ValidationError, match="filename"):
        PluginArchiveArtifact.model_validate({**payload[1], "filename": "../plugin.zip"})

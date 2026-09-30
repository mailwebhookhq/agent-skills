"""Check the operator-facing build command and its failure boundaries."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from release_tools.__main__ import main
from release_tools.models import ArchiveArtifact, PluginArchiveArtifact, ReleaseArtifact
from release_tools.publish import GitHubClient


def test_build_real_skill_emits_matching_manifest(tmp_path: Path) -> None:
    """Build the repository's skill and independently verify its manifest and layout."""
    output = tmp_path / "archives"
    root = Path(__file__).resolve().parents[1]
    assert (
        main(
            [
                "build",
                "--skills",
                str(root / "skills"),
                "--licence",
                str(root / "LICENCE"),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert len(manifest) == 1
    entry = manifest[0]
    data = (output / entry["filename"]).read_bytes()
    assert entry["digest"] == "sha256:" + hashlib.sha256(data).hexdigest()
    assert entry["size"] == len(data)
    with zipfile.ZipFile(output / entry["filename"]) as archive:
        assert "SKILL.md" in archive.namelist()
        assert "LICENCE" in archive.namelist()
        assert "agents/openai.yaml" in archive.namelist()
        assert "references/schemas/custom-json-mapper.schema.json" in archive.namelist()
        assert "manifest.json" not in archive.namelist()
        assert not any(name.startswith("release_tools/") for name in archive.namelist())


def test_build_plugin_uses_tag_version_and_publish_reads_both_artifact_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise CLI manifest handoff while ensuring the two ZIP layouts share skill bytes."""
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "archives"
    plugin_source = (root / "plugin.json").read_bytes()
    assert (
        main(
            [
                "build",
                "--skills",
                str(root / "skills"),
                "--licence",
                str(root / "LICENCE"),
                "--plugin",
                str(root / "plugin.json"),
                "--tag",
                "v2.3.4-rc.1+build.5",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert len(manifest) == 2
    for entry in manifest:
        data = (output / entry["filename"]).read_bytes()
        assert entry["digest"] == "sha256:" + hashlib.sha256(data).hexdigest()
        assert entry["size"] == len(data)
    with (
        zipfile.ZipFile(output / "mailwebhook-plugin.zip") as plugin,
        zipfile.ZipFile(output / "author-mailwebhook-route-json.zip") as standalone,
    ):
        packaged = json.loads(plugin.read("plugin.json"))
        assert packaged["version"] == "2.3.4-rc.1+build.5"
        interface = packaged["extensions"]["com.openai"]["interface"]
        assert interface["websiteURL"] == "https://www.mailwebhook.com/"
        assert interface["privacyPolicyURL"] == "https://www.mailwebhook.com/privacy"
        assert interface["termsOfServiceURL"] == "https://www.mailwebhook.com/terms"
        assert "SKILL.md" not in plugin.namelist()
        assert "assets/icon.png" in plugin.namelist()
        assert "LICENCE" in plugin.namelist()
        assert "manifest.json" not in plugin.namelist()
        for name in standalone.namelist():
            assert plugin.read(f"skills/author-mailwebhook-route-json/{name}") == standalone.read(
                name
            )
    assert (root / "plugin.json").read_bytes() == plugin_source
    captured: list[ReleaseArtifact] = []

    def capture_publish(
        client: GitHubClient,
        artifacts: list[ReleaseArtifact],
        archive_dir: Path,
        tag: str,
        index_path: Path,
    ) -> None:
        """Inspect the parsed CLI handoff without publishing a test release."""
        assert archive_dir == output
        assert tag == "v2.3.4-rc.1+build.5"
        captured.extend(artifacts)

    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token")
    monkeypatch.setattr("release_tools.__main__.publish_archives", capture_publish)
    assert (
        main(
            [
                "publish",
                "--archives",
                str(output),
                "--tag",
                "v2.3.4-rc.1+build.5",
                "--repository",
                "example/skills",
            ]
        )
        == 0
    )
    assert isinstance(captured[0], ArchiveArtifact)
    assert isinstance(captured[1], PluginArchiveArtifact)


@pytest.mark.parametrize("tag", ["v2", "v01.2.3", "v1.2.3\n", "v1/2.3"])
def test_plugin_build_rejects_invalid_release_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tag: str
) -> None:
    """Fail invalid release tags before writing any distribution archives."""
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "archives"
    assert (
        main(
            [
                "build",
                "--skills",
                str(root / "skills"),
                "--licence",
                str(root / "LICENCE"),
                "--plugin",
                str(root / "plugin.json"),
                "--tag",
                tag,
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert "Release failed:" in capsys.readouterr().err
    assert not output.exists()


def test_build_tag_requires_plugin(capsys: pytest.CaptureFixture[str]) -> None:
    """Avoid silently ignoring a release version when only standalone skills are built."""
    assert main(["build", "--tag", "v1.2.3"]) == 1
    assert "--tag requires --plugin" in capsys.readouterr().err


def test_build_failure_is_reported_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reject a missing input without leaving a successful-looking output directory."""
    output = tmp_path / "archives"
    assert main(["build", "--skills", str(tmp_path / "missing"), "--output", str(output)]) == 1
    error = capsys.readouterr().err
    assert "Release failed:" in error
    assert "Traceback" not in error
    assert not output.exists()


def test_publish_requires_token_before_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep unauthenticated builds separate from intentionally authenticated publication."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert main(["publish", "--tag", "v1.0.0", "--repository", "example/skills"]) == 1
    assert "Set GITHUB_TOKEN" in capsys.readouterr().err


def test_publish_rejects_bad_manifest_without_exposing_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fail malformed build metadata before constructing a release client."""
    monkeypatch.setenv("GITHUB_TOKEN", "do-not-print-this-token")
    (tmp_path / "manifest.json").write_text('{"unexpected":true}')
    assert (
        main(
            [
                "publish",
                "--tag",
                "v1.0.0",
                "--repository",
                "example/skills",
                "--archives",
                str(tmp_path),
            ]
        )
        == 1
    )
    error = capsys.readouterr().err
    assert "Release failed:" in error
    assert "do-not-print-this-token" not in error

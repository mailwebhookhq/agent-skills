"""Check the operator-facing build command and its failure boundaries."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from release_tools.__main__ import main


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

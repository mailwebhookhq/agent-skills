"""Verify independently installable ZIPs and fail-closed packaging inputs."""

import hashlib
import os
import stat
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from release_tools.archives import build_archives


@pytest.fixture
def source_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create an isolated repository layout with a root licence."""
    skills = tmp_path / "skills"
    skills.mkdir()
    licence = tmp_path / "LICENCE"
    licence.write_text("MIT licence fixture\n", encoding="utf-8")
    return skills, licence, tmp_path / "dist"


def _skill(
    skills: Path, name: str = "example-skill", description: str = "Build a useful thing."
) -> Path:
    """Create a skill with representative reference and agent metadata files."""
    root = skills / name
    root.mkdir()
    metadata = yaml.safe_dump({"name": name, "description": description}, sort_keys=False)
    (root / "SKILL.md").write_text(
        f"---\n{metadata}---\n\n# Useful instructions\n", encoding="utf-8"
    )
    (root / "references").mkdir()
    (root / "references" / "contract.json").write_text('{"type":"object"}\n', encoding="utf-8")
    (root / "agents").mkdir()
    (root / "agents" / "openai.yaml").write_text(
        "interface:\n  display_name: Example\n", encoding="utf-8"
    )
    return root


def test_archive_root_contents_metadata_and_exact_digest(
    source_tree: tuple[Path, Path, Path],
) -> None:
    """Make an installable ZIP and hash the exact finished bytes on disk."""
    skills, licence, output = source_tree
    root = _skill(skills, description="A description\nwith two lines.")
    script = root / "run.sh"
    script.write_bytes(b"#!/bin/sh\nexit 0\n")
    script.chmod(0o700)
    artifacts = build_archives(skills, licence, output)
    assert len(artifacts) == 1
    artifact = artifacts[0]
    archive_path = output / artifact.filename
    assert artifact.description == "A description\nwith two lines."
    assert artifact.size == len(archive_path.read_bytes())
    assert artifact.digest == "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == [
            "LICENCE",
            "SKILL.md",
            "agents/openai.yaml",
            "references/contract.json",
            "run.sh",
        ]
        assert archive.read("SKILL.md") == (root / "SKILL.md").read_bytes()
        assert archive.read("LICENCE") == licence.read_bytes()
        assert archive.testzip() is None
        for member in archive.infolist():
            assert member.date_time == (1980, 1, 1, 0, 0, 0)
            assert member.create_system == 3
            assert stat.S_ISREG(member.external_attr >> 16)
        assert (archive.getinfo("run.sh").external_attr >> 16) & 0o777 == 0o755
        assert (archive.getinfo("SKILL.md").external_attr >> 16) & 0o777 == 0o644


def test_archives_are_deterministic_despite_source_metadata(
    source_tree: tuple[Path, Path, Path],
) -> None:
    """Ignore source timestamps and non-executable permission differences."""
    skills, licence, first_output = source_tree
    root = _skill(skills)
    first = build_archives(skills, licence, first_output)
    (root / "SKILL.md").chmod(0o600)
    os.utime(root / "SKILL.md", (1_000_000_000, 1_000_000_000))
    second_output = first_output.parent / "second"
    second = build_archives(skills, licence, second_output)
    assert first == second
    assert (first_output / first[0].filename).read_bytes() == (
        second_output / second[0].filename
    ).read_bytes()


def test_multiple_skills_and_licence_override(source_tree: tuple[Path, Path, Path]) -> None:
    """Package sorted independent skills and honor each skill's own licence."""
    skills, licence, output = source_tree
    second = _skill(skills, "zeta")
    first = _skill(skills, "alpha")
    (second / "LICENCE").write_text("Skill-specific licence\n", encoding="utf-8")
    artifacts = build_archives(skills, licence, output)
    assert [artifact.name for artifact in artifacts] == ["alpha", "zeta"]
    with zipfile.ZipFile(output / "alpha.zip") as archive:
        assert archive.read("LICENCE") == licence.read_bytes()
        assert archive.read("SKILL.md") == (first / "SKILL.md").read_bytes()
    with zipfile.ZipFile(output / "zeta.zip") as archive:
        assert archive.read("LICENCE") == b"Skill-specific licence\n"
        assert b"zeta" in archive.read("SKILL.md")


def test_hidden_metadata_and_cache_files_are_excluded(source_tree: tuple[Path, Path, Path]) -> None:
    """Keep repository metadata and transient local files out of release bytes."""
    skills, licence, output = source_tree
    root = _skill(skills)
    for relative in [
        ".git/config",
        ".env",
        "__pycache__/test.pyc",
        "references/.DS_Store",
        "references/x.pyc",
        "contract.json~",
        "file.swp",
        "Thumbs.db",
    ]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("excluded", encoding="utf-8")
    (skills / ".gitkeep").touch()
    build_archives(skills, licence, output)
    with zipfile.ZipFile(output / "example-skill.zip") as archive:
        assert archive.namelist() == [
            "LICENCE",
            "SKILL.md",
            "agents/openai.yaml",
            "references/contract.json",
        ]


@pytest.mark.parametrize(
    "frontmatter",
    [
        "No frontmatter\n",
        "---\nname: example-skill\n",
        "---\n- not-a-mapping\n---\n",
        "---\nname: example-skill\nname: example-skill\ndescription: Useful\n---\n",
        "---\nname: example-skill\ndescription: [invalid\n---\n",
        "---\nname: ../escape\ndescription: Useful\n---\n",
        "---\nname: other-skill\ndescription: Useful\n---\n",
        "---\nname: example-skill\ndescription: '   '\n---\n",
        "---\nname: example-skill\n---\n",
        "---\n!!python/object/apply:os.system ['echo unsafe']\n---\n",
    ],
)
def test_invalid_frontmatter_leaves_no_output(
    source_tree: tuple[Path, Path, Path], frontmatter: str
) -> None:
    """Fail before publishing archives for malformed or unsafe metadata."""
    skills, licence, output = source_tree
    root = _skill(skills)
    (root / "SKILL.md").write_text(frontmatter, encoding="utf-8")
    with pytest.raises(ValueError):
        build_archives(skills, licence, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "location",
    [
        "skill",
        "SKILL.md",
        "references",
        "references/link.json",
        "LICENCE",
        "repository-licence",
        "skills-root",
    ],
)
def test_symlink_inputs_are_rejected(source_tree: tuple[Path, Path, Path], location: str) -> None:
    """Prevent dereferencing files outside the declared skill contents."""
    skills, licence, output = source_tree
    root = _skill(skills)
    if location == "skill":
        link = skills / "linked-skill"
        link.symlink_to(root, target_is_directory=True)
    elif location == "skills-root":
        link = skills.parent / "linked-skills"
        link.symlink_to(skills, target_is_directory=True)
        skills = link
    elif location == "repository-licence":
        link = licence.parent / "linked-licence"
        link.symlink_to(licence)
        licence = link
    else:
        link = root / location
        if link.exists():
            target = link.with_name(link.name + "-original")
            link.rename(target)
        else:
            target = licence
        link.symlink_to(target, target_is_directory=target.is_dir())
    with pytest.raises(ValueError, match="symlink"):
        build_archives(skills, licence, output)
    assert not output.exists()


def test_nonempty_output_is_never_overwritten(source_tree: tuple[Path, Path, Path]) -> None:
    """Require a fresh output directory so stale assets cannot leak into a release."""
    skills, licence, output = source_tree
    _skill(skills)
    output.mkdir()
    stale = output / "old.zip"
    stale.write_bytes(b"existing output")
    with pytest.raises(ValueError, match="empty"):
        build_archives(skills, licence, output)
    assert stale.read_bytes() == b"existing output"
    assert list(output.iterdir()) == [stale]


def test_empty_output_is_supported(source_tree: tuple[Path, Path, Path]) -> None:
    """Allow callers to create the destination directory before packaging."""
    skills, licence, output = source_tree
    _skill(skills)
    output.mkdir()
    assert len(build_archives(skills, licence, output)) == 1


@pytest.mark.parametrize("nested", ["", "dist", "example-skill/dist"])
def test_output_cannot_be_inside_skills(source_tree: tuple[Path, Path, Path], nested: str) -> None:
    """Prevent recursive packaging and accidental mutation of skill sources."""
    skills, licence, _ = source_tree
    _skill(skills)
    with pytest.raises(ValueError, match="outside"):
        build_archives(skills, licence, skills / nested)


@pytest.mark.parametrize(
    "invalid_input",
    [
        "empty",
        "missing-skills",
        "missing-licence",
        "missing-skill-file",
        "root-file",
        "licence-directory",
        "backslash-path",
        "non-utf8",
    ],
)
def test_invalid_source_configuration(
    source_tree: tuple[Path, Path, Path], invalid_input: str
) -> None:
    """Reject incomplete source trees and ambiguous archive filenames."""
    skills, licence, output = source_tree
    if invalid_input != "empty":
        root = _skill(skills)
        if invalid_input == "missing-skills":
            skills = skills / "missing"
        elif invalid_input == "missing-licence":
            licence = licence.with_name("missing")
        elif invalid_input == "missing-skill-file":
            (root / "SKILL.md").unlink()
        elif invalid_input == "root-file":
            (skills / "unexpected.txt").touch()
        elif invalid_input == "licence-directory":
            (root / "LICENCE").mkdir()
        elif invalid_input == "backslash-path":
            (root / "..\\escape").touch()
        elif invalid_input == "non-utf8":
            (root / "SKILL.md").write_bytes(b"\xff")
    with pytest.raises(ValueError):
        build_archives(skills, licence, output)
    assert not output.exists()


def test_special_file_is_rejected_without_reading(source_tree: tuple[Path, Path, Path]) -> None:
    """Reject FIFOs without blocking a release waiting for stream contents."""
    skills, licence, output = source_tree
    root = _skill(skills)
    os.mkfifo(root / "named-pipe")
    with pytest.raises(ValueError, match="special files"):
        build_archives(skills, licence, output)
    assert not output.exists()


def test_build_failure_cleans_staging_and_keeps_output_empty(
    source_tree: tuple[Path, Path, Path],
) -> None:
    """Publish all archives together or leave no partially built release."""
    skills, licence, output = source_tree
    _skill(skills, "alpha")
    _skill(skills, "zeta")
    output.mkdir()
    original = Path.read_bytes

    def failing_read(path: Path) -> bytes:
        """Inject a late source read failure after the first archive is complete."""
        if "zeta" in path.parts and path.name == "SKILL.md":
            raise OSError("simulated unreadable input")
        return original(path)

    with patch.object(Path, "read_bytes", failing_read), pytest.raises(OSError, match="simulated"):
        build_archives(skills, licence, output)
    assert list(output.iterdir()) == []
    assert not list(output.parent.glob(".skill-archives-*"))


def test_real_skill_is_packaged_with_its_references(tmp_path: Path) -> None:
    """Exercise the repository's complete skill as an independent ZIP artifact."""
    repository = Path(__file__).resolve().parents[1]
    output = tmp_path / "release"
    artifacts = build_archives(repository / "skills", repository / "LICENCE", output)
    assert any(artifact.name == "author-mailwebhook-route-json" for artifact in artifacts)
    for artifact in artifacts:
        with zipfile.ZipFile(output / artifact.filename) as archive:
            assert "SKILL.md" in archive.namelist()
            assert "LICENCE" in archive.namelist()
            assert "agents/openai.yaml" in archive.namelist()
            assert any(name.startswith("references/") for name in archive.namelist())
            assert all(not name.startswith("skills/") for name in archive.namelist())

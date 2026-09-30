"""Create reproducible, self-contained skill archives from validated inputs."""

import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode

from release_tools.models import ArchiveArtifact, SkillMetadata


class _UniqueKeyLoader(yaml.SafeLoader):
    """Load ordinary YAML without silently accepting duplicate mapping keys."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        """Reject duplicate keys, including keys introduced by YAML merges."""
        if not isinstance(node, MappingNode):
            raise yaml.constructor.ConstructorError(
                None, None, "YAML mapping must contain key/value pairs", node.start_mark
            )
        self.flatten_mapping(node)
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in result:
                    raise ValueError(f"duplicate YAML frontmatter key: {key!r}")
                result[key] = self.construct_object(value_node, deep=deep)
            except TypeError as error:
                raise ValueError("YAML frontmatter keys must be scalar values") from error
        return result


def _require_kind(path: Path, *, directory: bool) -> os.stat_result:
    """Require a real directory or regular file without following symlinks."""
    try:
        details = path.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"required input does not exist: {path}") from error
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(details.st_mode):
        kind = "directory" if directory else "regular file"
        raise ValueError(f"input must be a {kind}, not a symlink or special file: {path}")
    return details


def _excluded(name: str) -> bool:
    """Omit hidden metadata, interpreter caches, and editor backup files."""
    return (
        name.startswith(".")
        or name in {"__pycache__", "Thumbs.db"}
        or name.endswith((".pyc", ".pyo", ".swp", ".swo", "~"))
    )


def _read_metadata(skill_dir: Path) -> SkillMetadata:
    """Validate skill frontmatter and its agreement with the folder name."""
    skill_file = skill_dir / "SKILL.md"
    _require_kind(skill_file, directory=False)
    try:
        lines = skill_file.read_text(encoding="utf-8").splitlines()
    except UnicodeError as error:
        raise ValueError(f"SKILL.md must be UTF-8: {skill_file}") from error
    if not lines or lines[0] != "---":
        raise ValueError(f"SKILL.md must begin with YAML frontmatter: {skill_file}")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(
            f"SKILL.md frontmatter must have a closing delimiter: {skill_file}"
        ) from error
    try:
        frontmatter = yaml.load("\n".join(lines[1:end]), Loader=_UniqueKeyLoader)
    except (yaml.YAMLError, ValueError) as error:
        raise ValueError(f"invalid YAML frontmatter in {skill_file}: {error}") from error
    if not isinstance(frontmatter, dict):
        raise ValueError(f"SKILL.md frontmatter must be a mapping: {skill_file}")
    metadata = SkillMetadata.model_validate(frontmatter)
    if metadata.name != skill_dir.name:
        raise ValueError(f"skill name must match its folder name: {skill_dir}")
    return metadata


def _collect_files(skill_dir: Path) -> dict[str, Path]:
    """Collect portable archive paths, rejecting symlinks and special files."""
    files: dict[str, Path] = {}
    pending = [skill_dir]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            details = path.lstat()
            if stat.S_ISLNK(details.st_mode):
                raise ValueError(f"skill input must not contain symlinks: {path}")
            if not stat.S_ISREG(details.st_mode) and not stat.S_ISDIR(details.st_mode):
                raise ValueError(f"skill input must not contain special files: {path}")
            if "\\" in path.name:
                raise ValueError(f"skill paths must not contain backslashes: {path}")
            if _excluded(path.name):
                continue
            if stat.S_ISDIR(details.st_mode):
                pending.append(path)
            else:
                files[path.relative_to(skill_dir).as_posix()] = path
    return files


def _write_archive(target: Path, files: dict[str, Path]) -> tuple[str, int]:
    """Write stable ZIP metadata and hash the resulting completed file bytes."""
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for archive_name, source in sorted(files.items()):
            details = _require_kind(source, directory=False)
            entry = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            # Preserve executability while removing ownership and machine-specific permissions.
            mode = 0o755 if details.st_mode & 0o111 else 0o644
            entry.external_attr = (stat.S_IFREG | mode) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, source.read_bytes(), compresslevel=9)
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return f"sha256:{digest}", target.stat().st_size


def build_archives(skills_dir: Path, licence_path: Path, output_dir: Path) -> list[ArchiveArtifact]:
    """Build one self-contained ZIP for every immediate skill directory.

    Args:
        skills_dir: Directory whose visible child directories are skills.
        licence_path: Repository licence copied unless a skill has its own LICENCE.
        output_dir: Missing or empty destination outside the skills tree.

    Returns:
        Validated metadata and digests for the completed archives, sorted by name.

    Raises:
        ValueError: Inputs, metadata, filenames, or output placement are invalid.
        OSError: Reading sources or atomically publishing the output fails.
    """
    for value in (skills_dir, licence_path, output_dir):
        if not isinstance(value, Path):
            raise ValueError("archive paths must be pathlib.Path instances")
    _require_kind(skills_dir, directory=True)
    _require_kind(licence_path, directory=False)
    resolved_skills = skills_dir.resolve()
    resolved_output = output_dir.resolve()
    if resolved_output.is_relative_to(resolved_skills):
        raise ValueError("output directory must be outside the skills tree")
    if output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    if output_dir.exists():
        _require_kind(output_dir, directory=True)
        if any(output_dir.iterdir()):
            raise ValueError("output directory must be empty; stale artifacts are not reusable")

    prepared: list[tuple[SkillMetadata, dict[str, Path]]] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        details = skill_dir.lstat()
        if stat.S_ISLNK(details.st_mode):
            raise ValueError(f"skill input must not contain symlinks: {skill_dir}")
        if not stat.S_ISREG(details.st_mode) and not stat.S_ISDIR(details.st_mode):
            raise ValueError(f"skill input must not contain special files: {skill_dir}")
        if _excluded(skill_dir.name):
            continue
        _require_kind(skill_dir, directory=True)
        metadata = _read_metadata(skill_dir)
        local_licence = skill_dir / "LICENCE"
        if local_licence.exists() or local_licence.is_symlink():
            _require_kind(local_licence, directory=False)
        files = _collect_files(skill_dir)
        files.setdefault("LICENCE", licence_path)
        prepared.append((metadata, files))
    if not prepared:
        raise ValueError("skills directory must contain at least one skill")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".skill-archives-", dir=output_dir.parent))
    artifacts: list[ArchiveArtifact] = []
    try:
        for metadata, files in prepared:
            filename = f"{metadata.name}.zip"
            digest, size = _write_archive(staging / filename, files)
            artifacts.append(
                ArchiveArtifact(
                    name=metadata.name,
                    description=metadata.description,
                    filename=filename,
                    digest=digest,
                    size=size,
                )
            )
        # A directory rename publishes all archives together and rejects a now-nonempty target.
        os.replace(staging, output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return artifacts

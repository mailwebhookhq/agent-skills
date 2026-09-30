"""Validate this repository's portable, skills-only plugin distribution contract.

This deliberately supports the metadata and PNG branding used by the project,
not every optional plugin capability. Unknown fields fail instead of silently
producing a package missing a declared integration or referenced asset.
"""

import io
import json
import unicodedata
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    UrlConstraints,
    field_validator,
)

from release_tools.models import Description, SemanticVersion, SkillName


def _single_line(value: str) -> str:
    """Require meaningful listing text without hidden control characters."""
    if not value.strip() or not value.isprintable():
        raise ValueError("listing text must be nonblank and fit on one printable line")
    return value


ListingText = Annotated[
    str, StringConstraints(strict=True, min_length=1), AfterValidator(_single_line)
]


def _public_url(value: HttpUrl) -> HttpUrl:
    """Keep embedded credentials out of publicly distributed listing metadata."""
    if value.username is not None or value.password is not None:
        raise ValueError("plugin metadata URLs must not contain credentials")
    return value


HttpsUrl = Annotated[
    HttpUrl,
    UrlConstraints(allowed_schemes=["https"], max_length=2048),
    AfterValidator(_public_url),
]


def _asset_path(value: str) -> str:
    """Limit bundled branding to unambiguous PNG paths beneath assets/."""
    if (
        not value.startswith("./assets/")
        or value != value.strip()
        or "\\" in value
        or ":" in value
        or not value.isprintable()
        or any(part in {"", ".", ".."} for part in value[2:].split("/"))
        or PurePosixPath(value).suffix.lower() != ".png"
    ):
        raise ValueError("plugin icons must be safe './assets/' relative PNG paths")
    return value


IconPath = Annotated[ListingText, AfterValidator(_asset_path)]


class _PluginModel(BaseModel):
    """Reject unsupported fields so packaging never silently drops content."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class PluginAuthor(_PluginModel):
    """Identify the maintainer in the portable plugin manifest."""

    name: Annotated[ListingText, Field(max_length=120)]
    url: HttpsUrl | None = None


class PluginInterface(_PluginModel):
    """Validate the listing metadata supported by this skills-only package."""

    display_name: Annotated[ListingText, Field(alias="displayName", max_length=30)]
    short_description: Annotated[ListingText, Field(alias="shortDescription", max_length=30)]
    long_description: Annotated[ListingText, Field(alias="longDescription", max_length=4000)]
    developer_name: Annotated[ListingText, Field(alias="developerName", max_length=80)]
    category: Literal[
        "Productivity",
        "Creativity",
        "Developer Tools",
        "Business & Operations",
        "Data & Analytics",
        "Communication",
        "Education & Research",
        "Security",
        "Finance",
        "Healthcare",
        "Travel",
        "Entertainment",
        "Other",
    ]
    capabilities: Annotated[
        list[Annotated[ListingText, Field(max_length=120)]], Field(max_length=20)
    ] = Field(default_factory=list)
    website_url: Annotated[
        HttpUrl,
        UrlConstraints(allowed_schemes=["https"], max_length=1024),
        AfterValidator(_public_url),
    ] = Field(alias="websiteURL")
    composer_icon: IconPath = Field(alias="composerIcon")
    logo: IconPath
    default_prompt: Annotated[
        list[Annotated[ListingText, Field(max_length=128)]], Field(max_length=3)
    ] = Field(default_factory=list, alias="defaultPrompt")

    @field_validator("default_prompt")
    @classmethod
    def prompts_are_unique(cls, value: list[str]) -> list[str]:
        """Reject duplicate starters and mentions forbidden in directory prompts."""
        normalized = [
            " ".join(unicodedata.normalize("NFKC", item).split()).casefold() for item in value
        ]
        if len(normalized) != len(set(normalized)):
            raise ValueError("default prompts must be unique after normalization")
        if any("@" in item for item in value):
            raise ValueError("default prompts must not contain @mentions")
        return value


class OpenAIExtension(_PluginModel):
    """Declare listing details without MCP servers, apps, or lifecycle hooks."""

    interface: PluginInterface


class PluginExtensions(_PluginModel):
    """Limit client extensions to the explicitly supported OpenAI metadata."""

    openai: OpenAIExtension = Field(alias="com.openai")


class PluginManifest(_PluginModel):
    """Validate the portable root manifest and project listing requirements."""

    schema_url: Literal["https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"] = Field(
        alias="$schema"
    )
    name: SkillName
    version: SemanticVersion
    description: Annotated[Description, AfterValidator(_single_line)]
    license: ListingText
    author: PluginAuthor
    homepage: HttpsUrl
    repository: HttpsUrl
    keywords: Annotated[list[ListingText], Field(min_length=1)]
    extensions: PluginExtensions


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys instead of accepting ambiguous manifests."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate plugin manifest key: {key}")
        result[key] = value
    return result


def parse_plugin_manifest(data: bytes, version: str | None = None) -> PluginManifest:
    """Validate UTF-8 manifest bytes and an optional release-version override.

    Args:
        data: The root plugin.json file contents.
        version: SemVer substituted only in the generated archive manifest.

    Returns:
        A validated manifest without modifying the source file.

    Raises:
        ValueError: JSON, metadata, or the supplied version is invalid.
    """
    if not isinstance(data, bytes):
        raise ValueError("plugin manifest must be supplied as bytes")
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("plugin.json must contain a UTF-8 JSON object") from error
    manifest = PluginManifest.model_validate(payload)
    if version is not None:
        manifest = PluginManifest.model_validate(
            {**manifest.model_dump(by_alias=True), "version": version}
        )
    return manifest


def validate_plugin_icon(data: bytes) -> None:
    """Require a complete square PNG meeting directory image size limits.

    Args:
        data: Exact icon bytes that will be written to the archive.

    Raises:
        ValueError: The PNG is malformed, oversized, animated, or not square.
    """
    if not isinstance(data, bytes) or not data or len(data) > 5 * 1024 * 1024:
        raise ValueError("plugin icons must be nonempty PNG files no larger than 5 MiB")
    try:
        with Image.open(io.BytesIO(data)) as icon:
            if icon.format != "PNG":
                raise ValueError("this package supports PNG icons only")
            width, height = icon.size
            if width != height or not 48 <= width <= 4096:
                raise ValueError("plugin PNG icons must be square and between 48 and 4096 pixels")
            if icon.is_animated:
                raise ValueError("this package supports static PNG icons only")
            icon.verify()
        # verify() checks the container; load() also checks its compressed pixel data.
        with Image.open(io.BytesIO(data)) as icon:
            icon.load()
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ValueError("plugin icon must be a valid, complete PNG image") from error


def validate_plugin_members(files: dict[str, int]) -> None:
    """Check plugin ZIP paths and expansion limits before writing any archive.

    Args:
        files: Archive member paths mapped to their uncompressed byte sizes.

    Raises:
        ValueError: Paths collide, are unsafe, or exceed submission size limits.
    """
    if not isinstance(files, dict):
        raise ValueError("plugin members must be a mapping of names to byte sizes")
    if len(files) > 5000:
        raise ValueError("plugin ZIP must contain at most 5,000 files")
    total_size = 0
    normalized_files: set[str] = set()
    normalized_directories: set[str] = set()
    for name, size in files.items():
        if not isinstance(name, str) or not isinstance(size, int) or isinstance(size, bool):
            raise ValueError("plugin members require string names and integer byte sizes")
        parts = name.split("/")
        normalized_parts = [unicodedata.normalize("NFKC", part).casefold() for part in parts]
        if (
            name.startswith("/")
            or "\\" in name
            or ":" in name
            or not name.isprintable()
            or any(part in {"", ".", ".."} or part != part.strip() for part in parts)
            or any(
                part in {"", ".", ".."}
                or any(character in part for character in "/\\:")
                or part != part.strip()
                for part in normalized_parts
            )
            or len(parts) > 20
        ):
            raise ValueError(f"unsafe or excessively deep plugin archive path: {name}")
        normalized = "/".join(normalized_parts)
        parents = ["/".join(normalized.split("/")[:index]) for index in range(1, len(parts))]
        if (
            normalized in normalized_files
            or normalized in normalized_directories
            or any(parent in normalized_files for parent in parents)
        ):
            raise ValueError(f"plugin archive paths collide after normalization: {name}")
        normalized_files.add(normalized)
        normalized_directories.update(parents)
        if size < 0 or size > 100 * 1024 * 1024:
            raise ValueError(f"plugin archive member must not exceed 100 MiB: {name}")
        total_size += size
    if total_size > 512 * 1024 * 1024:
        raise ValueError("plugin ZIP must not exceed 512 MiB uncompressed")

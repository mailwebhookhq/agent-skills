"""Validated contracts for skill archives and the public discovery index."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

SkillName = Annotated[
    str,
    StringConstraints(strict=True, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]
Description = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1024)]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^sha256:[0-9a-f]{64}$")]


class SkillMetadata(BaseModel):
    """Read the discovery fields while allowing other skill frontmatter keys."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: SkillName
    description: Description

    @field_validator("description")
    @classmethod
    def description_is_nonblank(cls, value: str) -> str:
        """Reject blank descriptions without changing their published text."""
        if not value.strip():
            raise ValueError("description must contain non-whitespace characters")
        return value


class ArchiveArtifact(SkillMetadata):
    """Describe the exact archive bytes prepared for a release upload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: Annotated[str, StringConstraints(strict=True)]
    digest: Digest
    size: Annotated[int, Field(strict=True, gt=0)]

    @model_validator(mode="after")
    def filename_matches_name(self) -> "ArchiveArtifact":
        """Ensure a manifest filename cannot escape its artifact directory."""
        if self.filename != f"{self.name}.zip":
            raise ValueError("filename must equal the skill name followed by '.zip'")
        return self


class DiscoveryEntry(SkillMetadata):
    """Identify one publicly downloadable, digest-pinned skill archive."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["archive"] = "archive"
    url: HttpUrl
    digest: Digest

    @field_validator("url")
    @classmethod
    def url_uses_https(cls, value: HttpUrl) -> HttpUrl:
        """Require encrypted public discovery downloads."""
        if value.scheme != "https":
            raise ValueError("archive URL must use HTTPS")
        return value


class DiscoveryIndex(BaseModel):
    """Serialize the supported discovery index with unique skill names."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_url: Literal["https://schemas.agentskills.io/discovery/0.2.0/schema.json"] = Field(
        default="https://schemas.agentskills.io/discovery/0.2.0/schema.json", alias="$schema"
    )
    skills: Annotated[list[DiscoveryEntry], Field(min_length=1)]

    @field_validator("skills")
    @classmethod
    def names_are_unique(cls, value: list[DiscoveryEntry]) -> list[DiscoveryEntry]:
        """Prevent ambiguous discovery entries for the same skill."""
        names = [entry.name for entry in value]
        if len(names) != len(set(names)):
            raise ValueError("discovery skill names must be unique")
        return value

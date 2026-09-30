"""Exercise the runtime contracts used by packaging and discovery publishing."""

from typing import Any

import pytest
from pydantic import ValidationError

from release_tools.models import ArchiveArtifact, DiscoveryEntry, DiscoveryIndex, SkillMetadata

VALID_DIGEST = "sha256:" + "a" * 64


def _artifact(**changes: Any) -> ArchiveArtifact:
    """Construct an artifact while varying one contract boundary at a time."""
    values: dict[str, Any] = {
        "name": "example-skill",
        "description": "Author an example.",
        "filename": "example-skill.zip",
        "digest": VALID_DIGEST,
        "size": 100,
    }
    values.update(changes)
    return ArchiveArtifact.model_validate(values)


@pytest.mark.parametrize(
    "name", ["", "-skill", "skill-", "two--parts", "UPPER", "../escape", "a/b", "a_b", "a" * 65, 42]
)
def test_invalid_skill_names(name: Any) -> None:
    """Reject noncanonical or unsafe archive identifiers."""
    with pytest.raises(ValidationError):
        SkillMetadata(name=name, description="Useful skill")


def test_metadata_preserves_description_and_allows_skill_fields() -> None:
    """Preserve authored description text without rejecting legal extra metadata."""
    metadata = SkillMetadata.model_validate(
        {"name": "a" * 64, "description": "  Keep my exact text.\n", "license": "MIT"}
    )
    assert metadata.description == "  Keep my exact text.\n"
    assert metadata.name == "a" * 64


@pytest.mark.parametrize("description", ["", " \n\t ", "a" * 1025, 8, None])
def test_invalid_descriptions(description: Any) -> None:
    """Require a bounded, meaningful string for discovery."""
    with pytest.raises(ValidationError):
        SkillMetadata(name="example", description=description)


@pytest.mark.parametrize(
    "changes",
    [
        {"filename": "../example-skill.zip"},
        {"filename": "example-skill\\file.zip"},
        {"filename": "other.zip"},
        {"filename": "example-skill.ZIP"},
        {"digest": "a" * 64},
        {"digest": "sha256:" + "A" * 64},
        {"digest": "sha256:" + "a" * 63},
        {"size": 0},
        {"size": -1},
        {"size": "100"},
        {"size": True},
        {"size": 1.5},
        {"unknown": "field"},
    ],
)
def test_artifact_rejects_invalid_contract(changes: dict[str, Any]) -> None:
    """Reject traversal, altered digests, ambiguous sizes, and unexpected fields."""
    with pytest.raises(ValidationError):
        _artifact(**changes)


def test_archive_artifact_is_frozen() -> None:
    """Keep validated upload metadata immutable after hashing."""
    artifact = _artifact()
    with pytest.raises(ValidationError):
        artifact.digest = "sha256:" + "b" * 64


def test_index_serializes_discovery_contract() -> None:
    """Emit the discovery schema alias and supported archive fields exactly."""
    entry = DiscoveryEntry(
        name="example-skill",
        description="Author an example.",
        url="https://github.com/example/skills/releases/download/v1/example-skill.zip",
        digest=VALID_DIGEST,
    )
    payload = DiscoveryIndex(skills=[entry]).model_dump(mode="json", by_alias=True)
    assert payload == {
        "$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
        "skills": [
            {
                "name": "example-skill",
                "type": "archive",
                "description": "Author an example.",
                "url": "https://github.com/example/skills/releases/download/v1/example-skill.zip",
                "digest": VALID_DIGEST,
            }
        ],
    }
    assert DiscoveryIndex.model_validate(payload).skills == [entry]


@pytest.mark.parametrize("url", ["http://example.com/skill.zip", "file:///skill.zip", "not-a-url"])
def test_discovery_rejects_non_https_urls(url: str) -> None:
    """Reject discovery download locations outside the HTTPS contract."""
    with pytest.raises(ValidationError):
        DiscoveryEntry(name="example", description="Useful skill", url=url, digest=VALID_DIGEST)


def test_discovery_requires_unique_nonempty_skills() -> None:
    """Ensure each public skill can resolve to a single archive."""
    entry = DiscoveryEntry(
        name="example",
        description="Useful skill",
        url="https://example.com/a.zip",
        digest=VALID_DIGEST,
    )
    with pytest.raises(ValidationError, match="at least 1"):
        DiscoveryIndex(skills=[])
    with pytest.raises(ValidationError, match="unique"):
        DiscoveryIndex(skills=[entry, entry])
    with pytest.raises(ValidationError):
        DiscoveryIndex.model_validate({"$schema": "https://example.com/schema", "skills": [entry]})

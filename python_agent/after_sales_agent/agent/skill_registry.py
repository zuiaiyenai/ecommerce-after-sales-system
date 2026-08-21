from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class AgentSkill:
    name: str
    description: str
    instructions: str
    version: str
    references: tuple[str, ...] = ()

    def context(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "instructions": self.instructions,
        }


@dataclass(frozen=True)
class _SkillIndexEntry:
    name: str
    description: str
    path: Path
    references: tuple[str, ...]


class AgentSkillRegistry:
    """Index skill metadata and progressively disclose bodies and references."""

    STAGE_SKILLS = {
        "evidence_collection": "evidence-request",
        "policy_explanation": "policy-consultation",
        "human_handoff": "human-handoff",
        "formal_review": "formal-review",
    }

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[1] / "skills"
        self._index = self._discover_metadata()
        self._skill_cache: dict[str, AgentSkill] = {}
        self._reference_cache: dict[tuple[str, str], str] = {}
        self._version_cache: dict[str, str] = {}
        self._lock = RLock()

    def select(self, stage: str) -> AgentSkill | None:
        """Load only the skill body mapped to the requested workflow stage."""
        name = self.STAGE_SKILLS.get(stage, "")
        return self.load(name) if name else None

    def load(self, name: str) -> AgentSkill | None:
        entry = self._index.get(name)
        if entry is None:
            return None
        with self._lock:
            cached = self._skill_cache.get(name)
            if cached is not None:
                return cached
            content = entry.path.read_text(encoding="utf-8")
            metadata, instructions = self._parse_document(content)
            if (
                str(metadata.get("name") or "").strip() != entry.name
                or str(metadata.get("description") or "").strip()
                != entry.description
                or not instructions
            ):
                raise RuntimeError(f"skill changed after indexing: {entry.path}")
            version = self._package_version(entry, main_content=content)
            skill = AgentSkill(
                name=entry.name,
                description=entry.description,
                instructions=instructions,
                version=version,
                references=entry.references,
            )
            self._skill_cache[name] = skill
            self._version_cache[name] = version
            return skill

    def load_reference(self, skill_or_stage: str, reference: str) -> str:
        """Load one declared reference after its parent skill has been selected."""
        name = self.STAGE_SKILLS.get(skill_or_stage, skill_or_stage)
        entry = self._index.get(name)
        if entry is None:
            raise KeyError(f"unknown skill: {skill_or_stage}")
        normalized = Path(reference).as_posix().lstrip("/")
        if normalized.startswith("../") or normalized not in entry.references:
            raise KeyError(f"unknown skill reference: {name}/{reference}")
        self.load(name)
        cache_key = (name, normalized)
        with self._lock:
            cached = self._reference_cache.get(cache_key)
            if cached is not None:
                return cached
            reference_root = (entry.path.parent / "references").resolve()
            reference_path = (reference_root / normalized).resolve()
            if reference_path.parent != reference_root:
                raise KeyError(f"invalid skill reference: {name}/{reference}")
            content = reference_path.read_text(encoding="utf-8").strip()
            if not content:
                raise RuntimeError(f"empty skill reference: {reference_path}")
            self._reference_cache[cache_key] = content
            return content

    def metadata(self) -> list[dict[str, Any]]:
        """Return the lightweight discovery catalog without loading skill bodies."""
        return [
            {
                "name": entry.name,
                "description": entry.description,
                "version": self._version(entry),
                "references": list(entry.references),
            }
            for entry in sorted(self._index.values(), key=lambda item: item.name)
        ]

    def cache_state(self) -> dict[str, tuple[str, ...]]:
        """Expose resource-level loading state for diagnostics and tests."""
        with self._lock:
            return {
                "skills": tuple(sorted(self._skill_cache)),
                "references": tuple(
                    sorted(f"{name}/{reference}" for name, reference in self._reference_cache)
                ),
            }

    def _discover_metadata(self) -> dict[str, _SkillIndexEntry]:
        skills: dict[str, _SkillIndexEntry] = {}
        if not self.root.exists():
            return skills
        for skill_file in sorted(self.root.glob("*/SKILL.md")):
            metadata = self._read_frontmatter(skill_file)
            name = str(metadata.get("name") or "").strip()
            description = str(metadata.get("description") or "").strip()
            if not name or not description:
                continue
            reference_root = skill_file.parent / "references"
            references = (
                tuple(
                    path.relative_to(reference_root).as_posix()
                    for path in sorted(reference_root.rglob("*.md"))
                )
                if reference_root.exists()
                else ()
            )
            skills[name] = _SkillIndexEntry(
                name=name,
                description=description,
                path=skill_file,
                references=references,
            )
        return skills

    def _version(self, entry: _SkillIndexEntry) -> str:
        cached = self._version_cache.get(entry.name)
        if cached is not None:
            return cached
        version = self._package_version(entry)
        self._version_cache[entry.name] = version
        return version

    @staticmethod
    def _package_version(
        entry: _SkillIndexEntry,
        *,
        main_content: str | None = None,
    ) -> str:
        """Hash the complete Skill package without retaining reference bodies."""
        digest = hashlib.sha256()
        digest.update(b"SKILL.md\0")
        if main_content is not None:
            digest.update(main_content.encode("utf-8"))
        else:
            with entry.path.open("rb") as handle:
                for block in iter(lambda: handle.read(64 * 1024), b""):
                    digest.update(block)
        reference_root = entry.path.parent / "references"
        for reference in entry.references:
            digest.update(b"\0")
            digest.update(reference.encode("utf-8"))
            digest.update(b"\0")
            with (reference_root / reference).open("rb") as handle:
                for block in iter(lambda: handle.read(64 * 1024), b""):
                    digest.update(block)
        return digest.hexdigest()[:12]

    @staticmethod
    def _read_frontmatter(path: Path) -> dict[str, str]:
        metadata: dict[str, str] = {}
        with path.open("r", encoding="utf-8") as handle:
            if handle.readline().strip() != "---":
                return metadata
            for raw_line in handle:
                line = raw_line.rstrip("\r\n")
                if line.strip() == "---":
                    return metadata
                key, separator, value = line.partition(":")
                if separator:
                    metadata[key.strip()] = value.strip()
        return {}

    @staticmethod
    def _parse_document(content: str) -> tuple[dict[str, str], str]:
        parts = content.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            return {}, ""
        metadata: dict[str, str] = {}
        for line in parts[1].splitlines():
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip()
        return metadata, parts[2].strip()

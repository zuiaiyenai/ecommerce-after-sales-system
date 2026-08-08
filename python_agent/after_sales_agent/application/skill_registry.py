from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentSkill:
    name: str
    description: str
    instructions: str
    version: str

    def context(self) -> dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "instructions": self.instructions,
        }


class AgentSkillRegistry:
    """Discovers versioned project skills and discloses only the active one."""

    STAGE_SKILLS = {
        "evidence_collection": "collect-after-sales-evidence",
        "policy_explanation": "explain-after-sales-policy",
        "human_handoff": "summarize-human-handoff",
    }

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[2] / "skills"
        self._skills = self._discover()

    def select(self, stage: str) -> AgentSkill | None:
        return self._skills.get(self.STAGE_SKILLS.get(stage, ""))

    def metadata(self) -> list[dict[str, str]]:
        return [
            {"name": skill.name, "description": skill.description, "version": skill.version}
            for skill in sorted(self._skills.values(), key=lambda item: item.name)
        ]

    def _discover(self) -> dict[str, AgentSkill]:
        skills: dict[str, AgentSkill] = {}
        if not self.root.exists():
            return skills
        for skill_file in sorted(self.root.glob("*/SKILL.md")):
            skill = self._parse(skill_file)
            if skill is not None:
                skills[skill.name] = skill
        return skills

    @staticmethod
    def _parse(path: Path) -> AgentSkill | None:
        content = path.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            return None
        metadata: dict[str, Any] = {}
        for line in parts[1].splitlines():
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip()
        name = str(metadata.get("name") or "").strip()
        description = str(metadata.get("description") or "").strip()
        instructions = parts[2].strip()
        if not name or not description or not instructions:
            return None
        version = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
        return AgentSkill(name=name, description=description, instructions=instructions, version=version)

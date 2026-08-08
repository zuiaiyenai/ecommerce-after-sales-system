from __future__ import annotations

import unittest

from after_sales_agent.application.skill_registry import AgentSkillRegistry


class AgentSkillRegistryTest(unittest.TestCase):
    def test_discovers_versioned_project_skills(self) -> None:
        registry = AgentSkillRegistry()
        metadata = {item["name"]: item for item in registry.metadata()}

        self.assertEqual(
            {
                "collect-after-sales-evidence",
                "explain-after-sales-policy",
                "summarize-human-handoff",
            },
            set(metadata),
        )
        self.assertTrue(all(len(item["version"]) == 12 for item in metadata.values()))

    def test_selects_only_one_skill_for_each_workflow_stage(self) -> None:
        registry = AgentSkillRegistry()

        evidence = registry.select("evidence_collection")
        policy = registry.select("policy_explanation")
        handoff = registry.select("human_handoff")

        self.assertEqual("collect-after-sales-evidence", evidence.name)
        self.assertEqual("explain-after-sales-policy", policy.name)
        self.assertEqual("summarize-human-handoff", handoff.name)
        self.assertIn("minimum reusable evidence", evidence.description)


if __name__ == "__main__":
    unittest.main()

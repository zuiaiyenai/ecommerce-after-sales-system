from __future__ import annotations

import unittest

from after_sales_agent.agent.skill_registry import AgentSkillRegistry


class AgentSkillRegistryTest(unittest.TestCase):
    def test_discovers_versioned_project_skills(self) -> None:
        registry = AgentSkillRegistry()
        self.assertEqual(
            {"skills": (), "references": ()},
            registry.cache_state(),
        )
        metadata = {item["name"]: item for item in registry.metadata()}

        self.assertEqual(
            {
                "evidence-request",
                "policy-consultation",
                "human-handoff",
                "formal-review",
            },
            set(metadata),
        )
        self.assertTrue(all(len(item["version"]) == 12 for item in metadata.values()))
        self.assertEqual(
            {"skills": (), "references": ()},
            registry.cache_state(),
        )

    def test_selects_only_one_skill_for_each_workflow_stage(self) -> None:
        registry = AgentSkillRegistry()

        evidence = registry.select("evidence_collection")
        policy = registry.select("policy_explanation")
        handoff = registry.select("human_handoff")
        formal_review = registry.select("formal_review")

        self.assertEqual("evidence-request", evidence.name)
        self.assertEqual("policy-consultation", policy.name)
        self.assertEqual("human-handoff", handoff.name)
        self.assertIn("最小通用凭证", evidence.description)
        self.assertEqual("formal-review", formal_review.name)
        self.assertIn("不能绕过 Gate", formal_review.instructions)
        self.assertEqual(
            {
                "skills": (
                    "evidence-request",
                    "formal-review",
                    "human-handoff",
                    "policy-consultation",
                ),
                "references": (),
            },
            registry.cache_state(),
        )

    def test_loads_only_requested_reference_and_rejects_traversal(self) -> None:
        registry = AgentSkillRegistry()

        policy_reference = registry.load_reference(
            "formal_review",
            "policy-workflow.md",
        )

        self.assertIn("严格过滤", policy_reference)
        self.assertEqual(
            {
                "skills": ("formal-review",),
                "references": ("formal-review/policy-workflow.md",),
            },
            registry.cache_state(),
        )
        with self.assertRaises(KeyError):
            registry.load_reference("formal_review", "../SKILL.md")


if __name__ == "__main__":
    unittest.main()

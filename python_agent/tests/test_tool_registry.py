from __future__ import annotations

import unittest

from after_sales_agent.application.tool_registry import AgentToolRegistry


class ToolRegistrySchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = AgentToolRegistry()
        self.specs = {spec["name"]: spec for spec in self.registry.tool_specs()}

    def test_all_executable_tools_have_strict_complete_object_schemas(self) -> None:
        self.assertEqual(set(self.registry.registry()), set(self.specs))
        for name, spec in self.specs.items():
            with self.subTest(tool=name):
                schema = spec["input_schema"]
                self.assertEqual("object", schema["type"])
                self.assertIs(False, schema["additionalProperties"])
                self.assertTrue(set(schema["required"]).issubset(schema["properties"]))

    def test_trusted_identity_fields_are_not_model_visible(self) -> None:
        trusted = {"user_id", "session_id", "order_id", "ticket_id", "review_request_id"}
        for spec in self.specs.values():
            schema = spec["input_schema"]
            self.assertTrue(trusted.isdisjoint(schema["properties"]))
            self.assertTrue(trusted.isdisjoint(schema["required"]))

    def test_representative_schema_types_are_explicit(self) -> None:
        search = self.specs["search_user_orders"]["input_schema"]["properties"]
        knowledge = self.specs["retrieve_knowledge"]["input_schema"]["properties"]
        review = self.specs["review_images"]["input_schema"]["properties"]
        submit = self.specs["submit_ai_review"]["input_schema"]["properties"]

        self.assertEqual("string", search["keyword"]["type"])
        self.assertEqual("array", search["status_filter"]["type"])
        self.assertEqual("number", knowledge["top_k"]["type"])
        self.assertEqual("array", review["attachments"]["type"])
        self.assertEqual("object", review["attachments"]["items"]["type"])
        self.assertEqual("boolean", submit["visual_uncertain"]["type"])
        self.assertEqual("number", submit["ai_review_confidence"]["type"])

    def test_final_reply_is_not_an_executable_registry_tool(self) -> None:
        self.assertNotIn("final_reply", self.registry.registry())
        self.assertNotIn("final_reply", self.specs)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import pathlib
import sys
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[3] / "tools" / "audit_knowledge_coverage.py"
spec = importlib.util.spec_from_file_location("knowledge_coverage_audit_for_test", SCRIPT_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules["knowledge_coverage_audit_for_test"] = module
spec.loader.exec_module(module)


class KnowledgeCoverageAuditTest(unittest.TestCase):
    def test_canonical_scene_matches_runtime_legacy_aliases(self) -> None:
        self.assertEqual("product_damage", module.canonical_scene("damage"))
        self.assertEqual("logistics_issue", module.canonical_scene("logistics_damage"))
        self.assertEqual("wrong_or_missing_items", module.canonical_scene("missing_item"))

    def test_prefers_direct_then_scene_then_category_then_global(self) -> None:
        report = module.build_report(
            [
                {"category": "服装", "scene": "product_damage", "documents": 1, "indexed_documents": 1, "chunks": 1},
                {"category": "general", "scene": "quality_issue", "documents": 1, "indexed_documents": 1, "chunks": 1},
                {"category": "服装", "scene": "general", "documents": 1, "indexed_documents": 1, "chunks": 1},
                {"category": "general", "scene": "general", "documents": 1, "indexed_documents": 1, "chunks": 1},
            ],
            ["服装", "数码"],
            ["product_damage", "quality_issue", "logistics_issue"],
        )
        levels = {(item["category"], item["scene"]): item["level"] for item in report["coverage"]}
        self.assertEqual("direct", levels[("服装", "product_damage")])
        self.assertEqual("scene_default", levels[("数码", "quality_issue")])
        self.assertEqual("category_default", levels[("服装", "logistics_issue")])
        self.assertEqual("global_default", levels[("数码", "logistics_issue")])

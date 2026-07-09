from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
import unittest


BASE_DIR = pathlib.Path(__file__).resolve().parents[1] / "after_sales_agent"


def load_backend_module():
    package = types.ModuleType("after_sales_agent")
    package.__path__ = [str(BASE_DIR)]
    sys.modules.setdefault("after_sales_agent", package)

    agents_package = types.ModuleType("after_sales_agent.agents")
    agents_package.__path__ = [str(BASE_DIR / "agents")]
    sys.modules.setdefault("after_sales_agent.agents", agents_package)

    llm_client_module = types.ModuleType("after_sales_agent.llm_client")

    class LLMError(Exception):
        pass

    class OpenAICompatibleConfig:
        @staticmethod
        def from_env():
            return OpenAICompatibleConfig()

    class OpenAICompatibleClient:
        def __init__(self, *_args, **_kwargs):
            pass

    llm_client_module.LLMError = LLMError
    llm_client_module.OpenAICompatibleClient = OpenAICompatibleClient
    llm_client_module.OpenAICompatibleConfig = OpenAICompatibleConfig
    sys.modules["after_sales_agent.llm_client"] = llm_client_module

    models_module = types.ModuleType("after_sales_agent.models")

    class AfterSalesRequest:
        pass

    class ConversationMessage:
        pass

    class Order:
        pass

    models_module.AfterSalesRequest = AfterSalesRequest
    models_module.ConversationMessage = ConversationMessage
    models_module.Order = Order
    sys.modules["after_sales_agent.models"] = models_module

    spec = importlib.util.spec_from_file_location(
        "after_sales_agent.agents.qwen_emotion_backend",
        BASE_DIR / "agents" / "qwen_emotion_backend.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["after_sales_agent.agents.qwen_emotion_backend"] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_backend_module()
QwenEmotionBackend = MODULE.QwenEmotionBackend
QwenEmotionResult = MODULE.QwenEmotionResult


class QwenEmotionBackendTest(unittest.TestCase):
    def test_self_check_no_longer_ties_calm_to_handoff_priority(self) -> None:
        result = QwenEmotionResult(
            label="calm",
            emotion_score=0.25,
            confidence=0.90,
            need_human_priority=True,
            reason="user requested human support",
            raw={},
        )

        self.assertFalse(QwenEmotionBackend._needs_self_check(result))

    def test_score_ranges_are_more_conservative(self) -> None:
        self.assertEqual((0.10, 0.35), QwenEmotionBackend.SCORE_RANGES["calm"])
        self.assertEqual((0.30, 0.55), QwenEmotionBackend.SCORE_RANGES["anxious"])
        self.assertEqual((0.50, 0.75), QwenEmotionBackend.SCORE_RANGES["dissatisfied"])

    def test_normalize_result_keeps_in_range_values(self) -> None:
        result = QwenEmotionResult(
            label="calm",
            emotion_score=0.52,
            confidence=0.98,
            need_human_priority=False,
            reason="normal follow-up question",
            raw={},
        )

        normalized = QwenEmotionBackend._normalize_result(result)
        self.assertEqual("dissatisfied", normalized.label)
        self.assertEqual(0.52, normalized.emotion_score)
        self.assertEqual(0.98, normalized.confidence)

    def test_normalize_result_keeps_handoff_priority_independent(self) -> None:
        result = QwenEmotionResult(
            label="dissatisfied",
            emotion_score=0.98,
            confidence=0.65,
            need_human_priority=True,
            reason="user asked to escalate handling",
            raw={},
        )

        normalized = QwenEmotionBackend._normalize_result(result)
        self.assertEqual("angry", normalized.label)
        self.assertEqual(0.98, normalized.emotion_score)
        self.assertTrue(normalized.need_human_priority)

    def test_needs_self_check_when_score_exceeds_one(self) -> None:
        result = QwenEmotionResult(
            label="anxious",
            emotion_score=1.20,
            confidence=0.90,
            need_human_priority=False,
            reason="score is out of valid range",
            raw={},
        )

        self.assertTrue(QwenEmotionBackend._needs_self_check(result))

    def test_needs_self_check_when_confidence_exceeds_one(self) -> None:
        result = QwenEmotionResult(
            label="calm",
            emotion_score=0.20,
            confidence=1.20,
            need_human_priority=False,
            reason="confidence is invalid",
            raw={},
        )

        self.assertTrue(QwenEmotionBackend._needs_self_check(result))

    def test_normalize_result_keeps_in_range_score_unchanged(self) -> None:
        result = QwenEmotionResult(
            label="anxious",
            emotion_score=0.44,
            confidence=0.88,
            need_human_priority=False,
            reason="already valid anxious result",
            raw={},
        )

        normalized = QwenEmotionBackend._normalize_result(result)
        self.assertEqual("anxious", normalized.label)
        self.assertEqual(0.44, normalized.emotion_score)
        self.assertEqual(0.88, normalized.confidence)

    def test_normalize_result_clamps_negative_score_to_zero(self) -> None:
        result = QwenEmotionResult(
            label="satisfied",
            emotion_score=-0.40,
            confidence=0.93,
            need_human_priority=False,
            reason="negative score should be clamped",
            raw={},
        )

        normalized = QwenEmotionBackend._normalize_result(result)
        self.assertEqual("satisfied", normalized.label)
        self.assertEqual(0.0, normalized.emotion_score)
        self.assertEqual(0.93, normalized.confidence)

    def test_normalize_result_clamps_score_above_one(self) -> None:
        result = QwenEmotionResult(
            label="angry",
            emotion_score=1.40,
            confidence=0.92,
            need_human_priority=True,
            reason="score above one should be clamped",
            raw={},
        )

        normalized = QwenEmotionBackend._normalize_result(result)
        self.assertEqual("angry", normalized.label)
        self.assertEqual(1.0, normalized.emotion_score)
        self.assertEqual(0.92, normalized.confidence)
        self.assertTrue(normalized.need_human_priority)

    def test_label_from_score_maps_satisfied(self) -> None:
        self.assertEqual("satisfied", QwenEmotionBackend._label_from_score(0.05))

    def test_label_from_score_maps_calm(self) -> None:
        self.assertEqual("calm", QwenEmotionBackend._label_from_score(0.20))

    def test_label_from_score_maps_anxious(self) -> None:
        self.assertEqual("anxious", QwenEmotionBackend._label_from_score(0.40))

    def test_label_from_score_maps_dissatisfied(self) -> None:
        self.assertEqual("dissatisfied", QwenEmotionBackend._label_from_score(0.60))

    def test_label_from_score_maps_angry(self) -> None:
        self.assertEqual("angry", QwenEmotionBackend._label_from_score(0.88))

    def test_parse_required_bool_supports_yes_and_no(self) -> None:
        self.assertTrue(QwenEmotionBackend._parse_required_bool("yes", "need_human_priority"))
        self.assertFalse(QwenEmotionBackend._parse_required_bool("no", "need_human_priority"))

    def test_parse_required_bool_rejects_invalid_text(self) -> None:
        with self.assertRaises(Exception):
            QwenEmotionBackend._parse_required_bool("maybe", "need_human_priority")


if __name__ == "__main__":
    unittest.main()

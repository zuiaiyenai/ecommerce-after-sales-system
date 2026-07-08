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
            reason="用户要求人工处理",
            raw={},
        )

        self.assertFalse(QwenEmotionBackend._needs_self_check(result))

    def test_score_ranges_are_more_conservative(self) -> None:
        self.assertEqual((0.10, 0.35), QwenEmotionBackend.SCORE_RANGES["calm"])
        self.assertEqual((0.30, 0.55), QwenEmotionBackend.SCORE_RANGES["anxious"])
        self.assertEqual((0.50, 0.75), QwenEmotionBackend.SCORE_RANGES["dissatisfied"])

    def test_normalize_result_clamps_score_into_label_range(self) -> None:
        result = QwenEmotionResult(
            label="calm",
            emotion_score=0.52,
            confidence=0.98,
            need_human_priority=False,
            reason="用户普通追问",
            raw={},
        )

        normalized = QwenEmotionBackend._normalize_result(result)
        self.assertEqual("calm", normalized.label)
        self.assertEqual(0.30, normalized.emotion_score)
        self.assertEqual(0.78, normalized.confidence)

    def test_normalize_result_keeps_handoff_priority_independent(self) -> None:
        result = QwenEmotionResult(
            label="dissatisfied",
            emotion_score=0.98,
            confidence=0.65,
            need_human_priority=True,
            reason="用户要求升级处理",
            raw={},
        )

        normalized = QwenEmotionBackend._normalize_result(result)
        self.assertEqual("dissatisfied", normalized.label)
        self.assertEqual(0.70, normalized.emotion_score)
        self.assertTrue(normalized.need_human_priority)

    def test_apply_message_priors_downgrades_handoff_request(self) -> None:
        result = QwenEmotionResult(
            label="dissatisfied",
            emotion_score=0.74,
            confidence=0.91,
            need_human_priority=True,
            reason="模型原始结果偏高",
            raw={},
        )

        normalized = QwenEmotionBackend._apply_message_priors("转人工", result)
        self.assertEqual("anxious", normalized.label)
        self.assertEqual(0.42, normalized.emotion_score)

    def test_apply_message_priors_recognizes_positive_ack(self) -> None:
        result = QwenEmotionResult(
            label="calm",
            emotion_score=0.30,
            confidence=0.78,
            need_human_priority=False,
            reason="普通确认",
            raw={},
        )

        normalized = QwenEmotionBackend._apply_message_priors("好的谢谢", result)
        self.assertEqual("satisfied", normalized.label)
        self.assertEqual(0.12, normalized.emotion_score)


if __name__ == "__main__":
    unittest.main()

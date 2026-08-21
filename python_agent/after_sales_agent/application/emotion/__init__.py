"""Emotion analysis application service.

Composes the LLM/Qwen emotion backends behind a single ``EmotionAgent`` entry
point used by the chat flow (``application/chat/emotion_context.py``).
"""
from __future__ import annotations

from .emotion_service import EmotionAgent, EmotionBackendResult
from .llm_emotion_classifier import LLMEmotionBackend, LLMEmotionResult
from .qwen_emotion_backend import QwenEmotionBackend, QwenEmotionResult

__all__ = [
    "EmotionAgent",
    "EmotionBackendResult",
    "LLMEmotionBackend",
    "LLMEmotionResult",
    "QwenEmotionBackend",
    "QwenEmotionResult",
]

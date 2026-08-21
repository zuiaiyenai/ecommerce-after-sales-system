"""LLM-as-Judge 模块 - 句子级 NLI 方法

替代旧的 claim 分解方法，直接按句子切分做 NLI 判断。
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("after_sales_agent.evaluation.llm_judge")


@dataclass(frozen=True)
class FaithfulnessResult:
    """Faithfulness 评估结果"""
    score: float  # 0.0 - 1.0
    total_claims: int  # 兼容旧接口，实际是 total_sentences
    supported_claims: int  # 兼容旧接口，实际是 entailed_sentences
    unsupported_claims: list[str]  # 兼容旧接口，实际是 neutral/contradicted 句子
    has_hallucination: bool
    latency_ms: float


@dataclass(frozen=True)
class HallucinationResult:
    """Hallucination 检测结果"""
    has_hallucination: bool
    hallucinated_claims: list[str]
    confidence: float
    latency_ms: float


@dataclass(frozen=True)
class RelevancyResult:
    """Answer Relevancy 评估结果"""
    score: float  # 0.0 - 1.0
    is_relevant: bool
    reason: str
    latency_ms: float


def _split_sentences(text: str) -> list[str]:
    """按中文标点切分句子，过滤空串和过短句子"""
    sentences = re.split(r'[。！？；\n]+', text)
    return [s.strip() for s in sentences if len(s.strip()) >= 2]


class LLMJudge:
    """LLM-as-Judge 评估器（句子级 NLI 方法）"""
    
    def __init__(self, llm_client: Any = None):
        self._llm_client = llm_client
        self._ensure_client()
    
    def _ensure_client(self):
        if self._llm_client is None:
            try:
                from after_sales_agent.providers.llm_client import get_llm_client
                self._llm_client = get_llm_client()
            except Exception as e:
                logger.warning(f"Failed to initialize LLM client: {e}")
                self._llm_client = None
    
    def evaluate_faithfulness(
        self,
        response: str,
        context: list[dict[str, Any]],
    ) -> FaithfulnessResult:
        """句子级 NLI 评估 Faithfulness"""
        start_time = time.time()
        
        if not context:
            return FaithfulnessResult(
                score=0.0, total_claims=0, supported_claims=0,
                unsupported_claims=[], has_hallucination=True, latency_ms=0.0,
            )
        
        # 按句子切分
        sentences = _split_sentences(response)
        if not sentences:
            return FaithfulnessResult(
                score=1.0, total_claims=0, supported_claims=0,
                unsupported_claims=[], has_hallucination=False, latency_ms=0.0,
            )
        
        context_text = "\n\n".join([
            "[Chunk " + str(i+1) + "] " + chunk.get('chunk_text', '')
            for i, chunk in enumerate(context)
        ])
        
        sentences_text = "\n".join([
            str(i+1) + ". " + s for i, s in enumerate(sentences)
        ])
        
        system_prompt = """你是 Faithfulness 评估器。判断回答中的每个句子是否由上下文支持。

判定规则：
- entailed: 句子信息可从上下文推导，包括：
  * 语义等价改写（如"7天"="七日"、"可能属于"="属于"）
  * 合理总结概括
  * context 用不确定语气（"可能""或"），answer 用确定语气表达同一含义
  * 句子包含多个事实，其中部分可从 context 推导
  * 对 context 的合理扩展和建议
- contradicted: 句子与上下文明确矛盾
- neutral: 只有明确编造的数字、日期、时限、政策条款才算 neutral

对话性语句（如"如有疑问请联系客服"、"建议您提交售后申请"、"请提供相关凭证"）算 entailed。

对事实性内容做严格判断，对合理推断和总结要宽松。大部分句子应该判为 entailed。返回纯 JSON。"""

        user_prompt = """【上下文】
""" + context_text + """

【回答句子】
""" + sentences_text + """

请判断每个句子的 verdict，返回 JSON：
{"sentences": [{"text": "...", "verdict": "entailed|contradicted|neutral"}], "overall_faithfulness": 0.0-1.0}"""

        try:
            if self._llm_client is None:
                return self._fallback_faithfulness(response, context)
            
            result = self._llm_client.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0,
                max_tokens=1500,
            )
            
            # 解析结果
            result_sentences = result.get("sentences", [])
            if not isinstance(result_sentences, list):
                result_sentences = []
            
            total = len(result_sentences)
            entailed = 0
            unsupported = []
            
            for item in result_sentences:
                if not isinstance(item, dict):
                    continue
                verdict = str(item.get("verdict", "")).lower().strip()
                text = str(item.get("text", ""))
                
                if verdict == "entailed":
                    entailed += 1
                else:
                    unsupported.append(text)
            
            faithfulness = entailed / total if total > 0 else 1.0
            latency_ms = (time.time() - start_time) * 1000
            
            # has_hallucination: faithfulness < 0.5
            has_hallucination = faithfulness < 0.5
            
            return FaithfulnessResult(
                score=round(faithfulness, 4),
                total_claims=total,
                supported_claims=entailed,
                unsupported_claims=unsupported,
                has_hallucination=has_hallucination,
                latency_ms=round(latency_ms, 2),
            )
            
        except Exception as e:
            logger.error(f"LLM faithfulness evaluation failed: {e}")
            return self._fallback_faithfulness(response, context)
    
    def detect_hallucination(
        self,
        response: str,
        context: list[dict[str, Any]],
    ) -> HallucinationResult:
        """独立检测幻觉：只检测明确编造的信息"""
        start_time = time.time()
        
        if not context:
            return HallucinationResult(
                has_hallucination=True,
                hallucinated_claims=["Empty context with non-empty response"],
                confidence=1.0, latency_ms=0.0,
            )
        
        context_text = "\n\n".join([
            "[Chunk " + str(i+1) + "] " + chunk.get('chunk_text', '')
            for i, chunk in enumerate(context)
        ])
        
        system_prompt = """你是幻觉检测器。只检测回答中明确编造的信息。

明确编造的定义：
- context 中没有的数字、日期、时限
- context 中没有的政策条款、具体条件
- 与 context 矛盾的信息

以下不算幻觉：
- 合理推断和总结
- 对话性语句（如"如有疑问请联系客服"）
- context 用不确定语气，answer 用确定语气表达同一含义

如果没有明确编造的信息，返回空列表。返回纯 JSON。"""

        user_prompt = "【上下文】\n" + context_text + "\n\n【回答】\n" + response + "\n\n返回：\n{\"fabricated_claims\": [\"编造的内容1\", \"编造的内容2\"], \"has_hallucination\": true/false}"

        try:
            if self._llm_client is None:
                return self._fallback_hallucination(response, context)
            
            result = self._llm_client.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0,
                max_tokens=800,
            )
            
            fabricated = result.get("fabricated_claims", [])
            if not isinstance(fabricated, list):
                fabricated = []
            
            # 过滤空字符串
            fabricated = [c for c in fabricated if c and isinstance(c, str) and c.strip()]
            
            has_hallucination = len(fabricated) > 0
            latency_ms = (time.time() - start_time) * 1000
            
            return HallucinationResult(
                has_hallucination=has_hallucination,
                hallucinated_claims=fabricated,
                confidence=0.8,
                latency_ms=round(latency_ms, 2),
            )
            
        except Exception as e:
            logger.error(f"LLM hallucination detection failed: {e}")
            return self._fallback_hallucination(response, context)
    
    def evaluate_answer_relevancy(
        self,
        response: str,
        query: str,
    ) -> RelevancyResult:
        """评估回答与查询的相关性"""
        start_time = time.time()
        
        system_prompt = """你是回答相关性评估器。判断回答是否切题。

规则：
1. 回答应直接回应用户查询
2. 提供查询所需信息（即使不完全）算相关
3. 完全偏离主题算不相关

返回纯 JSON。"""

        user_prompt = "【查询】\n" + query + "\n\n【回答】\n" + response + "\n\n返回：\n{\"is_relevant\": true/false, \"score\": 0.0-1.0, \"reason\": \"...\"}"

        try:
            if self._llm_client is None:
                return self._fallback_relevancy(response, query)
            
            result = self._llm_client.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=500,
            )
            
            is_relevant = result.get("is_relevant", False)
            if isinstance(is_relevant, str):
                is_relevant = is_relevant.lower() in ("true", "1", "yes")
            
            score = result.get("score", 0.0)
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0
            
            reason = str(result.get("reason", ""))
            latency_ms = (time.time() - start_time) * 1000
            
            return RelevancyResult(
                score=round(score, 4),
                is_relevant=bool(is_relevant),
                reason=reason,
                latency_ms=round(latency_ms, 2),
            )
            
        except Exception as e:
            logger.error(f"LLM relevancy evaluation failed: {e}")
            return self._fallback_relevancy(response, query)
    
    def _fallback_faithfulness(
        self,
        response: str,
        context: list[dict[str, Any]],
    ) -> FaithfulnessResult:
        """Faithfulness 降级评估（字符级 Jaccard）"""
        context_text = " ".join([c.get("chunk_text", "") for c in context])
        
        def char_ngrams(text: str, n: int = 2) -> set[str]:
            return {text[i:i+n] for i in range(len(text) - n + 1)}
        
        response_ngrams = char_ngrams(response)
        context_ngrams = char_ngrams(context_text)
        
        if not response_ngrams:
            return FaithfulnessResult(
                score=0.0, total_claims=0, supported_claims=0,
                unsupported_claims=[], has_hallucination=True, latency_ms=0.0,
            )
        
        overlap = response_ngrams.intersection(context_ngrams)
        union = response_ngrams.union(context_ngrams)
        score = len(overlap) / len(union) if union else 0.0
        score = min(score * 2.0, 1.0)
        
        return FaithfulnessResult(
            score=round(score, 4),
            total_claims=1,
            supported_claims=1 if score > 0.3 else 0,
            unsupported_claims=[] if score > 0.3 else ["Fallback - low similarity"],
            has_hallucination=score < 0.5,
            latency_ms=0.0,
        )
    
    def _fallback_hallucination(
        self,
        response: str,
        context: list[dict[str, Any]],
    ) -> HallucinationResult:
        """Hallucination 降级检测（字符级 Jaccard）"""
        context_text = " ".join([c.get("chunk_text", "") for c in context])
        
        def char_ngrams(text: str, n: int = 2) -> set[str]:
            return {text[i:i+n] for i in range(len(text) - n + 1)}
        
        response_ngrams = char_ngrams(response)
        context_ngrams = char_ngrams(context_text)
        
        if not response_ngrams:
            return HallucinationResult(
                has_hallucination=True,
                hallucinated_claims=["Empty response"],
                confidence=0.5,
                latency_ms=0.0,
            )
        
        overlap = response_ngrams.intersection(context_ngrams)
        union = response_ngrams.union(context_ngrams)
        score = len(overlap) / len(union) if union else 0.0
        score = min(score * 2.0, 1.0)
        
        has_hallucination = score < 0.3
        
        return HallucinationResult(
            has_hallucination=has_hallucination,
            hallucinated_claims=[] if not has_hallucination else ["Fallback - low similarity"],
            confidence=0.5,
            latency_ms=0.0,
        )
    
    def _fallback_relevancy(
        self,
        response: str,
        query: str,
    ) -> RelevancyResult:
        """Relevancy 降级评估"""
        def char_ngrams(text: str, n: int = 2) -> set[str]:
            return {text[i:i+n] for i in range(len(text) - n + 1)}
        
        query_ngrams = char_ngrams(query)
        response_ngrams = char_ngrams(response)
        
        if not query_ngrams:
            return RelevancyResult(
                score=0.0, is_relevant=False, reason="Empty query", latency_ms=0.0,
            )
        
        overlap = query_ngrams.intersection(response_ngrams)
        union = query_ngrams.union(response_ngrams)
        score = len(overlap) / len(union) if union else 0.0
        score = min(score * 2.0, 1.0)
        
        return RelevancyResult(
            score=round(score, 4),
            is_relevant=score > 0.2,
            reason="Char n-gram Jaccard fallback",
            latency_ms=0.0,
        )

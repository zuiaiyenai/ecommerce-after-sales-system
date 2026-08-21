"""RAG 全链路测试框架 - 涵盖四层评估维度

测试维度：
1. 数据集质量验证
2. Retrieval 检索层评估 (Recall@K, NDCG, MRR)
3. Context 上下文层评估 (Context Recall/Precision)
4. Generation 生成层评估 (Faithfulness) - 支持 LLM-as-judge
5. End-to-End 业务层评估 (Accuracy/F1)
6. 性能监控 (响应时间/延迟)
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

logger = logging.getLogger("after_sales_agent.evaluation.rag_full_chain_test")

from after_sales_agent.evaluation.rag_metrics import (
    Case,
    _mean,
    _ndcg,
    _percentile,
    _recall,
    _rounded,
    hit_rate,
    reciprocal_rank,
    load_cases,
)

try:
    from after_sales_agent.evaluation.llm_judge import LLMJudge
except ImportError:
    LLMJudge = None


@dataclass(frozen=True)
class DatasetQualityReport:
    """数据集质量报告"""
    total_cases: int
    positive_cases: int
    negative_cases: int
    cases_with_filters: int
    avg_relevant_chunks: float
    max_relevant_chunks: int
    min_relevant_chunks: int
    unique_queries: int
    duplicate_queries: int
    split_distribution: dict[str, int]
    category_distribution: dict[str, int]
    annotation_method_distribution: dict[str, int]
    quality_score: float


@dataclass(frozen=True)
class RetrievalMetrics:
    """检索层指标"""
    recall_at_1: float | None
    recall_at_3: float | None
    recall_at_5: float | None
    recall_at_10: float | None
    ndcg_at_5: float | None
    ndcg_at_10: float | None
    mrr_at_10: float | None
    hit_rate_at_5: float | None
    hit_rate_at_10: float | None
    filter_violation_rate: float
    filter_violation_count: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    latency_avg_ms: float | None


@dataclass(frozen=True)
class ContextMetrics:
    """上下文层指标"""
    context_recall: float | None
    context_precision: float | None
    context_f1: float | None
    avg_context_length: float
    context_utilization: float


@dataclass(frozen=True)
class GenerationMetrics:
    """生成层指标"""
    faithfulness: float | None
    answer_relevancy: float | None
    hallucination_rate: float | None
    avg_response_length: float
    response_format_compliance: float
    # 新增指标
    true_hallucination_rate: float | None = None
    false_refusal_rate: float | None = None
    correct_abstention_rate: float | None = None
    refusal_rate: float | None = None


@dataclass(frozen=True)
class BusinessMetrics:
    """业务层指标"""
    accuracy: float | None
    macro_f1: float | None
    auto_approve_precision: float | None
    safety_violation_count: int
    evidence_f1: float | None


@dataclass(frozen=True)
class PerformanceMetrics:
    """性能指标"""
    total_latency_ms: float | None
    retrieval_latency_ms: float | None
    rerank_latency_ms: float | None
    generation_latency_ms: float | None
    throughput_qps: float | None
    timeout_count: int
    error_count: int


@dataclass(frozen=True)
class FullChainTestReport:
    """全链路测试报告"""
    dataset_quality: DatasetQualityReport
    retrieval_metrics: RetrievalMetrics
    context_metrics: ContextMetrics
    generation_metrics: GenerationMetrics
    business_metrics: BusinessMetrics
    performance_metrics: PerformanceMetrics
    test_duration_seconds: float
    test_timestamp: str


class RAGFullChainTester:
    """RAG 全链路测试器"""
    
    def __init__(
        self,
        retriever: Callable[..., dict[str, Any]],
        generator: Callable[[str, list[dict[str, Any]]], str] | None = None,
        business评判器: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        llm_judge: Any | None = None,
        use_llm_judge: bool = True,
    ):
        """
        Args:
            retriever: 检索器函数，接收 query 和 filters，返回检索结果
            generator: 生成器函数，接收 query 和 context，返回回答
            business评判器: 业务评判函数，接收 query 和 response，返回评判结果
            llm_judge: LLMJudge 实例，用于 Faithfulness/Hallucination/Relevancy 评估
            use_llm_judge: 是否使用 LLM-as-judge（默认 True）
        """
        self.retriever = retriever
        self.generator = generator
        self.business_judge = business评判器
        self.use_llm_judge = use_llm_judge
        
        # 初始化 LLM Judge
        if llm_judge is not None:
            self.llm_judge = llm_judge
        elif use_llm_judge and LLMJudge is not None:
            try:
                self.llm_judge = LLMJudge()
            except Exception as e:
                logger.warning(f"Failed to initialize LLMJudge: {e}")
                self.llm_judge = None
        else:
            self.llm_judge = None
    
    def run_full_test(
        self,
        dataset_path: str | Path,
        k_values: tuple[int, ...] = (1, 3, 5, 10),
    ) -> FullChainTestReport:
        """运行全链路测试"""
        start_time = time.time()
        
        # 加载数据集
        cases = load_cases(dataset_path)
        
        # 1. 数据集质量验证
        dataset_quality = self._evaluate_dataset_quality(cases)
        
        # 2. 执行检索并收集结果
        retrieval_results = self._execute_retrieval(cases)
        
        # 3. 检索层评估
        retrieval_metrics = self._evaluate_retrieval(cases, retrieval_results, k_values)
        
        # 4. 上下文层评估
        context_metrics = self._evaluate_context(cases, retrieval_results)
        
        # 5. 生成层评估
        generation_metrics = self._evaluate_generation(cases, retrieval_results)
        
        # 6. 业务层评估
        business_metrics = self._evaluate_business(cases, retrieval_results)
        
        # 7. 性能评估
        performance_metrics = self._evaluate_performance(retrieval_results)
        
        test_duration = time.time() - start_time
        
        return FullChainTestReport(
            dataset_quality=dataset_quality,
            retrieval_metrics=retrieval_metrics,
            context_metrics=context_metrics,
            generation_metrics=generation_metrics,
            business_metrics=business_metrics,
            performance_metrics=performance_metrics,
            test_duration_seconds=round(test_duration, 2),
            test_timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
    
    def _evaluate_dataset_quality(self, cases: Sequence[Case]) -> DatasetQualityReport:
        """评估数据集质量"""
        total = len(cases)
        positive = [c for c in cases if c.relevant_chunk_ids and not c.expect_no_answer]
        negative = [c for c in cases if c.expect_no_answer]
        
        cases_with_filters = sum(
            1 for c in cases
            if c.filters.get("merchant_code")
            or c.filters.get("product_category")
            or c.filters.get("scene")
        )
        
        relevant_counts = [len(c.relevant_chunk_ids) for c in positive]
        avg_relevant = sum(relevant_counts) / len(relevant_counts) if relevant_counts else 0
        max_relevant = max(relevant_counts) if relevant_counts else 0
        min_relevant = min(relevant_counts) if relevant_counts else 0
        
        queries = [c.query for c in cases]
        unique_queries = len(set(queries))
        duplicate_queries = total - unique_queries
        
        split_dist = {}
        for c in cases:
            split_dist[c.split] = split_dist.get(c.split, 0) + 1
        
        category_dist = {}
        for c in cases:
            category_dist[c.category] = category_dist.get(c.category, 0) + 1
        
        annotation_dist = {}
        for c in cases:
            annotation_dist[c.annotation_method] = annotation_dist.get(c.annotation_method, 0) + 1
        
        # 计算质量分数 (基于多个因素)
        quality_score = self._calculate_dataset_quality_score(
            total, unique_queries, avg_relevant, len(positive), len(negative)
        )
        
        return DatasetQualityReport(
            total_cases=total,
            positive_cases=len(positive),
            negative_cases=len(negative),
            cases_with_filters=cases_with_filters,
            avg_relevant_chunks=round(avg_relevant, 2),
            max_relevant_chunks=max_relevant,
            min_relevant_chunks=min_relevant,
            unique_queries=unique_queries,
            duplicate_queries=duplicate_queries,
            split_distribution=split_dist,
            category_distribution=category_dist,
            annotation_method_distribution=annotation_dist,
            quality_score=round(quality_score, 4),
        )
    
    def _calculate_dataset_quality_score(
        self,
        total: int,
        unique_queries: int,
        avg_relevant: float,
        positive_count: int,
        negative_count: int,
    ) -> float:
        """计算数据集质量分数"""
        # 基础分数
        score = 0.0
        
        # 1. 数据集大小 (最多 30 分)
        size_score = min(total / 100, 1.0) * 30
        score += size_score
        
        # 2. 查询多样性 (最多 25 分)
        diversity_score = (unique_queries / total if total > 0 else 0) * 25
        score += diversity_score
        
        # 3. 正负样本平衡 (最多 20 分)
        if positive_count > 0 and negative_count > 0:
            balance_ratio = min(positive_count, negative_count) / max(positive_count, negative_count)
            balance_score = balance_ratio * 20
        else:
            balance_score = 0
        score += balance_score
        
        # 4. 相关文档数量合理性 (最多 15 分)
        if avg_relevant > 0:
            relevance_score = min(avg_relevant / 3, 1.0) * 15
        else:
            relevance_score = 0
        score += relevance_score
        
        # 5. 标注质量 (最多 10 分)
        # 基于标注方法的可靠性
        annotation_score = 10  # 默认满分，实际应基于标注方法分布
        score += annotation_score
        
        return min(score, 100.0)
    
    def _execute_retrieval(
        self,
        cases: Sequence[Case],
    ) -> dict[str, dict[str, Any]]:
        """执行检索并收集结果"""
        results = {}
        
        for case in cases:
            start_time = time.time()
            
            try:
                # 调用检索器
                retrieval_result = self.retriever(
                    query=case.query,
                    **case.filters,
                )
                
                latency_ms = (time.time() - start_time) * 1000
                
                # 提取检索结果
                hits = retrieval_result.get("hits", [])
                no_answer = retrieval_result.get("no_answer", False)
                
                results[case.case_id] = {
                    "hits": hits,
                    "no_answer": no_answer,
                    "latency_ms": latency_ms,
                    "trace": retrieval_result.get("trace", {}),
                    "error": None,
                }
                
            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                results[case.case_id] = {
                    "hits": [],
                    "no_answer": True,
                    "latency_ms": latency_ms,
                    "trace": {},
                    "error": str(e),
                }
        
        return results
    
    def _evaluate_retrieval(
        self,
        cases: Sequence[Case],
        results: dict[str, dict[str, Any]],
        k_values: tuple[int, ...],
    ) -> RetrievalMetrics:
        """评估检索层"""
        positive_cases = [c for c in cases if c.relevant_chunk_ids and not c.expect_no_answer]
        
        # 提取排名和延迟
        rankings = {}
        latencies = []
        
        for case in positive_cases:
            case_result = results.get(case.case_id, {})
            hits = case_result.get("hits", [])
            
            # 提取 chunk_id 排名
            ranked_ids = []
            seen = set()
            for hit in hits:
                chunk_id = str(hit.get("chunk_id", ""))
                if chunk_id and chunk_id not in seen:
                    seen.add(chunk_id)
                    ranked_ids.append(chunk_id)
            
            rankings[case.case_id] = ranked_ids
            
            # 收集延迟
            latency = case_result.get("latency_ms")
            if isinstance(latency, (int, float)) and math.isfinite(latency):
                latencies.append(latency)
        
        # 计算 Recall@K
        recall_values = {}
        for k in k_values:
            recalls = [
                _recall(case.relevant_chunk_ids, rankings.get(case.case_id, []), k)
                for case in positive_cases
            ]
            recall_values[k] = _mean(recalls)
        
        # 计算 NDCG@K
        ndcg_values = {}
        for k in [5, 10]:
            ndcg_list = [
                _ndcg(case.relevant_chunk_ids, rankings.get(case.case_id, []), k)
                for case in positive_cases
            ]
            ndcg_values[k] = _mean(ndcg_list)
        
        # 计算 MRR@10
        mrr_values = [
            reciprocal_rank(case.relevant_chunk_ids, rankings.get(case.case_id, []), 10)
            for case in positive_cases
        ]
        mrr = _mean(mrr_values)
        
        # 计算 Hit Rate@K
        hit_values = {}
        for k in [5, 10]:
            hits_list = [
                hit_rate(case.relevant_chunk_ids, rankings.get(case.case_id, []), k)
                for case in positive_cases
            ]
            hit_values[k] = _mean(hits_list)
        
        # 计算过滤违规率
        violations = 0
        checked_hits = 0
        for case in cases:
            case_result = results.get(case.case_id, {})
            hits = case_result.get("hits", [])
            
            has_filter_labels = bool(
                case.forbidden_merchant_codes or case.forbidden_policy_versions
            )
            if has_filter_labels:
                checked_hits += len(hits)
                for hit in hits:
                    merchant = hit.get("merchant_code") or hit.get("metadata", {}).get("merchant_code")
                    version = hit.get("policy_version") or hit.get("metadata", {}).get("policy_version")
                    if merchant in case.forbidden_merchant_codes or version in case.forbidden_policy_versions:
                        violations += 1
        
        # 计算延迟统计
        latency_p50 = _percentile(latencies, 0.50) if latencies else None
        latency_p95 = _percentile(latencies, 0.95) if latencies else None
        latency_avg = _mean(latencies) if latencies else None
        
        return RetrievalMetrics(
            recall_at_1=_rounded(recall_values.get(1)),
            recall_at_3=_rounded(recall_values.get(3)),
            recall_at_5=_rounded(recall_values.get(5)),
            recall_at_10=_rounded(recall_values.get(10)),
            ndcg_at_5=_rounded(ndcg_values.get(5)),
            ndcg_at_10=_rounded(ndcg_values.get(10)),
            mrr_at_10=_rounded(mrr),
            hit_rate_at_5=_rounded(hit_values.get(5)),
            hit_rate_at_10=_rounded(hit_values.get(10)),
            filter_violation_rate=_rounded(violations / checked_hits) if checked_hits else 0.0,
            filter_violation_count=violations,
            latency_p50_ms=_rounded(latency_p50),
            latency_p95_ms=_rounded(latency_p95),
            latency_avg_ms=_rounded(latency_avg),
        )
    
    def _evaluate_context(
        self,
        cases: Sequence[Case],
        results: dict[str, dict[str, Any]],
    ) -> ContextMetrics:
        """评估上下文层"""
        positive_cases = [c for c in cases if c.relevant_chunk_ids and not c.expect_no_answer]
        
        context_recalls = []
        context_precisions = []
        context_lengths = []
        
        for case in positive_cases:
            case_result = results.get(case.case_id, {})
            hits = case_result.get("hits", [])
            
            # 提取检索到的 chunk_id
            retrieved_ids = set()
            for hit in hits:
                chunk_id = str(hit.get("chunk_id", ""))
                if chunk_id:
                    retrieved_ids.add(chunk_id)
            
            # 计算 Context Recall
            if case.relevant_chunk_ids:
                recall = len(retrieved_ids.intersection(case.relevant_chunk_ids)) / len(case.relevant_chunk_ids)
                context_recalls.append(recall)
            
            # 计算 Context Precision
            if retrieved_ids:
                precision = len(retrieved_ids.intersection(case.relevant_chunk_ids)) / len(retrieved_ids)
                context_precisions.append(precision)
            
            # 计算上下文长度（兼容 snippet 和 chunk_text 字段）
            total_length = sum(len(hit.get("snippet") or hit.get("chunk_text", "")) for hit in hits)
            context_lengths.append(total_length)
        
        # 计算平均指标
        avg_recall = _mean(context_recalls) if context_recalls else None
        avg_precision = _mean(context_precisions) if context_precisions else None
        
        # 计算 F1
        if avg_recall is not None and avg_precision is not None:
            if avg_recall + avg_precision > 0:
                context_f1 = 2 * avg_precision * avg_recall / (avg_precision + avg_recall)
            else:
                context_f1 = 0.0
        else:
            context_f1 = None
        
        avg_length = _mean(context_lengths) if context_lengths else 0
        
        # 计算上下文利用率 (有相关文档的案例比例)
        cases_with_relevant = sum(
            1 for case in positive_cases
            if results.get(case.case_id, {}).get("hits")
        )
        utilization = cases_with_relevant / len(positive_cases) if positive_cases else 0
        
        return ContextMetrics(
            context_recall=_rounded(avg_recall),
            context_precision=_rounded(avg_precision),
            context_f1=_rounded(context_f1),
            avg_context_length=round(avg_length, 2),
            context_utilization=round(utilization, 4),
        )
    
    def _evaluate_generation(
        self,
        cases: Sequence[Case],
        results: dict[str, dict[str, Any]],
    ) -> GenerationMetrics:
        """评估生成层"""
        if not self.generator:
            return GenerationMetrics(
                faithfulness=None,
                answer_relevancy=None,
                hallucination_rate=None,
                avg_response_length=0,
                response_format_compliance=0,
            )
        
        faithfulness_scores = []
        relevancy_scores = []
        hallucination_flags = []
        response_lengths = []
        format_compliance = []
        faithfulness_details = []
        
        # 新增指标
        refusal_flags = []
        true_hallucination_flags = []
        
        def is_refusal(response: str) -> bool:
            """判断回答是否是拒答（精确匹配）"""
            import re
            
            # 短回答（< 30 字符）的严格判断
            if len(response) < 30:
                short_patterns = [
                    "无法回答", "不能回答", "不知道", "没有相关信息",
                    "无法提供", "无法确定", "无法判断",
                    "根据现有知识库无法", "知识库中没有",
                ]
                return any(p in response for p in short_patterns)
            
            # 长回答的正则匹配：需要"抱歉"后面跟"无法"才算拒答
            if re.search(r"抱歉.*无法", response):
                return True
            
            # 其他明确拒答模式
            refusal_patterns = [
                "无法回答", "不能回答", "没有相关信息",
                "根据现有知识库无法", "知识库中没有",
            ]
            return any(p in response for p in refusal_patterns)
        
        for case in cases:
            case_result = results.get(case.case_id, {})
            hits = case_result.get("hits", [])
            
            # 构建上下文（兼容 snippet 和 chunk_text 字段）
            context = []
            for hit in hits:
                context.append({
                    "chunk_id": hit.get("chunk_id"),
                    "chunk_text": hit.get("snippet") or hit.get("chunk_text", ""),
                    "score": hit.get("score", 0),
                })
            
            # 调用生成器
            try:
                response = self.generator(case.query, context)
                
                # 判断是否拒答
                refusal = is_refusal(response)
                refusal_flags.append(refusal)
                
                # 评估 Faithfulness
                if self.llm_judge and self.use_llm_judge:
                    faith_result = self.llm_judge.evaluate_faithfulness(response, context)
                    faithfulness_scores.append(faith_result.score)
                    hallucination_flags.append(faith_result.has_hallucination)
                    faithfulness_details.append({
                        "case_id": case.case_id,
                        "score": faith_result.score,
                        "total_claims": faith_result.total_claims,
                        "supported_claims": faith_result.supported_claims,
                        "unsupported_claims": faith_result.unsupported_claims,
                        "latency_ms": faith_result.latency_ms,
                    })
                    
                    # 独立检测真实幻觉
                    hall_result = self.llm_judge.detect_hallucination(response, context)
                    true_hallucination_flags.append(hall_result.has_hallucination)
                    
                    relev_result = self.llm_judge.evaluate_answer_relevancy(response, case.query)
                    relevancy_scores.append(relev_result.score)
                else:
                    faithfulness = self._evaluate_faithfulness(response, context)
                    faithfulness_scores.append(faithfulness)
                    
                    relevancy = self._evaluate_answer_relevancy(response, case.query)
                    relevancy_scores.append(relevancy)
                    
                    hallucination = self._detect_hallucination(response, context)
                    hallucination_flags.append(hallucination)
                    true_hallucination_flags.append(hallucination)
                
                response_lengths.append(len(response))
                
                compliance = self._check_format_compliance(response)
                format_compliance.append(compliance)
                
            except Exception as e:
                logger.error(f"Generation evaluation failed for case {case.case_id}: {e}")
                faithfulness_scores.append(0.0)
                relevancy_scores.append(0.0)
                hallucination_flags.append(True)
                true_hallucination_flags.append(True)
                refusal_flags.append(True)
                response_lengths.append(0)
                format_compliance.append(0)
        
        self._generation_details = faithfulness_details
        
        # 计算新指标
        total = len(refusal_flags) if refusal_flags else 1
        refusal_rate = sum(refusal_flags) / total if refusal_flags else 0
        
        # 计算 False Refusal / Correct Abstention / False Answer
        false_refusal_count = 0
        correct_abstention_count = 0
        false_answer_count = 0
        positive_count = 0
        negative_count = 0
        
        for i, case in enumerate(cases):
            if i >= len(refusal_flags):
                break
            refusal = refusal_flags[i]
            
            if case.expect_no_answer:
                negative_count += 1
                if refusal:
                    correct_abstention_count += 1
                else:
                    false_answer_count += 1
            else:
                positive_count += 1
                if refusal:
                    false_refusal_count += 1
        
        false_refusal_rate = false_refusal_count / positive_count if positive_count > 0 else 0
        correct_abstention_rate = correct_abstention_count / negative_count if negative_count > 0 else 0
        false_answer_rate = false_answer_count / negative_count if negative_count > 0 else 0
        
        return GenerationMetrics(
            faithfulness=_rounded(_mean(faithfulness_scores)) if faithfulness_scores else None,
            answer_relevancy=_rounded(_mean(relevancy_scores)) if relevancy_scores else None,
            hallucination_rate=_rounded(sum(hallucination_flags) / len(hallucination_flags)) if hallucination_flags else None,
            avg_response_length=round(_mean(response_lengths) if response_lengths else 0, 2),
            response_format_compliance=round(_mean(format_compliance) if format_compliance else 0, 4),
            # 新增指标
            true_hallucination_rate=_rounded(sum(true_hallucination_flags) / len(true_hallucination_flags)) if true_hallucination_flags else None,
            false_refusal_rate=_rounded(false_refusal_rate),
            correct_abstention_rate=_rounded(correct_abstention_rate),
            refusal_rate=_rounded(refusal_rate),
        )
    
    def _evaluate_faithfulness(
        self,
        response: str,
        context: list[dict[str, Any]],
    ) -> float:
        """评估 Faithfulness (LLM 是否脱离知识库乱说)"""
        if not context:
            return 0.0
        
        # 简单实现：检查回答中的关键信息是否来自上下文
        # 实际项目中应使用 LLM 进行更准确的评估
        
        # 提取上下文中的关键词
        context_text = " ".join([c.get("chunk_text", "") for c in context])
        
        # 计算回答中来自上下文的词汇比例
        response_words = set(response.split())
        context_words = set(context_text.split())
        
        if not response_words:
            return 0.0
        
        overlap = response_words.intersection(context_words)
        faithfulness = len(overlap) / len(response_words)
        
        return min(faithfulness * 1.2, 1.0)  # 稍微放宽，因为分词可能不准确
    
    def _evaluate_answer_relevancy(
        self,
        response: str,
        query: str,
    ) -> float:
        """评估回答相关性"""
        if not query or not response:
            return 0.0
        
        # 简单实现：基于查询和回答的词汇重叠
        query_words = set(query.split())
        response_words = set(response.split())
        
        if not query_words:
            return 0.0
        
        overlap = query_words.intersection(response_words)
        relevancy = len(overlap) / len(query_words)
        
        return min(relevancy * 1.5, 1.0)  # 放宽，因为回答可能使用同义词
    
    def _detect_hallucination(
        self,
        response: str,
        context: list[dict[str, Any]],
    ) -> bool:
        """检测幻觉"""
        if not context:
            return True
        
        # 简单实现：如果回答中包含上下文中没有的数字或专有名词，则可能幻觉
        context_text = " ".join([c.get("chunk_text", "") for c in context])
        
        # 检查数字
        import re
        response_numbers = set(re.findall(r'\d+', response))
        context_numbers = set(re.findall(r'\d+', context_text))
        
        # 如果回答中的数字在上下文中找不到，可能幻觉
        if response_numbers and not response_numbers.issubset(context_numbers):
            return True
        
        return False
    
    def _check_format_compliance(self, response: str) -> float:
        """检查格式合规性"""
        # 简单实现：检查回答是否为空或过短
        if not response or len(response) < 10:
            return 0.0
        
        # 检查是否包含必要的售后信息
        required_keywords = ["退货", "换货", "退款", "售后", "凭证", "申请"]
        has_required = any(keyword in response for keyword in required_keywords)
        
        return 1.0 if has_required else 0.5
    
    def _evaluate_business(
        self,
        cases: Sequence[Case],
        results: dict[str, dict[str, Any]],
    ) -> BusinessMetrics:
        """评估业务层"""
        if not self.business_judge:
            return BusinessMetrics(
                accuracy=None,
                macro_f1=None,
                auto_approve_precision=None,
                safety_violation_count=0,
                evidence_f1=None,
            )
        
        correct_predictions = 0
        total_predictions = 0
        safety_violations = 0
        evidence_scores = []
        
        for case in cases:
            case_result = results.get(case.case_id, {})
            hits = case_result.get("hits", [])
            
            # 调用业务评判器
            try:
                judgment = self.business_judge(case.query, {
                    "hits": hits,
                    "no_answer": case_result.get("no_answer", False),
                    "filters": case.filters,
                })
                
                # 评估准确性
                expected_no_answer = case.expect_no_answer
                predicted_no_answer = judgment.get("no_answer", False)
                
                if expected_no_answer == predicted_no_answer:
                    correct_predictions += 1
                total_predictions += 1
                
                # 检查安全违规
                if judgment.get("safety_violation", False):
                    safety_violations += 1
                
                # 评估凭证 F1
                if "evidence_f1" in judgment:
                    evidence_scores.append(judgment["evidence_f1"])
                    
            except Exception:
                total_predictions += 1
        
        accuracy = correct_predictions / total_predictions if total_predictions > 0 else None
        evidence_f1 = _mean(evidence_scores) if evidence_scores else None
        
        return BusinessMetrics(
            accuracy=_rounded(accuracy),
            macro_f1=_rounded(accuracy),  # 简化：假设二分类
            auto_approve_precision=None,
            safety_violation_count=safety_violations,
            evidence_f1=_rounded(evidence_f1),
        )
    
    def _evaluate_performance(
        self,
        results: dict[str, dict[str, Any]],
    ) -> PerformanceMetrics:
        """评估性能"""
        latencies = []
        errors = 0
        
        for case_result in results.values():
            latency = case_result.get("latency_ms")
            if isinstance(latency, (int, float)) and math.isfinite(latency):
                latencies.append(latency)
            
            if case_result.get("error"):
                errors += 1
        
        total_latency = sum(latencies) if latencies else None
        avg_latency = _mean(latencies) if latencies else None
        
        # 计算 QPS
        if latencies:
            total_time_seconds = sum(latencies) / 1000
            throughput = len(latencies) / total_time_seconds if total_time_seconds > 0 else None
        else:
            throughput = None
        
        return PerformanceMetrics(
            total_latency_ms=_rounded(total_latency),
            retrieval_latency_ms=_rounded(avg_latency),
            rerank_latency_ms=None,
            generation_latency_ms=None,
            throughput_qps=_rounded(throughput),
            timeout_count=0,
            error_count=errors,
        )


def generate_markdown_report(report: FullChainTestReport) -> str:
    """生成 Markdown 格式的测试报告"""
    lines = []
    
    lines.append("# RAG 全链路测试报告")
    lines.append("")
    lines.append(f"**测试时间**: {report.test_timestamp}")
    lines.append(f"**测试耗时**: {report.test_duration_seconds} 秒")
    lines.append("")
    
    # 数据集质量
    lines.append("## 1. 数据集质量")
    lines.append("")
    dq = report.dataset_quality
    lines.append(f"- 总案例数: {dq.total_cases}")
    lines.append(f"- 正向案例: {dq.positive_cases}")
    lines.append(f"- 负向案例: {dq.negative_cases}")
    lines.append(f"- 有过滤条件的案例: {dq.cases_with_filters}")
    lines.append(f"- 平均相关文档数: {dq.avg_relevant_chunks}")
    lines.append(f"- 唯一查询数: {dq.unique_queries}")
    lines.append(f"- 重复查询数: {dq.duplicate_queries}")
    lines.append(f"- **质量分数: {dq.quality_score}/100**")
    lines.append("")
    
    # 检索层
    lines.append("## 2. Retrieval 检索层")
    lines.append("")
    rm = report.retrieval_metrics
    lines.append("### 召回率 (Recall@K)")
    lines.append(f"- Recall@1: {rm.recall_at_1}")
    lines.append(f"- Recall@3: {rm.recall_at_3}")
    lines.append(f"- Recall@5: {rm.recall_at_5}")
    lines.append(f"- Recall@10: {rm.recall_at_10}")
    lines.append("")
    lines.append("### 排序质量")
    lines.append(f"- NDCG@5: {rm.ndcg_at_5}")
    lines.append(f"- NDCG@10: {rm.ndcg_at_10}")
    lines.append(f"- MRR@10: {rm.mrr_at_10}")
    lines.append("")
    lines.append("### 命中率")
    lines.append(f"- Hit Rate@5: {rm.hit_rate_at_5}")
    lines.append(f"- Hit Rate@10: {rm.hit_rate_at_10}")
    lines.append("")
    lines.append("### 过滤安全")
    lines.append(f"- 过滤违规率: {rm.filter_violation_rate}")
    lines.append(f"- 违规次数: {rm.filter_violation_count}")
    lines.append("")
    lines.append("### 延迟")
    lines.append(f"- P50: {rm.latency_p50_ms} ms")
    lines.append(f"- P95: {rm.latency_p95_ms} ms")
    lines.append(f"- 平均: {rm.latency_avg_ms} ms")
    lines.append("")
    
    # 上下文层
    lines.append("## 3. Context 上下文层")
    lines.append("")
    cm = report.context_metrics
    lines.append(f"- Context Recall: {cm.context_recall}")
    lines.append(f"- Context Precision: {cm.context_precision}")
    lines.append(f"- Context F1: {cm.context_f1}")
    lines.append(f"- 平均上下文长度: {cm.avg_context_length} 字符")
    lines.append(f"- 上下文利用率: {cm.context_utilization}")
    lines.append("")
    
    # 生成层
    lines.append("## 4. Generation 生成层")
    lines.append("")
    gm = report.generation_metrics
    if gm.faithfulness is not None:
        lines.append(f"- Faithfulness: {gm.faithfulness}")
        lines.append(f"- Answer Relevancy: {gm.answer_relevancy}")
        lines.append(f"- 幻觉率 (NLI Non-Entailment): {gm.hallucination_rate}")
        lines.append(f"- 平均响应长度: {gm.avg_response_length} 字符")
        lines.append(f"- 格式合规率: {gm.response_format_compliance}")
        # 新增指标
        if gm.true_hallucination_rate is not None:
            lines.append(f"- **真实幻觉率**: {gm.true_hallucination_rate}")
        if gm.refusal_rate is not None:
            lines.append(f"- 拒答率: {gm.refusal_rate}")
        if gm.false_refusal_rate is not None:
            lines.append(f"- **错误拒答率**: {gm.false_refusal_rate}")
        if gm.correct_abstention_rate is not None:
            lines.append(f"- 正确拒答率: {gm.correct_abstention_rate}")
    else:
        lines.append("- *未配置生成器，跳过生成层评估*")
    lines.append("")
    
    # 业务层
    lines.append("## 5. End-to-End 业务层")
    lines.append("")
    bm = report.business_metrics
    if bm.accuracy is not None:
        lines.append(f"- Accuracy: {bm.accuracy}")
        lines.append(f"- Macro F1: {bm.macro_f1}")
        lines.append(f"- 凭证 F1: {bm.evidence_f1}")
        lines.append(f"- 安全违规次数: {bm.safety_violation_count}")
    else:
        lines.append("- *未配置业务评判器，跳过业务层评估*")
    lines.append("")
    
    # 性能
    lines.append("## 6. 性能监控")
    lines.append("")
    pm = report.performance_metrics
    lines.append(f"- 总延迟: {pm.total_latency_ms} ms")
    lines.append(f"- 平均检索延迟: {pm.retrieval_latency_ms} ms")
    lines.append(f"- 吞吐量: {pm.throughput_qps} QPS")
    lines.append(f"- 错误次数: {pm.error_count}")
    lines.append("")
    
    # 总结
    lines.append("## 总结")
    lines.append("")
    
    # 计算综合分数
    scores = []
    if dq.quality_score:
        scores.append(dq.quality_score)
    if rm.recall_at_5:
        scores.append(float(rm.recall_at_5) * 100)
    if cm.context_f1:
        scores.append(float(cm.context_f1) * 100)
    if gm.faithfulness:
        scores.append(float(gm.faithfulness) * 100)
    if bm.accuracy:
        scores.append(float(bm.accuracy) * 100)
    
    overall_score = sum(scores) / len(scores) if scores else 0
    
    lines.append(f"**综合分数: {overall_score:.1f}/100**")
    lines.append("")
    
    # 改进建议
    lines.append("### 改进建议")
    lines.append("")
    if rm.recall_at_5 and float(rm.recall_at_5) < 0.8:
        lines.append("- 检索召回率偏低，建议优化 embedding 模型或增加检索候选数")
    if cm.context_precision and float(cm.context_precision) < 0.7:
        lines.append("- 上下文精度不足，建议优化 reranker 阈值或过滤策略")
    if gm.hallucination_rate and float(gm.hallucination_rate) > 0.1:
        lines.append("- 幻觉率偏高，建议加强 faithfulness 约束或优化 prompt")
    if pm.error_count > 0:
        lines.append(f"- 存在 {pm.error_count} 次错误，建议检查异常处理")
    
    return "\n".join(lines)

"""RAG 全链路完整测试运行脚本 - 支持消融测试和 LLM-as-judge"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from after_sales_agent.retrieval.pgvector_retriever import PgVectorKnowledgeRetriever, PgVectorConfig
from after_sales_agent.evaluation.rag_metrics import load_cases, evaluate
from evaluation.rag_full_chain_test import (
    RAGFullChainTester,
    generate_markdown_report,
)

# 检索模式定义
RETRIEVAL_MODES = {
    "dense": "仅 pgvector 向量召回",
    "keyword": "仅 pg_trgm/FTS 关键词召回",
    "rrf": "Dense + Keyword → RRF 融合",
    "rerank": "RRF → qwen3-rerank 精排",
}

# 模块级单例 retriever，避免每次测试都创建新实例
_retriever_instance: PgVectorKnowledgeRetriever | None = None


def get_retriever() -> PgVectorKnowledgeRetriever:
    """获取检索器单例"""
    global _retriever_instance
    if _retriever_instance is None:
        config = PgVectorConfig.from_env()
        _retriever_instance = PgVectorKnowledgeRetriever(config)
    return _retriever_instance


def test_retriever_with_mode(mode: str):
    """创建指定模式的检索器函数（使用单例）"""
    retriever = get_retriever()
    
    def retriever_func(query: str, **filters) -> dict:
        return retriever.retrieve(query=query, retrieval_mode=mode, **filters)
    
    return retriever_func


def run_ablation_test(dataset_path: str, modes: list[str] | None = None):
    """运行消融测试
    
    Args:
        dataset_path: 数据集路径
        modes: 要测试的检索模式列表，默认为所有模式
    """
    if modes is None:
        modes = list(RETRIEVAL_MODES.keys())
    
    print(f"=== RAG 消融测试 ===")
    print(f"数据集: {dataset_path}")
    print(f"测试模式: {', '.join(modes)}")
    print()
    
    # 加载数据集
    cases = load_cases(dataset_path)
    print(f"加载 {len(cases)} 条测试用例")
    print()
    
    results_by_mode = {}
    
    for mode in modes:
        print(f"--- 测试模式: {mode} ({RETRIEVAL_MODES[mode]}) ---")
        
        # 创建检索器
        retriever_func = test_retriever_with_mode(mode)
        
        # 执行检索
        runs = {}
        start_time = time.time()
        
        for i, case in enumerate(cases):
            try:
                result = retriever_func(
                    query=case.query,
                    **case.filters,
                )
                runs[case.case_id] = result
                
                if (i + 1) % 10 == 0:
                    print(f"  已完成 {i + 1}/{len(cases)} 条")
                    
            except Exception as e:
                print(f"  错误 [{case.case_id}]: {e}")
                runs[case.case_id] = {"hits": [], "no_answer": True, "error": str(e)}
        
        elapsed = time.time() - start_time
        
        # 计算指标
        metrics = evaluate(cases, runs, k_values=(5, 10))
        metrics["mode"] = mode
        metrics["total_time_seconds"] = round(elapsed, 2)
        metrics["avg_latency_ms"] = round(elapsed * 1000 / len(cases), 2)
        
        results_by_mode[mode] = metrics
        
        print(f"  Recall@5: {metrics.get('recall_at_5', 'N/A')}")
        print(f"  MRR@10: {metrics.get('mrr_at_10', 'N/A')}")
        print(f"  NDCG@5: {metrics.get('ndcg_at_5', 'N/A')}")
        print(f"  HitRate@5: {metrics.get('hit_rate_at_5', 'N/A')}")
        print(f"  No-answer FPR: {metrics.get('no_answer_false_positive_rate', 'N/A')}")
        print(f"  平均延迟: {metrics.get('latency_ms', {}).get('p50', 'N/A')} ms (p50)")
        print()
    
    return results_by_mode


def run_full_chain_test(
    dataset_path: str,
    retrieval_mode: str = "rrf",
    use_llm_judge: bool = True,
):
    """运行全链路测试
    
    Args:
        dataset_path: 数据集路径
        retrieval_mode: 检索模式
        use_llm_judge: 是否使用 LLM-as-judge
    """
    print(f"=== RAG 全链路测试 ===")
    print(f"数据集: {dataset_path}")
    print(f"检索模式: {retrieval_mode}")
    print(f"LLM-as-judge: {'启用' if use_llm_judge else '禁用'}")
    print()
    
    # 创建检索器
    retriever_func = test_retriever_with_mode(retrieval_mode)
    
    # 创建生成器（用于第 3 层评测）
    def generator(query: str, context: list) -> str:
        """调用 LLM 生成回答"""
        from after_sales_agent.providers.llm_client import get_llm_client
        client = get_llm_client()
        
        # 构建上下文文本（只取 top-3，减少噪音）
        context_text = "\n\n".join([
            "[知识 " + str(i+1) + "] " + chunk.get('chunk_text', '')
            for i, chunk in enumerate(context[:3])
        ])
        
        system_prompt = """你是售后客服助手。根据知识库内容回答用户问题。

核心原则：优先回答。只有知识库完全没有提及用户问题的主题时，才拒答。

判断标准：
- "相关" = 知识库提到了用户问题涉及的商品类型、问题类型或政策类别
- "不相关" = 知识库完全没有提及用户问题的主题

回答规则：
1. 知识库有相关信息 → 基于该信息完整回答
2. 知识库只有部分信息 → 回答能确认的部分，对缺失部分说"现有知识库未提及该细节"
3. 知识库完全无相关信息 → 回复：抱歉，根据现有知识库无法回答该问题
4. 可以对知识库内容做同义改写和合理总结（如"可能属于"→"属于"）
5. 不要编造知识库中不存在的具体数字、时限、政策条款
6. 禁止因为部分信息缺失而整体拒答"""
        
        user_prompt = "根据以下知识回答：\n\n" + context_text + "\n\n问题：" + query
        
        try:
            response = client.chat([
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}
            ], max_tokens=500, temperature=0)
            
            if 'choices' in response:
                return response['choices'][0]['message']['content']
            return response.get('message', {}).get('content', '')
        except Exception as e:
            print("Generator error:", e)
            return "抱歉，暂时无法回答您的问题。"
    
    # 创建 business_judge（用于第 4 层评测）
    def business_judge(query: str, result: dict) -> dict:
        """判断路由是否正确：有 hits 则应 ANSWER，无 hits 则应 NO_ANSWER"""
        hits = result.get('hits', [])
        no_answer = result.get('no_answer', False)
        
        # 简单路由判断：有 hits 且 no_answer=False → ANSWER
        # 无 hits 或 no_answer=True → NO_ANSWER
        predicted_answer = bool(hits) and not no_answer
        
        return {
            'predicted_answer': predicted_answer,
            'no_answer': not predicted_answer,
        }
    
    # 创建测试器
    tester = RAGFullChainTester(
        retriever=retriever_func,
        generator=generator,
        business评判器=business_judge,
        use_llm_judge=use_llm_judge,
    )
    
    # 运行测试
    report = tester.run_full_test(dataset_path)
    
    # 生成报告
    markdown_report = generate_markdown_report(report)
    
    # 保存报告
    report_path = ROOT / "evaluation" / f"full_chain_report_{retrieval_mode}.md"
    report_path.write_text(markdown_report, encoding="utf-8")
    
    print(f"\n测试报告已保存到: {report_path}")
    print("\n=== 测试结果摘要 ===")
    print(f"数据集质量分数: {report.dataset_quality.quality_score}/100")
    print(f"Recall@5: {report.retrieval_metrics.recall_at_5}")
    print(f"NDCG@5: {report.retrieval_metrics.ndcg_at_5}")
    print(f"MRR@10: {report.retrieval_metrics.mrr_at_10}")
    print(f"Context Recall: {report.context_metrics.context_recall}")
    print(f"Context Precision: {report.context_metrics.context_precision}")
    
    if report.generation_metrics.faithfulness is not None:
        print(f"Faithfulness: {report.generation_metrics.faithfulness}")
        print(f"Hallucination Rate: {report.generation_metrics.hallucination_rate}")
    
    if report.business_metrics.accuracy is not None:
        print(f"Routing Accuracy: {report.business_metrics.accuracy}")
    
    return report


def run_dataset_validation(dataset_path: str):
    """运行数据集质量验证"""
    print(f"=== 数据集质量验证 ===")
    print(f"数据集: {dataset_path}")
    print()
    
    # 加载数据集
    cases = load_cases(dataset_path)
    
    # 统计信息
    total = len(cases)
    positive = [c for c in cases if c.relevant_chunk_ids and not c.expect_no_answer]
    negative = [c for c in cases if c.expect_no_answer]
    
    # 查询唯一性
    queries = [c.query for c in cases]
    unique_queries = len(set(queries))
    
    # 品类分布
    categories = {}
    for c in cases:
        cat = c.category
        categories[cat] = categories.get(cat, 0) + 1
    
    # 标注方法分布
    annotations = {}
    for c in cases:
        ann = c.annotation_method
        annotations[ann] = annotations.get(ann, 0) + 1
    
    # 多 chunk 统计
    multi_chunk = [c for c in positive if len(c.relevant_chunk_ids) > 1]
    
    print(f"总样本数: {total}")
    print(f"正向样本: {len(positive)}")
    print(f"负向样本: {len(negative)}")
    print(f"唯一查询: {unique_queries}")
    print(f"多 chunk 场景: {len(multi_chunk)}")
    print()
    
    print("品类分布:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
    print()
    
    print("标注方法分布:")
    for ann, count in sorted(annotations.items()):
        print(f"  {ann}: {count}")
    print()
    
    # 验证 chunk_id 存在性
    print("验证 chunk_id 存在性...")
    all_chunk_ids = set()
    for c in positive:
        all_chunk_ids.update(c.relevant_chunk_ids)
    
    print(f"  唯一 chunk_id 数量: {len(all_chunk_ids)}")
    print(f"  chunk_id 列表: {sorted(all_chunk_ids, key=lambda x: int(x))[:10]}...")
    
    return {
        "total": total,
        "positive": len(positive),
        "negative": len(negative),
        "unique_queries": unique_queries,
        "multi_chunk": len(multi_chunk),
        "categories": categories,
        "annotations": annotations,
    }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="RAG 全链路完整测试")
    parser.add_argument(
        "command",
        choices=["validate", "ablation", "full", "all"],
        help="测试类型: validate=数据集验证, ablation=消融测试, full=全链路测试, all=全部测试",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=str(ROOT / "evaluation" / "rag_full_chain_cases.jsonl"),
        help="数据集路径",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["dense", "keyword", "rrf", "rerank"],
        default="rrf",
        help="检索模式 (仅 full 命令需要)",
    )
    parser.add_argument(
        "--no-llm-judge",
        action="store_true",
        help="禁用 LLM-as-judge，使用词重叠方法",
    )
    parser.add_argument(
        "--ablation-modes",
        type=str,
        nargs="+",
        choices=["dense", "keyword", "rrf", "rerank"],
        help="消融测试的模式列表",
    )
    
    args = parser.parse_args()
    
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"数据集不存在: {dataset_path}")
        sys.exit(1)
    
    if args.command == "validate":
        run_dataset_validation(str(dataset_path))
        
    elif args.command == "ablation":
        modes = args.ablation_modes or ["dense", "keyword", "rrf", "rerank"]
        results = run_ablation_test(str(dataset_path), modes)
        
        # 保存消融测试结果
        results_path = ROOT / "evaluation" / "ablation_results.json"
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        print(f"消融测试结果已保存到: {results_path}")
        
    elif args.command == "full":
        use_llm_judge = not args.no_llm_judge
        run_full_chain_test(str(dataset_path), args.mode, use_llm_judge)
        
    elif args.command == "all":
        # 运行所有测试
        print("=" * 60)
        print("开始 RAG 全链路完整测试")
        print("=" * 60)
        print()
        
        # 1. 数据集验证
        run_dataset_validation(str(dataset_path))
        print()
        
        # 2. 消融测试
        print("=" * 60)
        ablation_results = run_ablation_test(str(dataset_path))
        print()
        
        # 3. 全链路测试 (使用 rerank 模式 + LLM-as-judge)
        print("=" * 60)
        report = run_full_chain_test(str(dataset_path), "rerank", True)
        
        # 保存所有结果
        results_path = ROOT / "evaluation" / "full_test_results.json"
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump({
                "ablation": ablation_results,
                "full_chain": {
                    "dataset_quality": {
                        "total_cases": report.dataset_quality.total_cases,
                        "quality_score": report.dataset_quality.quality_score,
                    },
                    "retrieval": {
                        "recall_at_5": report.retrieval_metrics.recall_at_5,
                        "ndcg_at_5": report.retrieval_metrics.ndcg_at_5,
                        "mrr_at_10": report.retrieval_metrics.mrr_at_10,
                    },
                    "context": {
                        "recall": report.context_metrics.context_recall,
                        "precision": report.context_metrics.context_precision,
                    },
                    "generation": {
                        "faithfulness": report.generation_metrics.faithfulness,
                        "hallucination_rate": report.generation_metrics.hallucination_rate,
                    },
                    "business": {
                        "accuracy": report.business_metrics.accuracy,
                    },
                },
            }, f, ensure_ascii=False, indent=2, default=str)
        
        print()
        print("=" * 60)
        print("测试完成！")
        print("=" * 60)


if __name__ == "__main__":
    main()

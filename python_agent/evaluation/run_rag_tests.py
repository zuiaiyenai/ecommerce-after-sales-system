"""RAG 全链路测试运行脚本 - 实际执行测试"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from after_sales_agent.retrieval.pgvector_retriever import PgVectorKnowledgeRetriever, PgVectorConfig
from evaluation.rag_full_chain_test import (
    RAGFullChainTester,
    generate_markdown_report,
)
from evaluation.generate_test_cases import (
    generate_smoke_test_dataset,
    generate_full_test_dataset,
)

# 模块级单例 retriever，避免每次测试都创建新实例
_retriever_instance: PgVectorKnowledgeRetriever | None = None


def get_retriever() -> PgVectorKnowledgeRetriever:
    """获取检索器单例"""
    global _retriever_instance
    if _retriever_instance is None:
        config = PgVectorConfig.from_env()
        _retriever_instance = PgVectorKnowledgeRetriever(config)
    return _retriever_instance


def test_retriever(query: str, **filters) -> dict:
    """测试检索器函数（使用单例）"""
    retriever = get_retriever()
    return retriever.retrieve(query=query, **filters)


def run_smoke_test():
    """运行冒烟测试"""
    print("=== 运行 RAG 冒烟测试 ===\n")
    
    # 生成测试数据集
    dataset_path = ROOT / "evaluation" / "rag_smoke_test_cases.jsonl"
    if not dataset_path.exists():
        print("生成冒烟测试数据集...")
        generate_smoke_test_dataset(output_path=dataset_path)
    
    # 创建测试器
    tester = RAGFullChainTester(retriever=test_retriever)
    
    # 运行测试
    report = tester.run_full_test(dataset_path)
    
    # 生成报告
    markdown_report = generate_markdown_report(report)
    
    # 保存报告
    report_path = ROOT / "evaluation" / "smoke_test_report.md"
    report_path.write_text(markdown_report, encoding="utf-8")
    
    print(f"\n测试报告已保存到: {report_path}")
    print("\n=== 测试结果摘要 ===")
    print(f"数据集质量分数: {report.dataset_quality.quality_score}/100")
    print(f"Recall@5: {report.retrieval_metrics.recall_at_5}")
    print(f"NDCG@5: {report.retrieval_metrics.ndcg_at_5}")
    print(f"平均延迟: {report.retrieval_metrics.latency_avg_ms} ms")
    
    return report


def run_full_test():
    """运行完整测试"""
    print("=== 运行 RAG 完整测试 ===\n")
    
    # 生成测试数据集
    dataset_path = ROOT / "evaluation" / "rag_full_test_cases.jsonl"
    if not dataset_path.exists():
        print("生成完整测试数据集...")
        generate_full_test_dataset(output_path=dataset_path)
    
    # 创建测试器
    tester = RAGFullChainTester(retriever=test_retriever)
    
    # 运行测试
    report = tester.run_full_test(dataset_path)
    
    # 生成报告
    markdown_report = generate_markdown_report(report)
    
    # 保存报告
    report_path = ROOT / "evaluation" / "full_test_report.md"
    report_path.write_text(markdown_report, encoding="utf-8")
    
    print(f"\n测试报告已保存到: {report_path}")
    print("\n=== 测试结果摘要 ===")
    print(f"数据集质量分数: {report.dataset_quality.quality_score}/100")
    print(f"Recall@5: {report.retrieval_metrics.recall_at_5}")
    print(f"NDCG@5: {report.retrieval_metrics.ndcg_at_5}")
    print(f"Context F1: {report.context_metrics.context_f1}")
    print(f"平均延迟: {report.retrieval_metrics.latency_avg_ms} ms")
    
    return report


def run_existing_dataset_test(dataset_path: str):
    """运行现有数据集测试"""
    print(f"=== 运行现有数据集测试: {dataset_path} ===\n")
    
    dataset_path = Path(dataset_path)
    if not dataset_path.exists():
        print(f"数据集不存在: {dataset_path}")
        return None
    
    # 创建测试器
    tester = RAGFullChainTester(retriever=test_retriever)
    
    # 运行测试
    report = tester.run_full_test(dataset_path)
    
    # 生成报告
    markdown_report = generate_markdown_report(report)
    
    # 保存报告
    report_filename = f"test_report_{dataset_path.stem}.md"
    report_path = ROOT / "evaluation" / report_filename
    report_path.write_text(markdown_report, encoding="utf-8")
    
    print(f"\n测试报告已保存到: {report_path}")
    print("\n=== 测试结果摘要 ===")
    print(f"数据集质量分数: {report.dataset_quality.quality_score}/100")
    print(f"Recall@5: {report.retrieval_metrics.recall_at_5}")
    print(f"NDCG@5: {report.retrieval_metrics.ndcg_at_5}")
    print(f"平均延迟: {report.retrieval_metrics.latency_avg_ms} ms")
    
    return report


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="RAG 全链路测试")
    parser.add_argument(
        "command",
        choices=["smoke", "full", "dataset"],
        help="测试类型: smoke=冒烟测试, full=完整测试, dataset=指定数据集测试",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        help="指定数据集路径 (仅 dataset 命令需要)",
    )
    
    args = parser.parse_args()
    
    if args.command == "smoke":
        run_smoke_test()
    elif args.command == "full":
        run_full_test()
    elif args.command == "dataset":
        if not args.dataset:
            print("请指定 --dataset 参数")
            sys.exit(1)
        run_existing_dataset_test(args.dataset)


if __name__ == "__main__":
    main()

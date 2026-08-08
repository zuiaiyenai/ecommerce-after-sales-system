from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import EvidenceTask, PolicyTask
from ..tool_registry import ToolResult


class ToolExecutor(Protocol):
    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        ...


@dataclass(frozen=True)
class RegistryPolicyRetrievalPort:
    tools: ToolExecutor

    def retrieve(self, task: PolicyTask) -> ToolResult:
        return self.tools.call(
            "retrieve_knowledge",
            {
                "user_id": task.user_id,
                "query": task.query,
                "merchant_code": task.merchant_code,
                "product_category": task.product_category,
                "source_type": "after_sales_policy",
                "policy_version": task.policy_version,
                "as_of_time": task.business_time,
                "top_k": 5,
            },
        )

    def retrieve_multi(
        self,
        task: PolicyTask,
        queries: tuple[str, ...],
    ) -> ToolResult:
        return self.tools.call(
            "retrieve_knowledge_multi",
            {
                "user_id": task.user_id,
                "original_query": task.query,
                "queries": list(queries[:3]),
                "merchant_code": task.merchant_code,
                "product_category": task.product_category,
                "source_type": "after_sales_policy",
                "policy_version": task.policy_version,
                "as_of_time": task.business_time,
                "top_k": 5,
            },
        )


@dataclass(frozen=True)
class RegistryEvidenceReviewPort:
    tools: ToolExecutor

    def review(self, task: EvidenceTask) -> ToolResult:
        return self.tools.call(
            "review_images",
            {
                "user_id": task.user_id,
                "order_id": task.order_id,
                "attachments": [dict(item) for item in task.attachments],
                "order_hint": " ".join(
                    item
                    for item in (task.product_name, task.product_category)
                    if item
                ),
                "issue_hint": task.issue,
            },
        )

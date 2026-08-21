from __future__ import annotations

import json

import pytest

from after_sales_agent.application.rag_query_rewrite import (
    RagQueryRewriteService,
    RagRewriteProtocolError,
)


class RecordingRewriteLlm:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def chat_json(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(dict(kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response  # type: ignore[return-value]

    def generate_structured(self, *, system_prompt, user_prompt, schema, **kwargs: object) -> dict[str, object]:
        self.requests.append({"user_prompt": user_prompt, "schema": schema, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response  # type: ignore[return-value]


def evaluation_input() -> dict[str, object]:
    return {
        "user_question": "耳机超过七天后出现电流声，还能申请质量售后吗？",
        "task": "核验质量售后政策和证据要求",
        "known_facts": {
            "product_name": "蓝牙降噪耳机",
            "product_category": "数码",
            "issue_type": "functional_quality_issue",
            "after_sales_type": "RETURN_REFUND",
            "ticket_id": "TICKET-SHOULD-NOT-BE-SENT",
        },
        "original_query": "耳机 电流声 超过七天 质量售后",
        "previous_queries": ["耳机 电流声 超过七天 质量售后"],
        "require_trusted_policy": True,
        "retrieval_result": {
            "mode": "hybrid_reranked",
            "hits": [
                {
                    "title": "普通退款流程",
                    "snippet": "A" * 900,
                    "score": 0.82,
                    "citations": [
                        {
                            "source_code": "POLICY-001",
                            "chunk_id": "CHUNK-001",
                            "private_field": "do-not-send",
                        }
                    ],
                    "metadata": {"database_secret": "do-not-send"},
                }
            ],
        },
    }


def test_sufficient_decision_drops_unneeded_candidates() -> None:
    llm = RecordingRewriteLlm(
        {
            "sufficient": True,
            "confidence": 0.93,
            "covered_aspects": ["时效", "质量问题规则"],
            "missing_aspects": [],
            "queries": [{"query": "不应执行的查询", "focus": "unused"}],
            "filters": {"merchant_code": "FORGED"},
        }
    )
    service = RagQueryRewriteService(llm=llm)

    decision = service.evaluate(**evaluation_input())

    assert decision.sufficient
    assert decision.queries == ()
    assert decision.confidence == 0.93


def test_insufficient_decision_returns_distinct_valid_candidates_only() -> None:
    llm = RecordingRewriteLlm(
        {
            "sufficient": False,
            "confidence": 0.81,
            "covered_aspects": ["普通退款流程"],
            "missing_aspects": ["质量问题时效例外", "责任认定"],
            "queries": [
                {
                    "query": "数码商品超过普通退货时效后的质量售后适用条件",
                    "focus": "时效例外",
                    "merchant_code": "FORGED",
                },
                {
                    "query": "商品功能异常与人为损坏的认定标准及凭证",
                    "focus": "责任认定",
                },
                {
                    "query": "商品功能异常与人为损坏的认定标准及凭证",
                    "focus": "重复项",
                },
                {
                    "query": "第四条不会被保留，因为硬上限为三条候选查询",
                    "focus": "超限",
                },
            ],
            "filters": {"policy_version": "FORGED"},
        }
    )
    service = RagQueryRewriteService(llm=llm)

    decision = service.evaluate(**evaluation_input())

    assert not decision.sufficient
    assert [item.query for item in decision.queries] == [
        "数码商品超过普通退货时效后的质量售后适用条件",
        "商品功能异常与人为损坏的认定标准及凭证",
        "第四条不会被保留，因为硬上限为三条候选查询",
    ]
    assert [item.focus for item in decision.queries] == ["时效例外", "责任认定", "超限"]
    assert not hasattr(decision.queries[0], "merchant_code")


def test_terminal_evaluation_accepts_insufficient_result_without_more_queries() -> None:
    llm = RecordingRewriteLlm(
        {
            "sufficient": False,
            "confidence": 0.88,
            "covered_aspects": ["通用质量规则"],
            "missing_aspects": ["手机专项政策"],
            "queries": [],
        }
    )
    service = RagQueryRewriteService(llm=llm)

    decision = service.evaluate(**evaluation_input(), allow_rewrite=False)

    assert not decision.sufficient
    assert decision.queries == ()
    payload = json.loads(str(llm.requests[0]["user_prompt"]))
    assert payload["allow_rewrite"] is False


def test_case_facts_and_out_of_scope_gaps_do_not_make_knowledge_insufficient() -> None:
    llm = RecordingRewriteLlm(
        {
            "sufficient": False,
            "confidence": 0.91,
            "covered_aspects": ["质量问题规则", "排除条件", "凭证要求"],
            "knowledge_missing_aspects": [],
            "case_fact_gaps": ["尚未查询订单签收时间"],
            "out_of_scope_aspects": ["手机屏幕故障硬件根因诊断"],
            "queries": [
                {
                    "query": "不应继续执行的订单事实或技术诊断查询",
                    "focus": "非知识缺口",
                }
            ],
        }
    )
    service = RagQueryRewriteService(llm=llm)

    decision = service.evaluate(**evaluation_input())

    assert decision.sufficient
    assert decision.missing_aspects == ()
    assert decision.case_fact_gaps == ("尚未查询订单签收时间",)
    assert decision.out_of_scope_aspects == ("手机屏幕故障硬件根因诊断",)
    assert decision.queries == ()


def test_real_knowledge_gap_remains_insufficient() -> None:
    llm = RecordingRewriteLlm(
        {
            "sufficient": False,
            "confidence": 0.89,
            "covered_aspects": ["七天无理由退货通用规则"],
            "knowledge_missing_aspects": ["定制刻字商品是否排除无理由退货"],
            "case_fact_gaps": ["尚未查询签收时间"],
            "out_of_scope_aspects": [],
            "queries": [
                {
                    "query": "定制刻字商品七天无理由退货排除规则",
                    "focus": "定制商品政策",
                }
            ],
        }
    )
    service = RagQueryRewriteService(llm=llm)

    decision = service.evaluate(**evaluation_input())

    assert not decision.sufficient
    assert decision.missing_aspects == ("定制刻字商品是否排除无理由退货",)
    assert len(decision.queries) == 1


def test_prompt_separates_knowledge_gaps_from_missing_case_facts() -> None:
    prompt = RagQueryRewriteService._system_prompt()

    assert "缺少用户事实不等于知识不足" in prompt
    assert "后续工具查询或补充信息需求" in prompt


def test_prompt_requires_natural_queries_and_safe_semantic_expansion() -> None:
    prompt = RagQueryRewriteService._system_prompt()

    assert "不得输出用空格分隔的关键词堆叠" in prompt
    assert "可补充该现象在售后知识中常用的同义说法" in prompt
    assert "同义扩展必须用“类似、可能对应、是否属于”等非断言表达" in prompt
    assert "不得新增摔落、进水、时效、检测结果或退款资格" in prompt


def test_prompt_treats_conditional_guidance_as_sufficient_knowledge() -> None:
    prompt = RagQueryRewriteService._system_prompt()

    assert "能够给出条件性判断也属于知识充分" in prompt
    assert "不能直接认定责任不等于知识不足" in prompt
    assert "不得要求知识逐字包含用户描述的每一种现象" in prompt
    assert "不得额外要求完整退款流程" in prompt


def test_prompt_contains_only_allowlisted_facts_and_truncated_hit_summary() -> None:
    llm = RecordingRewriteLlm(
        {
            "sufficient": True,
            "confidence": 0.8,
            "covered_aspects": [],
            "missing_aspects": [],
            "queries": [],
        }
    )
    service = RagQueryRewriteService(llm=llm)

    service.evaluate(**evaluation_input())

    payload = json.loads(str(llm.requests[0]["user_prompt"]))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["known_facts"]["product_name"] == "蓝牙降噪耳机"
    assert "ticket_id" not in payload["known_facts"]
    assert "TICKET-SHOULD-NOT-BE-SENT" not in serialized
    assert "database_secret" not in serialized
    assert "private_field" not in serialized
    assert len(payload["retrieval_hits"][0]["snippet"]) == 500
    assert payload["retrieval_contract"] == {
        "mode": "hybrid_reranked",
        "no_answer": False,
        "filter_level": "",
        "reranker_succeeded": False,
        "trusted_policy_eligible": False,
    }


@pytest.mark.parametrize(
    "response",
    [
        {"sufficient": "false", "confidence": 0.8, "queries": []},
        {"sufficient": False, "confidence": 1.5, "queries": []},
        {
            "sufficient": False,
            "confidence": 0.8,
            "covered_aspects": [],
            "missing_aspects": ["政策条件"],
            "queries": [{"query": "短", "focus": "invalid"}],
        },
    ],
)
def test_invalid_protocol_fails_closed(response: dict[str, object]) -> None:
    service = RagQueryRewriteService(llm=RecordingRewriteLlm(response))

    with pytest.raises(RagRewriteProtocolError):
        service.evaluate(**evaluation_input())

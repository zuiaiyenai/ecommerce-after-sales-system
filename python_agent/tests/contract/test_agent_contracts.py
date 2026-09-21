from __future__ import annotations

from datetime import datetime, timedelta
import os
import unittest
from unittest.mock import MagicMock, Mock, patch

import after_sales_agent.domain.models as domain_models
from after_sales_agent.application.after_sales_workflow import LangGraphAfterSalesAgent
from after_sales_agent.infrastructure import ActiveDocumentRow
from after_sales_agent.application.knowledge_admin_service import KnowledgeAdminService
from after_sales_agent.tools import AgentToolRegistry
from after_sales_agent.interface.http_server import (
    build_chat_entry_payload,
    is_valid_internal_token,
    resolve_internal_request_token,
)
from after_sales_agent.integrations.java_tool_client import JavaToolError


class RecordingJavaClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def post(self, path: str, payload: dict):
        self.calls.append((path, payload))
        if path == "/orders/search":
            return [
                {
                    "orderId": "9007199254740995",
                    "orderNo": "ORDER-20260714-1",
                    "existingTicketId": "9007199254740993",
                }
            ]
        return {"reviewApplied": True}

    def get(self, path: str, params: dict):
        self.calls.append((path, params))
        return {}


class FailingJavaClient(RecordingJavaClient):
    def post(self, path: str, payload: dict):
        raise JavaToolError(
            "Java service is temporarily unavailable",
            code="JAVA_HTTP_503",
            category="service_unavailable",
            retryable=True,
            http_status=503,
        )


class AgentContractTest(unittest.TestCase):
    def test_ticket_id_and_ticket_no_remain_distinct(self) -> None:
        normalized = LangGraphAfterSalesAgent._normalize_ticket(
            {
                "ticket_id": "9007199254740993",
                "ticket_no": "AS202607140001",
                "order_id": "9007199254740995",
                "status": "PENDING_REVIEW",
            }
        )

        self.assertEqual("9007199254740993", normalized["ticket_id"])
        self.assertEqual("AS202607140001", normalized["ticket_no"])
        self.assertEqual("9007199254740995", normalized["order_id"])

    def test_removed_generic_id_is_not_interpreted_as_ticket_id(self) -> None:
        normalized = LangGraphAfterSalesAgent._normalize_ticket(
            {
                "id": "9007199254740993",
                "ticket_no": "AS202607140001",
                "status": "PENDING_REVIEW",
            }
        )

        self.assertIsNone(normalized["ticket_id"])

    def test_submit_review_uses_java_rest_camel_case_boundary(self) -> None:
        java = RecordingJavaClient()
        registry = AgentToolRegistry(java=java, retriever=Mock(), vision=Mock())

        registry.submit_ai_review(
            {
                "user_id": "20001",
                "ticket_id": "9007199254740993",
                "order_id": "9007199254740995",
                "review_request_id": "review-1",
                "verdict": "APPROVE",
                "filter_level": "strict",
                "reranker_succeeded": True,
                "trusted_policy_eligible": True,
                "policy_version": "v2",
            }
        )

        path, payload = java.calls[0]
        self.assertEqual("/aftersales/review", path)
        self.assertEqual("9007199254740993", payload["ticketId"])
        self.assertEqual("9007199254740995", payload["orderId"])
        self.assertEqual("review-1", payload["reviewRequestId"])
        self.assertEqual("strict", payload["filterLevel"])
        self.assertTrue(payload["rerankerSucceeded"])
        self.assertTrue(payload["trustedPolicyEligible"])
        self.assertEqual("v2", payload["policyVersion"])
        self.assertNotIn("ticket_id", payload)
        self.assertNotIn("order_id", payload)

    def test_tool_registry_rejects_camel_case_internal_identifiers(self) -> None:
        java = RecordingJavaClient()
        registry = AgentToolRegistry(java=java, retriever=Mock(), vision=Mock())

        missing_user = registry.call(
            "get_after_sales_ticket",
            {"userId": "20001", "ticket_id": "9007199254740993"},
        )
        missing_ticket = registry.call(
            "get_after_sales_ticket",
            {"user_id": "20001", "ticketId": "9007199254740993"},
        )

        self.assertFalse(missing_user.ok)
        self.assertIn("user_id is required", missing_user.error)
        self.assertFalse(missing_ticket.ok)
        self.assertIn("ticket_id is required", missing_ticket.error)
        self.assertEqual([], java.calls)

    def test_tool_registry_accepts_snake_case_and_emits_camel_case(self) -> None:
        java = RecordingJavaClient()
        registry = AgentToolRegistry(java=java, retriever=Mock(), vision=Mock())

        result = registry.call(
            "submit_ai_review",
            {
                "user_id": "20001",
                "ticket_id": "9007199254740993",
                "order_id": "9007199254740995",
                "review_request_id": "review-2",
                "verdict": "APPROVE",
            },
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.data["review_applied"])
        self.assertNotIn("reviewApplied", result.data)
        _, payload = java.calls[0]
        self.assertEqual("9007199254740993", payload["ticketId"])
        self.assertEqual("9007199254740995", payload["orderId"])
        self.assertEqual("review-2", payload["reviewRequestId"])
        self.assertNotIn("ticket_id", payload)
        self.assertNotIn("order_id", payload)

    def test_tool_registry_normalizes_java_response_to_snake_case(self) -> None:
        registry = AgentToolRegistry(java=RecordingJavaClient(), retriever=Mock(), vision=Mock())

        result = registry.call("search_user_orders", {"user_id": "20001"})

        self.assertTrue(result.ok)
        self.assertEqual("9007199254740995", result.data[0]["order_id"])
        self.assertEqual("ORDER-20260714-1", result.data[0]["order_no"])
        self.assertEqual("9007199254740993", result.data[0]["existing_ticket_id"])
        self.assertNotIn("orderId", result.data[0])

    def test_empty_legacy_citation_is_not_normalized_as_traceable(self) -> None:
        retriever = Mock()
        retriever.retrieve.return_value = {
            "hits": [{"citation": {}}, {"citation": {"source_code": "POLICY-2"}}]
        }
        registry = AgentToolRegistry(java=RecordingJavaClient(), retriever=retriever, vision=Mock())

        result = registry.retrieve_knowledge({"query": "refund"})

        self.assertEqual([], result["hits"][0]["citations"])
        self.assertEqual([], result["hits"][1]["citations"])
        self.assertEqual("rerank", retriever.retrieve.call_args.kwargs["retrieval_mode"])

    def test_existing_ticket_keeps_ticket_id_separate_from_ticket_number(self) -> None:
        ticket = LangGraphAfterSalesAgent._ticket_from_existing_order(
            {
                "order_id": "9007199254740995",
                "existing_ticket_id": "9007199254740993",
                "existing_ticket_no": "AS202607140001",
                "after_sales_status": "PENDING_REVIEW",
            }
        )

        self.assertEqual("9007199254740993", ticket["ticket_id"])
        self.assertEqual("AS202607140001", ticket["ticket_no"])
        self.assertNotIn("ticketId", ticket)

    def test_order_selection_accepts_explicit_order_id(self) -> None:
        state = {
            "order_id_hint": "9007199254740995",
            "tool_results": [
                {
                    "tool": "search_user_orders",
                    "ok": True,
                    "data": [
                        {
                            "order_id": "9007199254740995",
                            "order_no": "ORDER-20260714-1",
                        }
                    ],
                }
            ],
        }

        selected = LangGraphAfterSalesAgent._selected_order(state)
        self.assertEqual("9007199254740995", selected["order_id"])

    def test_order_selection_does_not_match_removed_generic_id(self) -> None:
        state = {
            "order_id_hint": "legacy-order-id",
            "tool_results": [
                {
                    "tool": "search_user_orders",
                    "ok": True,
                    "data": [
                        {"id": "legacy-order-id", "order_no": "ORDER-1"},
                        {"id": "other-legacy-id", "order_no": "ORDER-2"},
                    ],
                }
            ],
        }

        self.assertIsNone(LangGraphAfterSalesAgent._selected_order(state))

    def test_order_from_ticket_produces_explicit_order_id(self) -> None:
        order = LangGraphAfterSalesAgent._order_from_ticket(
            {
                "order_id": "9007199254740995",
                "order_no": "ORDER-20260714-1",
            }
        )

        self.assertEqual("9007199254740995", order["order_id"])
        self.assertNotIn("id", order)

    def test_agent_registry_has_no_ticket_creation_tool(self) -> None:
        registry = AgentToolRegistry(java=Mock(), retriever=Mock(), vision=Mock())
        self.assertNotIn("create_after_sales_ticket", registry.registry())
        self.assertNotIn("create_ticket", registry.registry())

    def test_tool_failure_keeps_machine_readable_error_contract(self) -> None:
        registry = AgentToolRegistry(java=FailingJavaClient(), retriever=Mock(), vision=Mock())

        result = registry.call("search_user_orders", {"user_id": "20001"})

        self.assertFalse(result.ok)
        self.assertEqual("JAVA_HTTP_503", result.error_code)
        self.assertEqual("service_unavailable", result.error_category)
        self.assertTrue(result.retryable)

    def test_tool_specs_expose_risk_and_idempotency_metadata(self) -> None:
        registry = AgentToolRegistry(java=Mock(), retriever=Mock(), vision=Mock())
        specs = {item["name"]: item for item in registry.tool_specs()}

        self.assertTrue(specs["search_user_orders"]["read_only"])
        self.assertEqual("high", specs["submit_ai_review"]["risk_level"])
        review_schema = specs["submit_ai_review"]["input_schema"]
        self.assertIn("verdict", review_schema["required"])
        self.assertNotIn("ticket_id", review_schema["required"])
        self.assertNotIn("ticket_id", review_schema["properties"])
        self.assertTrue(specs["submit_ai_review"]["idempotent"])
        as_of_schema = specs["retrieve_knowledge"]["input_schema"]["properties"]["as_of_time"]
        self.assertEqual("string", as_of_schema["type"])
        self.assertEqual("date-time", as_of_schema["format"])
        self.assertEqual(
            "string",
            specs["retrieve_knowledge"]["input_schema"]["properties"]["policy_version"]["type"],
        )

    def test_workflow_injects_trusted_ticket_id_after_model_schema_validation(self) -> None:
        state = {
            "user_id": "trusted-user",
            "ticket_id": "trusted-ticket",
            "allow_ai_review_submit": True,
        }

        LangGraphAfterSalesAgent._apply_action(state, {
            "action": "tool_call",
            "tool_name": "submit_ai_review",
            "tool_arguments": {"verdict": "APPROVE"},
        })

        self.assertEqual("trusted-ticket", state["tool_arguments"]["ticket_id"])

    def test_retrieve_knowledge_parses_timezone_aware_as_of_time(self) -> None:
        retriever = Mock()
        retriever.retrieve.return_value = {
            "hits": [{"citation": {"chunk_id": 7, "source_code": "POLICY-2"}}]
        }
        registry = AgentToolRegistry(java=Mock(), retriever=retriever, vision=Mock())

        result = registry.call(
            "retrieve_knowledge",
            {
                "query": "退款政策",
                "policy_version": "v2",
                "as_of_time": "2026-07-21T10:15:00+08:00",
            },
        )

        self.assertTrue(result.ok)
        parsed = retriever.retrieve.call_args.kwargs["as_of_time"]
        self.assertIsInstance(parsed, datetime)
        self.assertEqual(timedelta(hours=8), parsed.utcoffset())
        self.assertEqual("2026-07-21T10:15:00+08:00", parsed.isoformat())
        self.assertEqual("v2", retriever.retrieve.call_args.kwargs["policy_version"])
        self.assertEqual(
            [{"chunk_id": 7, "source_code": "POLICY-2"}],
            result.data["hits"][0]["citations"],
        )
        self.assertNotIn("citation", result.data["hits"][0])

    def test_knowledge_admin_passes_explicit_policy_context_without_inventing_time(self) -> None:
        retriever = Mock()
        retriever.retrieve.return_value = {
            "query": "refund",
            "mode": "hybrid_reranked",
            "filter_level": "strict",
            "reranker_succeeded": True,
            "trusted_policy_eligible": True,
            "hits": [{
                "source_type": "after_sales_policy",
                "citation": {"chunk_id": 7, "source_code": "POLICY-2"},
            }],
        }
        service = KnowledgeAdminService(retriever=retriever)

        result = service.retrieve({
            "query": "refund",
            "policy_version": "v2",
            "as_of_time": "2026-07-21T10:15:00+08:00",
        })

        kwargs = retriever.retrieve.call_args.kwargs
        self.assertEqual("v2", kwargs["policy_version"])
        self.assertEqual("2026-07-21T10:15:00+08:00", kwargs["as_of_time"].isoformat())
        self.assertTrue(result["reranker_succeeded"])
        self.assertTrue(result["trusted_policy_eligible"])
        self.assertEqual(
            [{"chunk_id": 7, "source_code": "POLICY-2"}],
            result["hits"][0]["citations"],
        )

        service.retrieve({"query": "faq"})
        self.assertIsNone(retriever.retrieve.call_args.kwargs["as_of_time"])

        service.retrieve({"query": "faq", "retrieval_mode": "keyword"})
        self.assertEqual("keyword", retriever.retrieve.call_args.kwargs["retrieval_mode"])

    def test_retrieve_knowledge_rejects_naive_or_invalid_as_of_time(self) -> None:
        retriever = Mock()
        registry = AgentToolRegistry(java=Mock(), retriever=retriever, vision=Mock())

        naive = registry.call(
            "retrieve_knowledge",
            {"query": "退款政策", "as_of_time": "2026-07-21T10:15:00"},
        )
        invalid = registry.call(
            "retrieve_knowledge",
            {"query": "退款政策", "as_of_time": "yesterday"},
        )

        self.assertFalse(naive.ok)
        self.assertEqual("INVALID_TOOL_ARGUMENTS", naive.error_code)
        self.assertIn("timezone", naive.error or "")
        self.assertFalse(invalid.ok)
        self.assertEqual("INVALID_TOOL_ARGUMENTS", invalid.error_code)
        retriever.retrieve.assert_not_called()

    def test_http_entry_uses_canonical_ticket_id(self) -> None:
        payload = build_chat_entry_payload(
            {"user_id": "1", "ticket_id": "9007199254740993", "message": "test"}
        )
        self.assertEqual("9007199254740993", payload["ticket_id"])

    def test_http_entry_replaces_forged_trust_markers(self) -> None:
        payload = build_chat_entry_payload(
            {
                "user_id": "1",
                "message": "test",
                "client_context": {
                    "source": "kafka",
                    "event_id": "forged-event",
                    "trusted_invocation": True,
                    "locale": "zh-CN",
                },
            }
        )

        self.assertEqual("java_gateway", payload["client_context"]["source"])
        self.assertEqual("zh-CN", payload["client_context"]["locale"])
        self.assertNotIn("event_id", payload["client_context"])
        self.assertNotIn("trusted_invocation", payload["client_context"])

    def test_internal_token_requires_two_non_empty_exact_values(self) -> None:
        self.assertTrue(is_valid_internal_token("shared-secret", "shared-secret"))
        self.assertFalse(is_valid_internal_token("wrong", "shared-secret"))
        self.assertFalse(is_valid_internal_token("", "shared-secret"))
        self.assertFalse(is_valid_internal_token("shared-secret", ""))

    def test_internal_token_supports_prometheus_bearer_authentication(self) -> None:
        self.assertEqual(
            "shared-secret",
            resolve_internal_request_token({"Authorization": "Bearer shared-secret"}),
        )
        self.assertEqual(
            "header-secret",
            resolve_internal_request_token({
                "X-Agent-Internal-Token": "header-secret",
                "Authorization": "Bearer bearer-secret",
            }),
        )
        self.assertIsNone(resolve_internal_request_token({"Authorization": "Basic abc"}))

    def test_http_entry_rejects_camel_case_contract_aliases(self) -> None:
        payload = build_chat_entry_payload(
            {
                "userId": "20001",
                "ticketId": "9007199254740993",
                "orderId": "9007199254740995",
                "sessionId": "9007199254740991",
                "recentHistory": [{"role": "user", "content": "legacy"}],
                "message": "test",
            }
        )

        self.assertEqual("0", payload["user_id"])
        self.assertIsNone(payload["ticket_id"])
        self.assertEqual("", payload["order_id"])
        self.assertIsNone(payload["session_id"])
        self.assertEqual([], payload["recent_history"])

    def test_graph_entry_accepts_only_snake_case(self) -> None:
        agent = object.__new__(LangGraphAfterSalesAgent)
        agent.graph = Mock()
        agent.graph.invoke.side_effect = lambda state: state

        agent._handle_core(
            {
                "userId": "20001",
                "sessionId": "9007199254740991",
                "ticketId": "9007199254740993",
                "reviewRequestId": "review-camel",
                "orderId": "9007199254740995",
                "recentHistory": [{"role": "user", "content": "legacy"}],
                "clientContext": {"source": "legacy"},
                "message": "test",
            }
        )

        state = agent.graph.invoke.call_args.args[0]
        self.assertEqual("0", state["user_id"])
        self.assertIsNone(state["session_id"])
        self.assertIsNone(state["ticket_id"])
        self.assertIsNone(state["review_request_id"])
        self.assertIsNone(state["order_id_hint"])
        self.assertEqual([], state["recent_history"])
        self.assertEqual({}, state["client_context"])

    def test_graph_entry_preserves_canonical_snake_case(self) -> None:
        agent = object.__new__(LangGraphAfterSalesAgent)
        agent.graph = Mock()
        agent.graph.invoke.side_effect = lambda state: state

        agent._handle_core(
            {
                "user_id": "20001",
                "session_id": "9007199254740991",
                "ticket_id": "9007199254740993",
                "review_request_id": "review-snake",
                "order_id": "9007199254740995",
                "recent_history": [{"role": "user", "content": "canonical"}],
                "client_context": {"source": "adapter"},
                "message": "test",
            }
        )

        state = agent.graph.invoke.call_args.args[0]
        self.assertEqual("20001", state["user_id"])
        self.assertEqual(9007199254740991, state["session_id"])
        self.assertEqual("9007199254740993", state["ticket_id"])
        self.assertEqual("review-snake", state["review_request_id"])
        self.assertEqual("9007199254740995", state["order_id_hint"])
        self.assertEqual("canonical", state["recent_history"][0]["content"])
        self.assertEqual("adapter", state["client_context"]["source"])

    def test_removed_after_sale_id_is_not_interpreted_as_ticket_id(self) -> None:
        payload = build_chat_entry_payload(
            {"user_id": "1", "afterSaleId": "9007199254740993", "message": "test"}
        )
        self.assertIsNone(payload["ticket_id"])

    def test_models_module_exports_required_types(self) -> None:
        """After merging domain_models into models, all key types must be importable."""
        import after_sales_agent.domain.models as models_mod

        required = (
            "AgentResult",
            "Attachment",
            "Decision",
            "EvidenceCheckResult",
            "HumanHandoffResult",
            "ImageReviewItem",
            "ImageReviewResult",
            "IntentResult",
            "Order",
            "RiskAssessmentResult",
            "RiskLevel",
            "StateTransitionResult",
            "Ticket",
            "TicketStatus",
        )
        for name in required:
            self.assertTrue(hasattr(models_mod, name), name)

    def test_knowledge_http_boundary_accepts_only_snake_case_filters(self) -> None:
        with patch(
            "after_sales_agent.application.knowledge_admin_service.PgVectorKnowledgeRetriever"
        ) as retriever_type:
            retriever_type.return_value.retrieve.return_value = {
                "query": "refund",
                "mode": "pgvector",
                "hits": [],
            }
            KnowledgeAdminService().retrieve(
                {
                    "query": "refund",
                    "merchantCode": "legacy-merchant",
                    "productCategory": "legacy-category",
                    "sourceType": "legacy-source",
                    "topK": 99,
                }
            )

        kwargs = retriever_type.return_value.retrieve.call_args.kwargs
        self.assertIsNone(kwargs["merchant_code"])
        self.assertIsNone(kwargs["product_category"])
        self.assertIsNone(kwargs["source_type"])
        self.assertIsNone(kwargs["top_k"])

    def test_knowledge_admin_reuses_one_retriever_across_requests(self) -> None:
        with patch(
            "after_sales_agent.application.knowledge_admin_service.PgVectorKnowledgeRetriever"
        ) as retriever_type:
            retriever_type.return_value.retrieve.return_value = {
                "query": "refund",
                "mode": "pgvector",
                "hits": [],
            }
            service = KnowledgeAdminService()
            service.retrieve({"query": "first"})
            service.retrieve({"query": "second"})

        retriever_type.assert_called_once()
        self.assertEqual(2, retriever_type.return_value.retrieve.call_count)

    def test_reindex_rebuilds_published_layered_chunk_contract(self) -> None:
        retriever = Mock()
        retriever.embed_many.return_value = [[0.1, 0.2]]
        retriever._vector_literal = lambda vec: "[" + ",".join(f"{v:.8f}" for v in vec) + "]"
        service = KnowledgeAdminService(retriever=retriever)
        service._knowledge_repository.list_active_documents = Mock(return_value=[ActiveDocumentRow(
            document_id=29,
            document_type="guideline",
            title="售后自动转人工边界",
            text="图片无法核验问题现象时转人工。",
            metadata={
                "product_category": None,
                "scene": "human_handoff",
                "intent": "guardrail",
            },
            revision=3,
            updated_at=datetime(2026, 7, 22, 10, 0),
            product_categories=None,
            scenes=["human_handoff"],
            intents=["guardrail"],
        )])
        service._knowledge_repository.lock_and_delete_chunks = Mock(
            return_value={29: (3, datetime(2026, 7, 22, 10, 0))}
        )
        service._knowledge_repository.insert_chunks = Mock()
        service._knowledge_repository.set_published_revision = Mock()

        with patch.dict(os.environ, {"PGVECTOR_DSN": "postgresql://test"}):
            result = service.reindex()

        service._knowledge_repository.insert_chunks.assert_called_once()
        call_kwargs = service._knowledge_repository.insert_chunks.call_args
        args = call_kwargs[0]
        kwargs = call_kwargs[1]
        self.assertEqual(29, args[1][0])  # document_ids
        self.assertEqual(1, len(args[2]))  # records length
        vector_fn = kwargs["vector_literal_fn"]
        self.assertEqual("[0.10000000,0.20000000]", vector_fn([0.1, 0.2]))
        self.assertEqual({"ok": True, "documents": 1, "chunks": 1}, result)

    def test_reindex_source_query_only_reads_published_documents(self) -> None:
        service = KnowledgeAdminService(retriever=Mock())
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        with patch("psycopg.connect", return_value=mock_conn):
            result = service._knowledge_repository.list_active_documents("postgresql://test")

        self.assertEqual([], result)
        source_sql = str(mock_cursor.execute.call_args.args[0])
        self.assertIn("review_status = 'PUBLISHED'", source_sql)

    def test_reindex_rejects_incomplete_embedding_batch_before_database_write(self) -> None:
        retriever = Mock()
        retriever.embed_many.return_value = []
        service = KnowledgeAdminService(retriever=retriever)
        service._knowledge_repository.list_active_documents = Mock(return_value=[ActiveDocumentRow(
            document_id=29,
            document_type="guideline",
            title="售后自动转人工边界",
            text="图片无法核验问题现象时转人工。",
            metadata={},
            revision=1,
            updated_at="2026-07-22T10:00:00",
            product_categories=None,
            scenes=["human_handoff"],
            intents=["guardrail"],
        )])
        connect = MagicMock()

        with patch.dict(os.environ, {"PGVECTOR_DSN": "postgresql://test"}), patch(
            "psycopg.connect", connect
        ):
            with self.assertRaisesRegex(RuntimeError, "EMBEDDING_COUNT_MISMATCH"):
                service.reindex()

        connect.assert_not_called()

    def test_reindex_aborts_when_published_source_changes_before_write_lock(self) -> None:
        retriever = Mock()
        retriever.embed_many.return_value = [[0.1, 0.2]]
        service = KnowledgeAdminService(retriever=retriever)
        service._knowledge_repository.list_active_documents = Mock(return_value=[ActiveDocumentRow(
            document_id=29,
            document_type="guideline",
            title="售后自动转人工边界",
            text="旧的已发布内容",
            metadata={},
            revision=1,
            updated_at=datetime(2026, 7, 22, 10, 0),
            product_categories=None,
            scenes=["human_handoff"],
            intents=["guardrail"],
        )])
        service._knowledge_repository.lock_and_delete_chunks = Mock(
            return_value={}  # empty: source changed, lock didn't match
        )
        service._knowledge_repository.insert_chunks = Mock()
        service._knowledge_repository.set_published_revision = Mock()

        with patch.dict(os.environ, {"PGVECTOR_DSN": "postgresql://test"}):
            with self.assertRaisesRegex(RuntimeError, "REINDEX_SOURCE_CHANGED"):
                service.reindex()

        service._knowledge_repository.insert_chunks.assert_not_called()
        service._knowledge_repository.set_published_revision.assert_not_called()


if __name__ == "__main__":
    unittest.main()

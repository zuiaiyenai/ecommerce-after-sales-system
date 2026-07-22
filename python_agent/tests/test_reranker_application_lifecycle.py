from __future__ import annotations

from unittest.mock import patch

from after_sales_agent.api import http_server


def test_application_shutdown_explicitly_closes_shared_clients_once() -> None:
    with patch.object(http_server.LLM_CLIENTS, "close") as close_llm, patch.object(
        http_server.RERANKER_CLIENTS, "close"
    ) as close_reranker:
        http_server.close_application_resources()

    close_llm.assert_called_once_with()
    close_reranker.assert_called_once_with()

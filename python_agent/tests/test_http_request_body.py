from __future__ import annotations

from io import BytesIO
import unittest
from unittest.mock import patch

from after_sales_agent.api import http_server
from after_sales_agent.application.knowledge_ingestion_service import KnowledgeParseError
from after_sales_agent.api.http_server import AgentApiHandler, RequestBodyReadError, read_http_request_body


class HttpRequestBodyTest(unittest.TestCase):
    def test_reads_content_length_request_body(self) -> None:
        payload = b'{"chunks":["refund policy"]}'

        body = read_http_request_body(
            {"Content-Length": str(len(payload))},
            BytesIO(payload),
            max_bytes=1024,
        )

        self.assertEqual(payload, body)

    def test_reads_chunked_request_body_used_by_spring_rest_template(self) -> None:
        raw = b'7\r\n{"chunk\r\nA\r\ns":["text"\r\n2\r\n]}\r\n0\r\n\r\n'

        body = read_http_request_body(
            {"Transfer-Encoding": "chunked"},
            BytesIO(raw),
            max_bytes=1024,
        )

        self.assertEqual(b'{"chunks":["text"]}', body)

    def test_rejects_chunked_body_over_the_request_limit(self) -> None:
        raw = b'5\r\n12345\r\n0\r\n\r\n'

        with self.assertRaises(RequestBodyReadError) as context:
            read_http_request_body(
                {"Transfer-Encoding": "chunked"},
                BytesIO(raw),
                max_bytes=4,
            )

        self.assertEqual("request_too_large", context.exception.error)
        self.assertEqual(413, context.exception.status)

    def test_knowledge_parse_route_returns_parse_payload(self) -> None:
        handler, sent = self._knowledge_parse_handler()
        service = unittest.mock.Mock()
        service.parse_document.return_value = {"content": "refund", "chunks": []}

        with patch.object(http_server, "KNOWLEDGE_ADMIN_SERVICE", service), patch.object(
            http_server, "read_http_request_body", return_value=b"{}"
        ):
            handler.do_POST()

        self.assertEqual([({"content": "refund", "chunks": []}, 200)], sent)

    def test_knowledge_parse_route_maps_stable_errors_without_internal_message(self) -> None:
        expected_statuses = {
            "UNSUPPORTED_FILE_TYPE": 415,
            "PDF_ENCRYPTED": 422,
            "PDF_TEXT_LAYER_MISSING": 422,
            "FILE_DECODE_FAILED": 422,
        }
        for error, status in expected_statuses.items():
            with self.subTest(error=error):
                handler, sent = self._knowledge_parse_handler()
                service = unittest.mock.Mock()
                service.parse_document.side_effect = KnowledgeParseError(error)

                with patch.object(http_server, "KNOWLEDGE_ADMIN_SERVICE", service), patch.object(
                    http_server, "read_http_request_body", return_value=b"{}"
                ):
                    handler.do_POST()

                self.assertEqual([({"error": error}, status)], sent)

    @staticmethod
    def _knowledge_parse_handler() -> tuple[AgentApiHandler, list[tuple[dict[str, object], int]]]:
        handler = object.__new__(AgentApiHandler)
        sent: list[tuple[dict[str, object], int]] = []
        handler.path = "/api/knowledge/parse"
        handler.headers = {}
        handler.rfile = BytesIO()
        handler._ensure_internal_authorized = lambda: True
        handler._send_json = lambda payload, status=200: sent.append((payload, status))
        return handler, sent


if __name__ == "__main__":
    unittest.main()

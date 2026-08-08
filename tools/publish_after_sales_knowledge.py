"""Publish the versioned demo after-sales knowledge catalog through Java APIs.

Validation is the default. Pass --apply to update/create documents in bounded
batches, curate draft filter metadata, publish revisions, and finally disable
superseded documents.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = (
    REPO_ROOT
    / "src"
    / "main"
    / "resources"
    / "agent-knowledge-base"
    / "after-sales-knowledge-v2.json"
)
TERMINAL_FAILURES = {
    "PARSE_FAILED",
    "CLASSIFY_FAILED",
    "EMBEDDING_FAILED",
}


class ApiError(RuntimeError):
    pass


@dataclass
class ApiClient:
    base_url: str
    token: str = ""

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ApiError(f"{method} {path} failed: {exc}") from exc
        if not isinstance(payload, dict) or int(payload.get("code") or 0) != 200:
            raise ApiError(f"{method} {path} returned an application error: {payload}")
        return payload.get("data")

    def login(self, account: str, password: str) -> None:
        data = self.request(
            "POST",
            "/admin/auth/login",
            {"account": account, "password": password},
        )
        token = str((data or {}).get("token") or "").strip()
        if not token:
            raise ApiError("Admin login returned no token")
        self.token = token


def load_catalog(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    documents = payload.get("documents")
    disabled = payload.get("disabled_source_codes")
    if not isinstance(documents, list) or not documents:
        raise ValueError("documents must be a non-empty array")
    if not isinstance(disabled, list):
        raise ValueError("disabled_source_codes must be an array")
    required = {
        "source_type",
        "source_code",
        "title",
        "scene",
        "intent",
        "tags",
        "content",
    }
    seen: set[str] = set()
    for index, document in enumerate(documents):
        if not isinstance(document, dict):
            raise ValueError(f"documents[{index}] must be an object")
        missing = sorted(required - set(document))
        if missing:
            raise ValueError(f"documents[{index}] is missing {missing}")
        code = str(document["source_code"]).strip()
        if not code or code in seen:
            raise ValueError(f"duplicate or empty source_code: {code!r}")
        seen.add(code)
        if not str(document["content"]).strip():
            raise ValueError(f"{code} has empty content")
        if not isinstance(document["tags"], list) or not document["tags"]:
            raise ValueError(f"{code} must have tags")
    overlap = seen.intersection(str(item) for item in disabled)
    if overlap:
        raise ValueError(f"active and disabled source codes overlap: {sorted(overlap)}")
    return payload


def list_documents(client: ApiClient) -> list[dict[str, Any]]:
    data = client.request("GET", "/admin/knowledge/list?page=1&pageSize=200")
    return [dict(item) for item in (data or []) if isinstance(item, dict)]


def wait_for_status(
    client: ApiClient,
    document_id: str,
    expected: set[str],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        data = client.request("GET", f"/admin/knowledge/{document_id}/ingestion-status")
        last = dict(data or {})
        status = str(last.get("reviewStatus") or "")
        if status in expected:
            return last
        if status in TERMINAL_FAILURES:
            raise ApiError(
                f"document {document_id} entered {status}: "
                f"{last.get('errorCode') or ''} {last.get('errorMessage') or ''}".strip()
            )
        time.sleep(0.5)
    raise ApiError(
        f"document {document_id} did not reach {sorted(expected)}; last status={last}"
    )


def desired_update_payload(
    catalog: dict[str, Any],
    document: dict[str, Any],
) -> dict[str, Any]:
    category = document.get("product_category")
    return {
        "title": document["title"],
        "merchantCode": catalog["merchant_code"],
        "status": 1,
        "content": document["content"],
        "productCategory": category if category is not None else "",
        "scene": document["scene"],
        "intent": document["intent"],
        "policyVersion": catalog["policy_version"],
        "tags": document["tags"],
        "metadata": {
            "knowledgeBaseVersion": catalog["knowledge_base_version"],
            "contentLanguage": "zh-CN",
            "managedBy": "versioned-knowledge-catalog",
        },
    }


def desired_create_payload(
    catalog: dict[str, Any],
    document: dict[str, Any],
) -> dict[str, Any]:
    return {
        "title": document["title"],
        "knowledgeType": document["source_type"],
        "sourceCode": document["source_code"],
        "scope": "MERCHANT",
        "merchantCode": catalog["merchant_code"],
        "status": "ENABLED",
        "content": document["content"],
        "productCategory": document.get("product_category") or "",
        "scene": document["scene"],
        "intent": document["intent"],
        "policyVersion": catalog["policy_version"],
        "tags": document["tags"],
        "metadata": {
            "knowledgeBaseVersion": catalog["knowledge_base_version"],
            "contentLanguage": "zh-CN",
            "managedBy": "versioned-knowledge-catalog",
        },
    }


def is_current(
    existing: dict[str, Any],
    catalog: dict[str, Any],
    document: dict[str, Any],
) -> bool:
    metadata = existing.get("metadata")
    return (
        str(existing.get("reviewStatus") or "") == "PUBLISHED"
        and int(existing.get("status") or 0) == 1
        and str(existing.get("title") or "") == document["title"]
        and str(existing.get("content") or "") == document["content"]
        and str((metadata or {}).get("knowledgeBaseVersion") or "")
        == catalog["knowledge_base_version"]
    )


def submit_document(
    client: ApiClient,
    catalog: dict[str, Any],
    document: dict[str, Any],
    existing: dict[str, Any] | None,
) -> str | None:
    if existing is not None and is_current(existing, catalog, document):
        return None
    if existing is None:
        data = client.request(
            "POST",
            "/admin/knowledge/text-import",
            desired_create_payload(catalog, document),
        )
        return str((data or {}).get("documentId") or "")
    document_id = str(existing["id"])
    client.request(
        "PUT",
        f"/admin/knowledge/{document_id}",
        desired_update_payload(catalog, document),
    )
    return document_id


def curate_and_publish(
    client: ApiClient,
    catalog: dict[str, Any],
    document_id: str,
    document: dict[str, Any],
    *,
    timeout_seconds: float,
) -> None:
    status = wait_for_status(
        client,
        document_id,
        {"REVIEW_REQUIRED"},
        timeout_seconds=timeout_seconds,
    )
    revision = int(status["revision"])
    chunks = client.request("GET", f"/admin/knowledge/{document_id}/draft") or []
    if not chunks:
        raise ApiError(f"document {document_id} has no draft chunks")
    categories = (
        [document["product_category"]]
        if document.get("product_category")
        else []
    )
    for chunk in chunks:
        data = client.request(
            "PUT",
            f"/admin/knowledge/{document_id}/draft/chunks/{chunk['chunkId']}",
            {
                "expectedRevision": revision,
                "productCategories": categories,
                "scenes": [document["scene"]],
                "intents": [document["intent"]],
            },
        )
        revision = int((data or {})["revision"])
    if document["source_type"] in {
        "after_sales_policy",
        "refund_policy",
        "exchange_rule",
    }:
        data = client.request(
            "PUT",
            f"/admin/knowledge/{document_id}/draft",
            {
                "expectedRevision": revision,
                "policyVersion": catalog["policy_version"],
                "validFrom": catalog["valid_from"],
                "validTo": catalog["valid_to"],
            },
        )
        revision = int((data or {})["revision"])
    client.request(
        "POST",
        f"/admin/knowledge/{document_id}/publish",
        {"expectedRevision": revision},
    )
    wait_for_status(
        client,
        document_id,
        {"PUBLISHED"},
        timeout_seconds=timeout_seconds,
    )


def disable_superseded(
    client: ApiClient,
    documents_by_code: dict[str, dict[str, Any]],
    source_codes: list[str],
) -> int:
    disabled = 0
    for source_code in source_codes:
        existing = documents_by_code.get(source_code)
        if existing is None or int(existing.get("status") or 0) == 0:
            continue
        client.request(
            "PUT",
            f"/admin/knowledge/{existing['id']}",
            {
                "status": 0,
                "metadata": {
                    "supersededByKnowledgeBaseVersion": "2026-07-28-demo-v2",
                    "supersededReason": "merged-into-structured-category-or-evidence-knowledge",
                },
            },
        )
        disabled += 1
    return disabled


def chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/api")
    parser.add_argument("--account", default=os.getenv("KNOWLEDGE_ADMIN_ACCOUNT", "admin_demo"))
    parser.add_argument("--password", default=os.getenv("KNOWLEDGE_ADMIN_PASSWORD", "123456"))
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    catalog = load_catalog(args.catalog.resolve())
    print(
        json.dumps(
            {
                "catalog": str(args.catalog),
                "knowledge_base_version": catalog["knowledge_base_version"],
                "documents": len(catalog["documents"]),
                "disabled_source_codes": len(catalog["disabled_source_codes"]),
                "apply": args.apply,
            },
            ensure_ascii=False,
        )
    )
    if not args.apply:
        return

    client = ApiClient(args.base_url)
    client.login(args.account, args.password)
    current = list_documents(client)
    by_code = {str(item.get("sourceCode") or ""): item for item in current}
    desired = [
        (document, by_code.get(str(document["source_code"])))
        for document in catalog["documents"]
    ]
    pending = [
        (document, existing)
        for document, existing in desired
        if existing is None or not is_current(existing, catalog, document)
    ]
    published = 0
    for batch_number, batch in enumerate(
        chunks(pending, max(1, min(args.batch_size, 8))),
        start=1,
    ):
        submitted: list[tuple[str, dict[str, Any]]] = []
        for document, existing in batch:
            document_id = submit_document(
                client,
                catalog,
                document,
                existing,
            )
            if document_id:
                submitted.append((document_id, document))
        for document_id, document in submitted:
            curate_and_publish(
                client,
                catalog,
                document_id,
                document,
                timeout_seconds=args.timeout_seconds,
            )
            published += 1
        print(
            json.dumps(
                {
                    "batch": batch_number,
                    "submitted": len(submitted),
                    "published_total": published,
                },
                ensure_ascii=False,
            )
        )

    refreshed = list_documents(client)
    refreshed_by_code = {
        str(item.get("sourceCode") or ""): item for item in refreshed
    }
    disabled = disable_superseded(
        client,
        refreshed_by_code,
        [str(item) for item in catalog["disabled_source_codes"]],
    )
    print(
        json.dumps(
            {
                "ok": True,
                "published": published,
                "already_current": len(catalog["documents"]) - len(pending),
                "disabled": disabled,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

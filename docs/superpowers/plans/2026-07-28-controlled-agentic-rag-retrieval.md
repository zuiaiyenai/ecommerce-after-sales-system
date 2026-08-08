# Controlled Agentic RAG Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one bounded, observation-driven follow-up RAG retrieval without changing business APIs or state transitions.

**Architecture:** A pure `RagRetrievalPolicy` evaluates structured retrieval results and builds a focused follow-up query. The existing LangGraph workflow records retrieval lifecycle state, invokes the policy before its existing guarded business flow, preserves all metadata filters, and selects the most reliable successful result.

**Tech Stack:** Python 3.11+, LangGraph, `unittest`/pytest, existing pgvector/RRF/reranker stack.

## Global Constraints

- Modify only Python RAG orchestration, RAG tests, example configuration, and Python Agent documentation.
- Keep Java, frontend, database schema, tool schemas, image review, review submission, and handoff behavior unchanged.
- Default total RAG attempts is exactly `2`; never repeat a normalized query.
- Follow-up retrieval may change only `query`; all metadata filters must remain byte-for-byte equivalent.
- Infrastructure failures are not query-rewrite candidates.
- No new external dependency.
- If service startup fails, record the first failure and do not loop on restarts.

---

### Task 1: Pure retrieval assessment policy

**Files:**
- Create: `python_agent/after_sales_agent/application/rag_retrieval_policy.py`
- Create: `python_agent/tests/test_rag_retrieval_policy.py`

**Interfaces:**
- Consumes: structured dictionaries returned by `retrieve_knowledge`.
- Produces: `RetrievalAssessment`, `RagRetrievalPolicy.assess(...)`, and `RagRetrievalPolicy.follow_up_query(...)`.

- [ ] **Step 1: Write failing policy tests**

```python
def test_empty_semantic_result_requests_one_follow_up():
    assessment = RagRetrievalPolicy(max_attempts=2).assess(
        result={"mode": "hybrid_reranked", "hits": [], "no_answer": True},
        attempts=1,
        trusted_policy_found=False,
        require_trusted_policy=False,
    )
    assert assessment.should_retry
    assert "empty_hits" in assessment.reasons

def test_infrastructure_failure_never_requests_query_rewrite():
    assessment = RagRetrievalPolicy(max_attempts=2).assess(
        result={"mode": "pgvector_error", "hits": [], "no_answer": True},
        attempts=1,
        trusted_policy_found=False,
        require_trusted_policy=False,
    )
    assert not assessment.should_retry

def test_follow_up_query_is_focused_and_not_duplicate():
    policy = RagRetrievalPolicy(max_attempts=2)
    query = policy.follow_up_query(
        original_query="耳机声音异常 售后",
        require_trusted_policy=True,
        previous_queries=["耳机声音异常 售后"],
    )
    assert query
    assert query != "耳机声音异常 售后"
    assert "适用条件" in query
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
$env:PYTHONPATH='python_agent'
python -m pytest python_agent/tests/test_rag_retrieval_policy.py -q
```

Expected: FAIL because `rag_retrieval_policy` does not exist.

- [ ] **Step 3: Implement the minimal pure policy**

```python
@dataclass(frozen=True)
class RetrievalAssessment:
    sufficient: bool
    should_retry: bool
    reasons: tuple[str, ...]

@dataclass(frozen=True)
class RagRetrievalPolicy:
    max_attempts: int = 2

    def assess(self, *, result, attempts, trusted_policy_found, require_trusted_policy):
        mode = str(result.get("mode") or "")
        if self._is_infrastructure_failure(mode, result.get("failure_reason")):
            return RetrievalAssessment(False, False, ("infrastructure_failure",))
        reasons = []
        if result.get("no_answer") is True or not result.get("hits"):
            reasons.append("empty_hits")
        if require_trusted_policy and not trusted_policy_found:
            reasons.append("trusted_policy_missing")
        sufficient = not reasons
        return RetrievalAssessment(
            sufficient,
            bool(reasons) and attempts < self.max_attempts,
            tuple(reasons),
        )
```

`follow_up_query` appends a generic consultation or policy focus phrase, normalizes whitespace for duplicate comparison, and returns `None` if the resulting query has already been used.

- [ ] **Step 4: Run policy tests and verify GREEN**

Run the Task 1 command. Expected: all tests pass.

### Task 2: Integrate bounded follow-up retrieval into LangGraph

**Files:**
- Modify: `python_agent/after_sales_agent/application/after_sales_workflow.py`
- Modify: `python_agent/tests/test_after_sales_workflow.py`

**Interfaces:**
- Consumes: `RagRetrievalPolicy`.
- Produces: state fields `retrieval_attempts`, `retrieval_queries`, `retrieval_assessment`; helper methods `_follow_up_retrieval_action` and `_best_knowledge_result`.

- [ ] **Step 1: Write failing workflow tests**

Add a recording tool fake that returns configured retrieval results and captures argument dictionaries. Cover:

```python
def test_empty_knowledge_result_retries_once_preserving_filters():
    # First result has empty hits; second has one usable hit.
    result = agent.handle(ticket_payload)
    calls = tools.knowledge_arguments
    assert len(calls) == 2
    assert calls[0]["query"] != calls[1]["query"]
    for key in ("merchant_code", "product_category", "scene", "intent",
                "source_type", "policy_version", "as_of_time", "top_k"):
        assert calls[1].get(key) == calls[0].get(key)

def test_infrastructure_failure_does_not_rewrite_query():
    # pgvector_error result proceeds to the existing manual-review path.
    assert len(tools.knowledge_arguments) == 1

def test_best_knowledge_result_keeps_stronger_first_attempt():
    best = agent._best_knowledge_result(state, order)
    assert best["hits"][0]["source_code"] == "POLICY-STRONG"
```

- [ ] **Step 2: Run the three new tests and verify RED**

Run each test by node ID. Expected failures: only one retrieval occurs and `_best_knowledge_result` is absent.

- [ ] **Step 3: Add retrieval lifecycle state**

Initialize in `_handle_core`:

```python
"retrieval_attempts": 0,
"retrieval_queries": [],
"retrieval_assessment": {},
```

In `observe_tool_result`, when `tool == "retrieve_knowledge"`, increment the attempt count, append the executed normalized query once, and store a serializable assessment summary.

- [ ] **Step 4: Route one follow-up before the existing guarded flow**

In `decide_next`, after tool-failure handling and before `_guarded_after_sales_action`, call:

```python
follow_up = self._follow_up_retrieval_action(state)
if follow_up is not None:
    self._apply_action(state, follow_up)
    return state
```

The action copies the previous `retrieve_knowledge` arguments, replaces only `query`, and preserves trusted identifiers injected by `_apply_action`.

- [ ] **Step 5: Select the best successful result**

Implement a deterministic score tuple:

```python
(
    int(bool(trusted_hits)),
    int(result.get("reranker_succeeded") is True),
    int(result.get("no_answer") is not True),
    len(result.get("hits") or []),
    index,
)
```

Replace RAG consumer lookups in evidence guidance, review construction, skill selection, and policy summary paths with `_best_knowledge_result` while leaving generic `_latest_tool_data` behavior unchanged for other tools.

- [ ] **Step 6: Run new tests, then full workflow tests**

```powershell
$env:PYTHONPATH='python_agent'
python -m pytest python_agent/tests/test_after_sales_workflow.py -q
```

Expected: all workflow tests pass.

### Task 3: Configuration, documentation, and regression verification

**Files:**
- Modify: `python_agent/.env.example`
- Modify: `python_agent/README.md`

**Interfaces:**
- Produces: documented `MAX_RAG_RETRIEVAL_ATTEMPTS=2`.

- [ ] **Step 1: Document the bounded setting**

Add `MAX_RAG_RETRIEVAL_ATTEMPTS=2` beside other Agent limits and explain that it counts the initial retrieval plus one semantic follow-up. State that infrastructure failures do not trigger query rewriting.

- [ ] **Step 2: Run focused RAG regression**

```powershell
$env:PYTHONPATH='python_agent'
python -m pytest python_agent/tests/test_rag_retrieval_policy.py python_agent/tests/test_after_sales_workflow.py python_agent/tests/test_pgvector_retriever.py python_agent/tests/test_rrf.py python_agent/tests/test_reranker_client.py -q
```

Expected: zero failures.

- [ ] **Step 3: Run Python Agent regression**

```powershell
$env:PYTHONPATH='python_agent'
python -m pytest python_agent/tests -m "not real_llm" -q
python -m compileall -q python_agent/after_sales_agent
```

Expected: zero failures and compile exit code `0`.

- [ ] **Step 4: Inspect scope and whitespace**

```powershell
git diff --check
git status --short
```

Confirm only the planned RAG files and pre-existing user changes are present. Do not stage or alter unrelated files.

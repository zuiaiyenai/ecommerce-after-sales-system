# Native Function Calling Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Python Agent decisions to provider-native Function Calling while preserving the existing LangGraph workflow, Java tool contracts, deterministic safety gates, and a configurable legacy JSON fallback.

**Architecture:** Add a small provider-protocol adapter that converts registry schemas to OpenAI-compatible functions, validates exactly one returned tool call, and normalizes it to the workflow's existing action dictionary. LangGraph keeps its current deterministic routing and tool execution nodes; it only replaces direct `chat_json()` decisions with the adapter and stores the assistant tool-call envelope plus matching `role=tool` observation for subsequent decisions.

**Tech Stack:** Python 3.11+, dataclasses/typing/json, existing OpenAI-compatible and Ollama HTTP clients, LangGraph, unittest/pytest.

## Global Constraints

- Native `tools` / `tool_calls` / `tool_call_id` / `role=tool` is the default path.
- `LLM_NATIVE_FUNCTION_CALLING_ENABLED=true` controls the native path.
- `LLM_LEGACY_TOOL_CALL_FALLBACK_ENABLED=true` allows one legacy `chat_json()` fallback per decision.
- Do not change Java Tool API paths, DTOs, permissions, transactions, idempotency, or status ownership.
- Process at most one tool call per model response; never execute malformed or additional calls.
- Model-visible schemas must not let the model control trusted identity and business IDs when Graph State already owns them.
- Preserve all deterministic workflow gates, retry limits, duplicate-call limits, manual handoff behavior, and final reply sanitization.
- `final_reply` is model-visible but is not executable through `AgentToolRegistry`.
- Do not add LangChain `bind_tools`, `ToolNode`, parallel tool execution, or a new dependency.

---

### Task 1: Function Calling Protocol Adapter And Complete Schemas

**Files:**
- Create: `python_agent/after_sales_agent/application/function_calling.py`
- Modify: `python_agent/after_sales_agent/application/tool_registry.py`
- Create: `python_agent/tests/test_function_calling.py`
- Create: `python_agent/tests/test_tool_registry.py`

**Interfaces:**
- Consumes: `OpenAICompatibleClient.chat(messages, tools=..., tool_choice="required", ...)` and `AgentToolRegistry.tool_specs()`.
- Produces: `FunctionCallingAdapter.decide(*, system_prompt: str, payload: dict[str, Any], prior_messages: list[dict[str, Any]]) -> NativeDecision`.
- Produces: `NativeDecision.action`, `NativeDecision.assistant_message`, and `FunctionCallingProtocolError` without executing a tool.
- Produces: complete registry `input_schema` objects that remain compatible with existing internal `AgentToolRegistry.call()` arguments.

- [ ] **Step 1: Write failing adapter protocol tests**

Add tests with a recording fake client for: standard single `tool_calls` parsing; JSON-string arguments becoming a dictionary; `final_reply` and `handoff_to_human` normalization; missing calls, multiple calls, unknown names, malformed JSON, and non-object arguments raising `FunctionCallingProtocolError`; exact forwarding of `tools`, `tool_choice="required"`, temperature, token limit, and prior assistant/tool messages.

```python
response = {
    "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
        "id": "call-1", "type": "function",
        "function": {"name": "search_user_orders", "arguments": "{\"keyword\":\"A100\"}"},
    }]}}]
}
decision = adapter.decide(system_prompt="system", payload={"user": {}}, prior_messages=[])
assert decision.action == {
    "action": "tool_call", "tool_name": "search_user_orders",
    "tool_arguments": {"keyword": "A100"}, "tool_call_id": "call-1",
}
assert decision.assistant_message == response["choices"][0]["message"]
```

- [ ] **Step 2: Run adapter tests and verify RED**

Run: `cd python_agent; python -m pytest tests/test_function_calling.py -q`

Expected: FAIL because `after_sales_agent.application.function_calling` does not exist.

- [ ] **Step 3: Write failing registry schema tests**

Assert every executable tool has `{type: object, properties: ..., required: [...], additionalProperties: false}`, required names exist in `properties`, identity fields such as `user_id` are absent from model-visible required/properties, and specific business fields have stable primitive/array/object types. Assert `final_reply` is supplied by the adapter as a control function and is absent from `registry()`.

- [ ] **Step 4: Run registry tests and verify RED**

Run: `cd python_agent; python -m pytest tests/test_tool_registry.py -q`

Expected: FAIL because current tool schemas contain incomplete properties and allow additional properties.

- [ ] **Step 5: Implement schemas and adapter minimally**

Use frozen dataclasses and strict parsing. Build provider tools from registry specs plus these control schemas:

```python
@dataclass(frozen=True)
class NativeDecision:
    action: dict[str, Any]
    assistant_message: dict[str, Any]

class FunctionCallingProtocolError(ValueError):
    pass
```

The adapter must call `client.chat()` only, accept exactly one tool call, validate `id`, `type=function`, registered name, and object arguments, and return existing workflow action keys. `final_reply` requires `assistant_reply`, accepts `need_human` and `evidence_needed`; `handoff_to_human` maps to `action=human_handoff`. It must never call `AgentToolRegistry.call()`.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `cd python_agent; python -m pytest tests/test_function_calling.py tests/test_tool_registry.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```powershell
git add -- python_agent/after_sales_agent/application/function_calling.py python_agent/after_sales_agent/application/tool_registry.py python_agent/tests/test_function_calling.py python_agent/tests/test_tool_registry.py
git commit -m "feat: add native function calling adapter"
```

### Task 2: LangGraph Native Decision Loop And Tool Result Correlation

**Files:**
- Modify: `python_agent/after_sales_agent/application/after_sales_workflow.py`
- Modify: `python_agent/tests/test_after_sales_workflow.py`

**Interfaces:**
- Consumes: Task 1 `FunctionCallingAdapter` and `NativeDecision`.
- Produces: Graph State fields `pending_tool_call_id`, `pending_assistant_tool_call`, and `function_messages`.
- Preserves: existing `_apply_action()`, trusted-state ID overwrites, `tool_call -> observe_tool_result -> decide_next`, Java execution, deterministic review rules, and response `tool_trace` contract.

- [ ] **Step 1: Write failing native workflow tests**

Add a fake LLM exposing both `chat()` and `chat_json()`. Cover: planner uses native calls by default; tool arguments cannot override trusted `user_id`, `session_id`, `order_id`, `ticket_id`, or `review_request_id`; tool trace stores the matching call ID; decider sends the original assistant tool-call message immediately followed by a compressed `role=tool` message with the same `tool_call_id`; only the first decision executes; native `final_reply` completes without registry execution; native `handoff_to_human` still routes through the existing handoff node.

```python
assert llm.chat_requests[1]["messages"][-2]["tool_calls"][0]["id"] == "call-1"
assert llm.chat_requests[1]["messages"][-1]["role"] == "tool"
assert llm.chat_requests[1]["messages"][-1]["tool_call_id"] == "call-1"
assert json.loads(llm.chat_requests[1]["messages"][-1]["content"])["ok"] is True
```

- [ ] **Step 2: Run native workflow tests and verify RED**

Run: `cd python_agent; python -m pytest tests/test_after_sales_workflow.py -k "native_function or tool_call_id" -q`

Expected: FAIL because workflow decisions still call `chat_json()` and do not preserve native protocol messages.

- [ ] **Step 3: Integrate adapter into Planner and Decider**

Initialize Graph State protocol fields to empty values. Add one workflow helper that calls the adapter and then `_apply_action`; use it from both `classify_or_plan` and the LLM branch of `decide_next`. Keep deterministic pre-model branches unchanged. Store the assistant envelope only after successful validation, attach its call ID to the executed trace item, and append a compressed observation message after `observe_tool_result`:

```python
{
    "role": "tool",
    "tool_call_id": call_id,
    "name": tool_name,
    "content": json.dumps(observation, ensure_ascii=False, default=str),
}
```

Clear pending call fields after correlation so later deterministic tool calls cannot reuse an old ID. Do not expose raw Java payloads beyond the existing compressed observation rules.

- [ ] **Step 4: Preserve trusted-state and safety gates**

Ensure `_apply_action()` continues to overwrite model-provided identifiers from Graph State and does not accept a model attempt to enable AI review submission. Unknown tools and invalid arguments must produce validation failures without bypassing registry checks. Existing no-successful-review, Kafka-source, duplicate-call, max-step, policy-trust, and human-handoff tests must remain unchanged and green.

- [ ] **Step 5: Run workflow tests and verify GREEN**

Run: `cd python_agent; python -m pytest tests/test_after_sales_workflow.py -q`

Expected: PASS, including existing legacy fakes.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- python_agent/after_sales_agent/application/after_sales_workflow.py python_agent/tests/test_after_sales_workflow.py
git commit -m "feat: use native tool calls in langgraph workflow"
```

### Task 3: Configurable Legacy Fallback, Provider Contract, And Regression Verification

**Files:**
- Modify: `python_agent/after_sales_agent/application/function_calling.py`
- Modify: `python_agent/after_sales_agent/application/after_sales_workflow.py`
- Modify: `python_agent/tests/test_function_calling.py`
- Modify: `python_agent/tests/test_after_sales_workflow.py`
- Modify: `python_agent/tests/test_resilient_llm_runtime.py`
- Modify: `python_agent/.env.example`
- Modify: `.env.example`
- Modify: `compose.yml`
- Modify: `python_agent/README.md`

**Interfaces:**
- Consumes: environment booleans `LLM_NATIVE_FUNCTION_CALLING_ENABLED` and `LLM_LEGACY_TOOL_CALL_FALLBACK_ENABLED`.
- Produces: one-decision fallback behavior that returns the existing legacy action shape and records protocol mode for observability without changing public API responses.
- Preserves: provider retry/circuit-breaker behavior and existing `chat_json()` parsing.

- [ ] **Step 1: Write failing fallback and provider payload tests**

Cover native enabled/disabled, fallback enabled/disabled, no tool call, malformed tool call, provider rejection, and exactly one legacy attempt. Assert malformed native output is never executed before fallback validation. Extend HTTP transport tests to assert `tools` and `tool_choice` are serialized for OpenAI-compatible requests and `tools` are serialized for Ollama without altering retries.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd python_agent; python -m pytest tests/test_function_calling.py tests/test_after_sales_workflow.py tests/test_resilient_llm_runtime.py -k "fallback or native_function or tool_choice" -q`

Expected: FAIL because the feature switches and fallback orchestration are not yet implemented.

- [ ] **Step 3: Implement bounded compatibility fallback**

Read booleans with the existing safe environment parsing style. When native is disabled, call legacy directly. When native fails for provider/protocol reasons and fallback is enabled, call `chat_json()` exactly once with the same system prompt and serialized payload. When fallback is disabled or invalid, fail closed into the workflow's existing safe human/final behavior; do not execute any unvalidated action. Emit structured logs containing only protocol mode, tool name, call ID, and error category, never full arguments or tool data.

- [ ] **Step 4: Document and wire defaults**

Add both switches with `true` defaults to root/Agent examples and Compose Agent environment. Document that native is primary, legacy is temporary provider compatibility, and setting fallback to `false` is the later cleanup/strict-mode step. Do not add secrets or change current provider credentials.

- [ ] **Step 5: Run focused and full Python verification**

Run:

```powershell
cd python_agent
python -m pytest tests/test_function_calling.py tests/test_tool_registry.py tests/test_after_sales_workflow.py tests/test_resilient_llm_runtime.py tests/test_real_llm.py -q
python -m pytest -q
python -m compileall after_sales_agent
```

Expected: all local tests pass; real-provider tests may skip when credentials/opt-in are absent; compileall succeeds.

- [ ] **Step 6: Check scope and obsolete decision calls**

Run:

```powershell
rg -n "chat_json\(" python_agent/after_sales_agent/application
git diff --check -- python_agent docs/superpowers/plans/2026-07-23-native-function-calling.md .env.example compose.yml
```

Expected: workflow `chat_json()` remains only inside the explicit legacy fallback path; no whitespace errors.

- [ ] **Step 7: Commit Task 3**

```powershell
git add -- python_agent/after_sales_agent/application/function_calling.py python_agent/after_sales_agent/application/after_sales_workflow.py python_agent/tests/test_function_calling.py python_agent/tests/test_after_sales_workflow.py python_agent/tests/test_resilient_llm_runtime.py python_agent/.env.example .env.example compose.yml python_agent/README.md docs/superpowers/plans/2026-07-23-native-function-calling.md
git commit -m "feat: enable native function calling with fallback"
```

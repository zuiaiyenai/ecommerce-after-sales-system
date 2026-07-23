# Native Function Calling Task 3 Report

## Scope

- Added configurable native Function Calling and one legacy JSON-decision fallback.
- Added HTTP mock contract coverage for OpenAI-compatible and Ollama provider payloads.
- Added deployment defaults in both example environment files and Compose.
- `python_agent/README.md` contains the required documentation increment in the working tree, but was not staged because it had substantial user-owned modifications before this task.

## TDD Evidence

RED command:

```text
python -m pytest tests/test_after_sales_workflow.py tests/test_resilient_llm_runtime.py -k "fallback or native_function_disabled or tool_choice" -q
3 failed, 51 deselected
```

The failures showed missing constructor switches and direct propagation of `FunctionCallingProtocolError`. A second RED test showed native-disabled legacy parse failure propagated instead of failing closed.

GREEN commands:

```text
python -m pytest tests/test_after_sales_workflow.py tests/test_resilient_llm_runtime.py -q
56 passed, 1 warning

python -m pytest tests/test_function_calling.py tests/test_tool_registry.py tests/test_after_sales_workflow.py tests/test_resilient_llm_runtime.py tests/test_real_llm.py -q
70 passed, 4 deselected, 1 warning

python -m compileall after_sales_agent
exit 0
```

## Full Verification

```text
python -m pytest -q
344 passed, 4 skipped, 4 deselected, 2 failed
```

The two failures are outside this task's files and pre-existing repository baseline issues:

- `tests/test_agent_contracts.py::AgentContractTest::test_tool_specs_expose_risk_and_idempotency_metadata` expects `ticket_id` in the `submit_ai_review` schema's required fields.
- `tests/test_offline_safety_evaluator.py::test_repository_agent_safety_dataset_passes_quality_gates` reports pass rate `0.9375`, expected `1.0`.

No provider network request was made. Provider contract tests use `httpx.MockTransport`.

## Files

- `python_agent/after_sales_agent/application/after_sales_workflow.py`
- `python_agent/tests/test_after_sales_workflow.py`
- `python_agent/tests/test_resilient_llm_runtime.py`
- `.env.example`
- `python_agent/.env.example`
- `compose.yml`
- `python_agent/README.md` (working-tree-only, see scope note)

## Self-review

- Native decision errors are limited to expected `LLMError` and `FunctionCallingProtocolError` handling; no broad `BaseException` catch is used.
- Legacy responses are dictionary-validated, cannot retain a fabricated `tool_call_id`, and continue through `_apply_action()` for trusted identifier injection and existing deterministic gates.
- Fail-closed consultation returns a temporary-unavailable reply. Existing tickets route to human handoff without claiming a Java state change before confirmation.
- Logs record only protocol mode and error class, not payloads or provider responses.

## Commit

`feat: enable native function calling with fallback`. The README change is deliberately excluded to avoid committing user-owned documentation changes.

## Concerns

- Full repository pytest remains blocked by the two unrelated baseline failures listed above.
- The existing README dirty state prevents safely isolating its required documentation hunk in this commit without also staging user changes.

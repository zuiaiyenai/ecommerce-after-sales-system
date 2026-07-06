# Python Agent Architecture

## Current Responsibility Split

### `python_agent/after_sales_agent/services/qwen_service.py`
- Main orchestration entry for Qwen-based conversation handling.
- Owns:
  - conversation-understanding call flow
  - rule-agent invocation
  - knowledge retrieval wiring
  - knowledge short-circuit assembly
  - final reply-model invocation
- Does not own low-level parsing or keyword heuristics anymore.

### `python_agent/after_sales_agent/services/qwen_understanding_support.py`
- Conversation-understanding repair helpers.
- Owns:
  - issue normalization fallback
  - logistics / refund-progress keyword guards
  - scene guardrails
  - invalid understanding repair
  - no-understanding request repair

### `python_agent/after_sales_agent/services/qwen_knowledge_support.py`
- Knowledge routing helpers.
- Owns:
  - retrieval query building
  - retrieval source selection
  - prompt-ready knowledge shaping
  - FAQ / policy / product short-circuit candidate selection

### `python_agent/after_sales_agent/services/qwen_reply_support.py`
- Reply parsing and safety cleanup helpers.
- Owns:
  - reply normalization
  - fallback filtering
  - intent / scene / confidence parsing
  - final assistant reply selection

## Agent Layer

### `python_agent/after_sales_agent/agents/return_agent.py`
- Main rule-chain orchestrator.
- Owns only:
  - policy coordination
  - branch selection
  - delegation to result builders / ticket builders

### `python_agent/after_sales_agent/agents/return_decision_support.py`
- AgentResult assembly layer.
- Owns:
  - ask-for-info responses
  - handoff responses
  - status responses
  - special-scene result building

### `python_agent/after_sales_agent/agents/return_ticket_support.py`
- Ticket and after-sales-scheme support layer.
- Owns:
  - ticket creation
  - scheme inference
  - quality-description detail heuristics

### Specialized agents
- `intent_agent.py`: user intent only
- `emotion_agent.py`: emotion label / score / confidence only
- `state_agent.py`: status allowance only
- `evidence_agent.py`: required materials only
- `risk_agent.py`: risk level and auto/manual decision only
- `handoff_agent.py`: transfer-to-human only

## Suggested Next Cleanup

### Phase 2
- Continue shrinking `return_decision_support.py` by separating:
  - `return_status_builders.py`
  - `return_scene_builders.py`
  - `return_handoff_builders.py`

### Phase 3
- Make Spring Boot / DB the single truth source for:
  - FAQ
  - policy
  - scheme mapping
  - scene evidence defaults

### Phase 4
- Remove or archive workspace-level confusion sources:
  - top-level `1/`
  - generated `target/`, `dist/`, `logs/`, `uploads/` from source-focused views

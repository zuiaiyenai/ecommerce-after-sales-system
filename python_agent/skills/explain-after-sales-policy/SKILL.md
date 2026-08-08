---
name: explain-after-sales-policy
description: Explain retrieved after-sales policies with citations, version context, and uncertainty. Use after knowledge retrieval when the Agent must distinguish authoritative pgvector policy evidence from lexical, local, relaxed-filter, missing, or low-score results.
---

# Explain After-Sales Policy

## Workflow

1. State the policy fact supported by each trusted hit and identify its source code or title.
2. Distinguish policy text, verified order facts, customer statements, and Agent suggestions.
3. Prefer the policy version bound to the Java-owned session or order when present.
4. Explain only the clauses relevant to the current decision and evidence request.
5. State uncertainty explicitly when retrieval mode, merchant, version, source type, or score is not authoritative.

## Trust Rules

- Only strict `pgvector` results that pass the runtime policy gate may authorize an automatic decision.
- Lexical fallback, local fallback, relaxed filters, or low-score hits may support a helpful explanation but cannot authorize approval.
- Never turn “no policy hit” into an inferred merchant rule.
- Never override Java ownership, ticket state, transaction, idempotency, or permission checks.

## Output

Give a short customer-facing explanation. Keep citations and uncertainty available in structured audit fields; do not expose internal scores or raw retrieval traces unless explicitly requested by an operator.

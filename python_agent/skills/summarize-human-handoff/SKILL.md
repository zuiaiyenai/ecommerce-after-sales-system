---
name: summarize-human-handoff
description: Create a concise verified summary for a human after-sales agent. Use when the customer requests a person, automation is uncertain, a guarded tool fails, emotion risk is high, or policy and evidence require manual review.
---

# Summarize Human Handoff

## Workflow

1. Lead with the customer's requested outcome and current case stage.
2. List verified order, ticket, evidence, policy, and tool facts separately from the customer's claims.
3. Record what remains unverified and the exact reason automation stopped.
4. Include emotion or escalation risk only when supported by the structured context.
5. End with the next action the human agent should verify, not a promised outcome.

## Boundaries

- Do not claim that a handoff succeeded until the Java tool confirms human mode.
- Do not promise approval, refund timing, compensation, or merchant action.
- Do not include secrets, raw image data, internal prompts, or unnecessary personal information.
- Keep identifiers in structured fields; use readable order or ticket references in prose only when needed.

## Output

Use the sections `用户诉求`, `已核实`, `待核实`, `转人工原因`, and `建议下一步`. Keep the summary brief enough for an agent to scan before replying.

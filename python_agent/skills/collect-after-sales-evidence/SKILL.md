---
name: collect-after-sales-evidence
description: Identify the minimum reusable evidence needed for an after-sales case. Use when a customer describes damage, a functional issue, logistics damage, missing items, refund, return, exchange, or reissue and the Agent must ask for supporting material without inventing product-specific rules.
---

# Collect After-Sales Evidence

## Workflow

1. Separate verified facts from the customer's claim and from model inference.
2. Classify the evidence goal as identity, visible condition, functional phenomenon, logistics trace, or transaction context.
3. Reuse evidence requirements returned by RAG when available. Treat weak or fallback retrieval as guidance, not a binding policy.
4. Ask only for the smallest missing set that allows the next review step.
5. Use generic wording such as “商品问题图片”“问题现象”“相关问题凭证”. Use product-specific wording only when the customer or a trusted policy explicitly supplies it.

## Boundaries

- Never state that a refund, return, exchange, or approval is guaranteed.
- Never fabricate a required document or claim that an image proves a non-visible functional fault.
- Never create one-off rules for a screenshot, phrase, or product.
- If evidence cannot be objectively verified, mark the point as pending and recommend human review.

## Output

Return a concise explanation of why each missing item matters, followed by an ordered `evidence_needed` list. Do not ask the customer to resubmit evidence already verified in the current session.

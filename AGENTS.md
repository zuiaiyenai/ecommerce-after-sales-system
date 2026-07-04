# Agent Notes

## ID Precision Across Java and Mini Program

- Any Java `Long` identifier that can reach JavaScript, uni-app, or WeChat mini program code must be serialized as a string in API responses.
- This includes Snowflake-style IDs such as `sessionId`, `messageId`, `orderId`, `afterSaleId`, `ticketId`, and any nested DTO IDs.
- Do not rely on front-end `String(number)` after JSON parsing. If the backend has already emitted a large numeric JSON value, JavaScript may have lost precision before conversion.
- Request DTOs may still accept `Long` when the client sends ID strings, because Spring/Jackson can bind numeric strings to `Long`.
- When adding or changing API DTOs, check both list/detail/history responses for large IDs and keep the outward-facing JSON contract string-based.

## Cross-Client Conversation Consistency

- User mini program, merchant console, and Python Agent persistence must treat the database conversation history as the source of truth.
- After an AI/chat API call that persists messages, the user mini program should prefer reloading `/chat/history` by `sessionId` over only appending local messages.
- Local message append is acceptable only as a temporary fallback when the persistence result or history reload is unavailable.
- If the backend inserts additional system messages, status-change messages, evaluation invitations, or human-handoff notices, update the session snapshot/last message in the same transaction or persistence flow.
- Do not create separate sessions for the same order/after-sale entry point. Entry from order after-sale detail and entry from consultation session list must resolve to the same backend session and the same message history.
- Hiding/removing a conversation in the UI means "hide from list", not deleting chat messages. A later user message for the same order/after-sale should revive the existing session and keep history.

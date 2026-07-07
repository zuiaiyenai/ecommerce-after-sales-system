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

## After-Sales RAG Troubleshooting

- If Python Agent logs show `knowledge mode = lexical_fallback_after_embedding_error` and `embedding_error = DASHSCOPE_API_KEY or BAILIAN_API_KEY is required`, the knowledge base is not necessarily empty. It usually means the running Python Agent process did not receive the embedding API key.
- For RAG recall failures, check in this order: Python process environment variables, `PGVECTOR_DSN`, PostgreSQL `knowledge_document`/`knowledge_chunk` data, then retriever SQL and keyword fallback.
- The standard path should be DashScope `text-embedding-v3` -> pgvector retrieval with `knowledge mode = pgvector`. `lexical_fallback_after_embedding_error` is only a PostgreSQL knowledge-document fallback when embedding cannot run.
- When restarting Python Agent locally, make sure the same terminal that starts `python_agent/api_server.py` has `DASHSCOPE_API_KEY` and `PGVECTOR_DSN` set.

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any


_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class ReviewCheckpointRuntime:
    """Owns the production checkpointer and its database connection."""

    saver: Any
    connection: Any

    def close(self) -> None:
        self.connection.close()


def build_review_checkpoint_runtime_from_env() -> ReviewCheckpointRuntime:
    """Build a durable saver or fail before Kafka consumption starts.

    Production review execution must never silently fall back to an in-memory
    saver: doing so would acknowledge a suspended review that cannot be resumed
    after a process restart.
    """

    dsn = os.getenv("LANGGRAPH_CHECKPOINT_DSN", "").strip()
    if not dsn:
        raise RuntimeError("LANGGRAPH_CHECKPOINT_DSN is required for review consumer")
    schema = os.getenv("LANGGRAPH_CHECKPOINT_SCHEMA", "agent_runtime").strip()
    if not _SCHEMA_PATTERN.fullmatch(schema):
        raise RuntimeError("LANGGRAPH_CHECKPOINT_SCHEMA is invalid")

    try:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg import sql
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError as exc:
        raise RuntimeError(
            "langgraph-checkpoint-postgres is required for durable review execution"
        ) from exc

    connection = None
    try:
        # PostgresSaver requires autocommit for setup migrations and a dict row
        # factory for checkpoint reads.
        connection = psycopg.connect(
            dsn,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        connection.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
        )
        connection.execute(
            sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
        )
        saver = PostgresSaver(connection)
        saver.setup()
        return ReviewCheckpointRuntime(saver=saver, connection=connection)
    except Exception:
        if connection is not None:
            connection.close()
        raise

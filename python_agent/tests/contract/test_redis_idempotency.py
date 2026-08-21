from __future__ import annotations

import uuid

import pytest

from after_sales_agent.interface.kafka_adapter import RedisEventIdempotencyStore

testcontainers = pytest.importorskip("testcontainers.redis")
RedisContainer = testcontainers.RedisContainer


@pytest.fixture(scope="module")
def redis_url() -> str:
    try:
        with RedisContainer("redis:7.4-alpine") as container:
            host = container.get_container_host_ip()
            port = container.get_exposed_port(6379)
            yield f"redis://{host}:{port}/0"
    except Exception as exc:  # Docker is optional on developer machines.
        pytest.skip(f"Docker/Testcontainers unavailable: {exc}")


@pytest.mark.integration
def test_set_nx_heartbeat_stale_takeover_and_terminal_ack(redis_url: str) -> None:
    event_id = f"phase3-{uuid.uuid4()}"
    owner = RedisEventIdempotencyStore(redis_url, ttl_seconds=60, stale_seconds=30, consumer_id="owner")
    contender = RedisEventIdempotencyStore(redis_url, ttl_seconds=60, stale_seconds=30, consumer_id="contender")
    owner._now = lambda: 1_000.0
    contender._now = lambda: 1_010.0

    first = owner.claim(event_id)
    duplicate = contender.claim(event_id)

    assert first.claimed is True
    assert first.attempt == 1
    assert duplicate.claimed is False
    assert duplicate.status == "PROCESSING"
    assert duplicate.should_ack is False

    owner._now = lambda: 1_020.0
    owner.refresh_processing(event_id)
    contender._now = lambda: 1_040.0
    refreshed = contender.claim(event_id)
    assert refreshed.claimed is False
    assert refreshed.should_ack is False

    contender._now = lambda: 1_051.0
    takeover = contender.claim(event_id)
    assert takeover.claimed is True
    assert takeover.attempt == 2

    contender.mark_completed(event_id)
    terminal = owner.claim(event_id)
    assert terminal.claimed is False
    assert terminal.status == "COMPLETED"
    assert terminal.should_ack is True

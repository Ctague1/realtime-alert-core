"""Metrics endpoint.

Aggregates this process's metrics (ingestion/API) with the processing
worker's metrics, which are exported to Redis by the worker itself.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import get_settings
from ..metrics import get_metrics
from ..redis_client import get_redis

router = APIRouter(tags=["metrics"])


class E2EBatch(BaseModel):
    """End-to-end latency samples measured by a dashboard client (ms)."""

    samples: list[float] = Field(default_factory=list, max_length=5000)


@router.post("/metrics/e2e")
async def report_e2e(payload: E2EBatch) -> dict:
    """Ingest client-side end-to-end latency samples into the histogram.

    The dashboard measures source-timestamp -> client-render latency in the
    browser and reports it here periodically so /metrics exposes real
    end-to-end numbers instead of leaving the histogram empty.
    """
    metrics = get_metrics()
    for sample in payload.samples:
        metrics.observe("e2e_latency_ms", sample)
    return {"accepted": len(payload.samples)}

# Counters/gauges that live in the processing worker process.
_WORKER_COUNTERS = (
    "events_processed",
    "events_acked",
    "duplicates_detected",
    "retries",
    "processing_failures",
    "new_alarms",
    "events_heartbeat",
    "sensor_offline_transitions",
    "sensor_online_transitions",
)
_WORKER_GAUGES = (
    "backlog_depth",
    "stream_length",
    "alarms_active",
    "alarms_acknowledged",
    "alarms_resolved",
    "sensors_offline",
)
_WORKER_LATENCY = ("queue_latency_ms", "process_latency_ms", "total_processing_ms")


@router.get("/metrics")
async def metrics() -> dict:
    local = get_metrics().snapshot()
    worker: dict | None = None
    try:
        raw = await get_redis().get(get_settings().metrics_export_key)
        if raw:
            worker = json.loads(raw)
    except Exception:  # noqa: BLE001
        worker = None

    if worker is None:
        return {**local, "worker_metrics": None}

    worker_snapshot = worker.get("snapshot", worker) if isinstance(worker, dict) else worker
    merged_counters = dict(local["counters"])
    for name in _WORKER_COUNTERS:
        value = worker_snapshot.get("counters", {}).get(name, 0)
        if name in merged_counters:
            merged_counters[name] += value
        else:
            merged_counters[name] = value

    merged_gauges = dict(local["gauges"])
    for name in _WORKER_GAUGES:
        value = worker_snapshot.get("gauges", {}).get(name)
        if value is not None:
            merged_gauges[name] = value

    merged_latency = dict(local["latency_ms"])
    for name in _WORKER_LATENCY:
        value = worker_snapshot.get("latency_ms", {}).get(name)
        if value and value.get("samples"):
            merged_latency[name] = value

    return {
        "started_at": min(local["started_at"], worker_snapshot.get("started_at", local["started_at"])),
        "uptime_seconds": local["uptime_seconds"],
        "counters": merged_counters,
        "gauges": merged_gauges,
        "latency_ms": merged_latency,
        "worker_metrics": {
            "uptime_seconds": worker_snapshot.get("uptime_seconds"),
            "consumer": worker.get("consumer"),
        },
    }
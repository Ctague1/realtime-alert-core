"""In-process metrics.

Lightweight counters, gauges and bounded-memory latency histograms. Exposed
through ``GET /metrics`` as JSON. Percentiles are computed on demand from a
bounded sample window so the hot path only pays for O(1) appends.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from typing import Deque, Dict

_COUNTER_NAMES = (
    "events_received",
    "events_accepted",
    "events_rejected",
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

_GAUGE_NAMES = (
    "backlog_depth",
    "alarms_active",
    "alarms_acknowledged",
    "alarms_resolved",
    "sensors_offline",
    "ws_clients",
)

_HISTOGRAM_NAMES = (
    "ingest_latency_ms",      # redis append - backend receive
    "queue_latency_ms",       # worker start - redis append
    "process_latency_ms",     # db persist - worker start
    "total_processing_ms",    # db persist - backend receive
    "e2e_latency_ms",         # dashboard receive - source ts (reported by frontend)
)

_SAMPLE_WINDOW = 10_000


class Metrics:
    def __init__(self) -> None:
        self._started = time.time()
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = defaultdict(float)
        self._histograms: Dict[str, Deque[float]] = {
            name: deque(maxlen=_SAMPLE_WINDOW) for name in _HISTOGRAM_NAMES
        }

    # ------------------------------------------------------------------ api
    def inc(self, name: str, value: int = 1) -> None:
        self._counters[name] += value

    def gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    def observe(self, name: str, value_ms: float) -> None:
        if value_ms < 0:
            return
        self._histograms[name].append(value_ms)

    # --------------------------------------------------------------- render
    def snapshot(self) -> dict:
        return {
            "started_at": self._started,
            "uptime_seconds": round(time.time() - self._started, 2),
            "counters": {name: self._counters[name] for name in _COUNTER_NAMES},
            "gauges": {name: round(self._gauges[name], 2) for name in _GAUGE_NAMES},
            "latency_ms": {
                name: {
                    "samples": len(samples),
                    "p50": _percentile(samples, 50),
                    "p95": _percentile(samples, 95),
                    "p99": _percentile(samples, 99),
                    "max": max(samples) if samples else None,
                    "avg": round(sum(samples) / len(samples), 3) if samples else None,
                }
                for name, samples in self._histograms.items()
            },
        }


def _percentile(samples: Deque[float], pct: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    idx = min(len(ordered) - 1, int(math.ceil((pct / 100.0) * len(ordered))) - 1)
    return round(ordered[max(idx, 0)], 3)


_metrics: Metrics | None = None


def get_metrics() -> Metrics:
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics


def reset_metrics() -> Metrics:
    """Replace the singleton (used by tests)."""
    global _metrics
    _metrics = Metrics()
    return _metrics
"""Application configuration.

All settings can be overridden through environment variables so the same
codebase runs unchanged under docker-compose, pytest and plain local runs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # --- general -----------------------------------------------------------
    env: str = field(default_factory=lambda: os.getenv("SENTINEL_ENV", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    service_name: str = "sentinel"

    # --- PostgreSQL --------------------------------------------------------
    pg_host: str = field(default_factory=lambda: os.getenv("PGHOST", "localhost"))
    pg_port: int = field(default_factory=lambda: int(os.getenv("PGPORT", "5432")))
    pg_db: str = field(default_factory=lambda: os.getenv("PGDATABASE", "sentinel"))
    pg_user: str = field(default_factory=lambda: os.getenv("PGUSER", "sentinel"))
    pg_password: str = field(default_factory=lambda: os.getenv("PGPASSWORD", "sentinel"))
    pg_pool_min: int = field(default_factory=lambda: int(os.getenv("PG_POOL_MIN", "2")))
    pg_pool_max: int = field(default_factory=lambda: int(os.getenv("PG_POOL_MAX", "16")))

    @property
    def pg_dsn(self) -> str:
        return (
            f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    # --- Redis -------------------------------------------------------------
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # --- Sensor stream (ingestion) ----------------------------------------
    sensor_ws_url: str = field(default_factory=lambda: os.getenv("SENSOR_WS_URL", "ws://localhost:8765"))
    ingestion_enabled: bool = field(
        default_factory=lambda: _env_bool("SENSOR_INGESTION_ENABLED", True)
    )
    sensor_reconnect_base: float = field(
        default_factory=lambda: float(os.getenv("SENSOR_RECONNECT_BASE", "1.0"))
    )
    sensor_reconnect_max: float = field(
        default_factory=lambda: float(os.getenv("SENSOR_RECONNECT_MAX", "30.0"))
    )

    # --- Redis Streams -----------------------------------------------------
    stream_name: str = field(default_factory=lambda: os.getenv("STREAM_NAME", "sensor:events"))
    group_name: str = field(default_factory=lambda: os.getenv("GROUP_NAME", "sentinel-workers"))
    consumer_name: str = field(
        default_factory=lambda: os.getenv("CONSUMER_NAME", "worker-default")
    )
    stream_maxlen: int = field(default_factory=lambda: int(os.getenv("STREAM_MAXLEN", "1000000")))

    # --- Processing worker -------------------------------------------------
    worker_batch_size: int = field(default_factory=lambda: int(os.getenv("WORKER_BATCH_SIZE", "100")))
    worker_block_ms: int = field(default_factory=lambda: int(os.getenv("WORKER_BLOCK_MS", "500")))
    pending_claim_idle_ms: int = field(
        default_factory=lambda: int(os.getenv("PENDING_CLAIM_IDLE_MS", "30000"))
    )
    pending_claim_interval: float = field(
        default_factory=lambda: float(os.getenv("PENDING_CLAIM_INTERVAL", "10.0"))
    )
    # Number of messages to reclaim in one XAUTOCLAIM pass.
    pending_claim_count: int = field(default_factory=lambda: int(os.getenv("PENDING_CLAIM_COUNT", "200")))

    # --- Heartbeat / sensor liveness --------------------------------------
    # Heartbeats are only one signal. ANY event from a sensor refreshes its
    # liveness; the offline timeout is generous so that a single missed
    # heartbeat never marks a sensor offline.
    heartbeat_expected_interval: float = field(
        default_factory=lambda: float(os.getenv("HEARTBEAT_EXPECTED_INTERVAL", "10.0"))
    )
    heartbeat_offline_timeout: float = field(
        default_factory=lambda: float(os.getenv("HEARTBEAT_OFFLINE_TIMEOUT", "30.0"))
    )
    heartbeat_scan_interval: float = field(
        default_factory=lambda: float(os.getenv("HEARTBEAT_SCAN_INTERVAL", "5.0"))
    )

    # --- Dashboard ---------------------------------------------------------
    dashboard_channel: str = field(default_factory=lambda: os.getenv("DASHBOARD_CHANNEL", "sentinel:dashboard"))
    max_dashboard_clients: int = field(default_factory=lambda: int(os.getenv("MAX_DASHBOARD_CLIENTS", "256")))

    # --- Liveness tracking -------------------------------------------------
    liveness_hash: str = field(default_factory=lambda: os.getenv("LIVENESS_HASH", "sensor:liveness"))

    # --- Metrics export ----------------------------------------------------
    metrics_export_key: str = field(
        default_factory=lambda: os.getenv("METRICS_EXPORT_KEY", "sentinel:metrics:worker")
    )
    metrics_export_interval: float = field(
        default_factory=lambda: float(os.getenv("METRICS_EXPORT_INTERVAL", "5.0"))
    )

    # --- Site-state aggregation ---------------------------------------------
    site_recompute_interval: float = field(
        default_factory=lambda: float(os.getenv("SITE_RECOMPUTE_INTERVAL", "5.0"))
    )

    # --- Correlation / pattern detection ------------------------------------
    # The worker scans recent non-escalated alarms for deterministic patterns
    # every `correlation_scan_interval` and escalates the alarms involved.
    correlation_scan_interval: float = field(
        default_factory=lambda: float(os.getenv("CORRELATION_SCAN_INTERVAL", "5.0"))
    )
    # Correlation window: only alarms created within the last N seconds are
    # considered part of a pattern.
    correlation_window: float = field(
        default_factory=lambda: float(os.getenv("CORRELATION_WINDOW", "60.0"))
    )
    # repeat_event: N alarms of the same type from the same sensor within the
    # window -> escalate the involved alarms one severity step.
    correlation_repeat_threshold: int = field(
        default_factory=lambda: int(os.getenv("CORRELATION_REPEAT_THRESHOLD", "3"))
    )
    # multi_signal_site: N distinct alarm types at the same site within the
    # window (at least one high/critical) -> escalate the involved alarms to
    # critical.
    correlation_multi_signal_threshold: int = field(
        default_factory=lambda: int(os.getenv("CORRELATION_MULTI_SIGNAL_THRESHOLD", "3"))
    )
    # critical_burst: N critical alarms at the same site within the window ->
    # recorded as a burst incident (severity stays critical).
    correlation_burst_threshold: int = field(
        default_factory=lambda: int(os.getenv("CORRELATION_BURST_THRESHOLD", "3"))
    )
    # Redis lock so multiple worker replicas never scan concurrently.
    correlation_lock_key: str = field(
        default_factory=lambda: os.getenv("CORRELATION_LOCK_KEY", "sentinel:correlation:lock")
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Rebuild settings (used by tests)."""
    global _settings
    _settings = Settings()
    return _settings
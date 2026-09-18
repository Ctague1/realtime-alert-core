-- ============================================================================
-- Project Sentinel - PostgreSQL schema
-- ============================================================================
-- The database is the authoritative store for all application state:
-- sites, sensors, events and alarms (including acknowledgement and
-- resolution state).
--
-- Idempotency: `events.event_id` is the primary key and
-- `alarms.event_id` carries a UNIQUE constraint. Any attempt to insert the
-- same logical event twice is rejected / resolved by the application layer
-- via INSERT ... ON CONFLICT upserts.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- sites
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sites (
    site_id                 TEXT PRIMARY KEY,
    name                    TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'unknown',
    active_alarm_count      INTEGER NOT NULL DEFAULT 0,
    highest_active_severity TEXT,
    latest_event_ts         TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- sensors
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensors (
    sensor_id           TEXT PRIMARY KEY,
    site_id             TEXT NOT NULL REFERENCES sites(site_id) ON UPDATE CASCADE,
    status              TEXT NOT NULL DEFAULT 'unknown',
    online              BOOLEAN NOT NULL DEFAULT true,
    last_event_ts       TIMESTAMPTZ,
    last_heartbeat_ts   TIMESTAMPTZ,
    latest_event_type   TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sensors_site_id   ON sensors (site_id);
CREATE INDEX IF NOT EXISTS idx_sensors_online    ON sensors (online);

-- ----------------------------------------------------------------------------
-- events
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    sensor_id       TEXT NOT NULL REFERENCES sensors(sensor_id) ON UPDATE CASCADE,
    site_id         TEXT NOT NULL REFERENCES sites(site_id)    ON UPDATE CASCADE,
    type            TEXT NOT NULL,
    severity        TEXT NOT NULL,
    confidence      DOUBLE PRECISION,
    source_ts       TIMESTAMPTZ NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL,
    redis_ts        BIGINT,
    processed_at    TIMESTAMPTZ,
    duplicate       BOOLEAN NOT NULL DEFAULT false,
    raw             JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_site_ts    ON events (site_id, source_ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_sensor_ts  ON events (sensor_id, source_ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_type       ON events (type);
CREATE INDEX IF NOT EXISTS idx_events_processed  ON events (processed_at) WHERE processed_at IS NULL;

-- ----------------------------------------------------------------------------
-- alarms
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alarms (
    alarm_id        BIGSERIAL PRIMARY KEY,
    event_id        TEXT NOT NULL UNIQUE REFERENCES events(event_id) ON DELETE CASCADE,
    sensor_id       TEXT NOT NULL REFERENCES sensors(sensor_id) ON UPDATE CASCADE,
    site_id         TEXT NOT NULL REFERENCES sites(site_id)    ON UPDATE CASCADE,
    type            TEXT NOT NULL,
    severity        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'ACTIVE'
                    CHECK (status IN ('ACTIVE', 'ACKNOWLEDGED', 'RESOLVED')),
    created_at      TIMESTAMPTZ NOT NULL,
    acknowledged_at TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alarms_status_severity ON alarms (status, severity, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alarms_site_status     ON alarms (site_id, status);
CREATE INDEX IF NOT EXISTS idx_alarms_sensor          ON alarms (sensor_id, status);

-- Escalation / correlation support. `escalated` marks alarms that were raised
-- by the correlation engine (or a burst); escalation is one-way and recorded
-- in the `correlations` audit table.
ALTER TABLE alarms ADD COLUMN IF NOT EXISTS escalated      BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE alarms ADD COLUMN IF NOT EXISTS escalated_at   TIMESTAMPTZ;
ALTER TABLE alarms ADD COLUMN IF NOT EXISTS correlation_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_alarms_escalated ON alarms (escalated) WHERE escalated = false;

-- ----------------------------------------------------------------------------
-- correlations (pattern-detection / escalation audit trail)
-- ----------------------------------------------------------------------------
-- One row per detected correlation. `event_ids` / `alarm_ids` are the JSON
-- arrays of the alarms involved in the detected pattern, and
-- `severity_before -> severity_after` records the escalation that was applied.
CREATE TABLE IF NOT EXISTS correlations (
    correlation_id   BIGSERIAL PRIMARY KEY,
    rule             TEXT NOT NULL,
    site_id          TEXT NOT NULL REFERENCES sites(site_id) ON UPDATE CASCADE,
    sensor_id        TEXT,
    window_start     TIMESTAMPTZ NOT NULL,
    window_end       TIMESTAMPTZ NOT NULL,
    severity_before  TEXT NOT NULL,
    severity_after   TEXT NOT NULL,
    event_ids        JSONB NOT NULL DEFAULT '[]',
    alarm_ids        JSONB NOT NULL DEFAULT '[]',
    description      TEXT NOT NULL DEFAULT '',
    detected_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_correlations_site_ts   ON correlations (site_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_correlations_detected  ON correlations (detected_at DESC);

COMMIT;
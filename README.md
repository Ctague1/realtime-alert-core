# Project Sentinel

Real-time alarm ingestion & monitoring core for Monitex Security.

Project Sentinel consumes a WebSocket sensor-event stream, buffers accepted
events durably in **Redis Streams**, processes them with **at-least-once**
semantics into authoritative **PostgreSQL** state, and streams live updates to
a **React** operator dashboard.

> **Guarantee (the short answer):** once an event is _accepted_ — i.e. appended
> to the Redis Stream — it is never silently lost. A burst, a consumer
> disconnect, or a worker/process restart cannot lose it, because the event is
> durably buffered before processing, every message is explicitly
> acknowledged only after the database commit succeeds, and unacknowledged
> messages are reclaimed and reprocessed (idempotently) after a restart.

---

## Table of contents

1. [Architecture](#architecture)
2. [Technology choices](#technology-choices)
3. [Event lifecycle](#event-lifecycle)
4. [Delivery guarantee](#delivery-guarantee)
5. [Backpressure](#backpressure)
6. [Severity rules](#severity-rules)
7. [Heartbeat / sensor liveness policy](#heartbeat--sensor-liveness-policy)
8. [Correlation & escalation](#correlation--escalation)
9. [Failure recovery](#failure-recovery)
10. [API](#api)
11. [Performance](#performance)
12. [Failure-test suite](#failure-test-suite)
13. [Running locally](#running-locally)
14. [Testing](#testing)
15. [Trade-offs & known limitations](#trade-offs--known-limitations)

---

## Architecture

```
             SENSOR STREAM (scripts/stream.py)
                    stream.py
                       │
                       │ WebSocket
                       ▼
              ┌──────────────────┐
              │ FastAPI backend  │  ingestion: validate -> XADD
              │ (ingestion/API)  │  REST API + /ws/dashboard
              └────────┬─────────┘
                       │ Redis Streams (sensor:events)
                       │   consumer group sentinel-workers
                       │   pending entries / XAUTOCLAIM recovery
                       ▼
              ┌──────────────────┐
              │ Processing worker│  normalize -> dedupe -> severity
              │ (separate proc)  │  -> sensor/site/alarm state -> persist -> ACK
              └────────┬─────────┘
                       │
              ┌────────┴────────┐
              ▼                 ▼
       ┌──────────────┐   Redis pub/sub (transient only)
       │ PostgreSQL   │        │
       │ events       │        ▼
       │ alarms       │   FastAPI hub ──► /ws/dashboard ──► React
       │ sites        │
       │ sensors      │
       └──────────────┘
```

### Components

| Component                     | Responsibility                                                                                                                                                                                                                                                                                                                            |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/stream.py`           | Provided sensor-fleet simulator (WebSocket server on `:8765`). Not part of the Sentinel pipeline. Runs manually on the host, or as the optional `sensor` Compose service (`docker compose --profile sensor up`).                                                                                                                          |
| **backend** (FastAPI)         | Connects to the sensor stream, validates events, appends them to the Redis Stream (the **durability boundary**). Serves the REST API, the dashboard WebSocket, `/metrics` and `/snapshot`. Its dashboard hub subscribes to the transient pub/sub channel and **auto-resubscribes** if that connection drops (e.g. after a Redis restart). |
| **worker** (separate process) | Redis Streams consumer-group consumer. Processes events, persists authoritative state to PostgreSQL, ACKs only after commit, recovers abandoned pending messages, and runs the sensor-liveness and site-state aggregation tasks. Runs in its own container so a worker restart is independent of a backend restart.                       |
| **redis**                     | Durable event buffer (Redis Streams with AOF persistence). Also hosts the transient dashboard pub/sub channel and the `sensor:liveness` hash.                                                                                                                                                                                             |
| **postgres**                  | Authoritative datastore for `sites`, `sensors`, `events`, `alarms` and acknowledgement/resolution state.                                                                                                                                                                                                                                  |
| **frontend** (React + Vite)   | Live operator dashboard; WebSocket updates; reconnect + snapshot reconciliation; acknowledge/resolve actions.                                                                                                                                                                                                                             |

---

## Technology choices

- **Python 3 + FastAPI** — asynchronous ingestion, REST API, WebSocket
  dashboard, health endpoints. `asyncpg` for PostgreSQL, `redis.asyncio` for
  Redis, `websockets` for the outbound sensor connection.
- **WebSocket** — the sensor protocol _and_ the live dashboard transport.
- **Redis Streams** — the durable event buffer and processing pipeline with
  consumer groups, explicit acknowledgements and pending-entry recovery.
  Plain Redis Pub/Sub is used **only** for the transient dashboard update
  channel, never for the critical alarm path (authoritative state always
  comes from PostgreSQL).
- **PostgreSQL** — the authoritative store. `event_id` is the primary key of
  `events` and `UNIQUE` on `alarms`, which makes reprocessing idempotent.
- **React (Vite)** — the operator dashboard.
- **Docker / Docker Compose** — runnable from a clean checkout.

---

## Event lifecycle

```
receive   sensor event arrives on the WebSocket
  → validate   required fields, types, timestamp; malformed events rejected
  → append     XADD to Redis Stream (MAXLEN ~ 1_000_000)
  → ACCEPT     the event is now durable in the pipeline
  → consume    XREADGROUP by the processing worker
  → process    normalize + effective severity + deduplicate
  → persist    one multi-row transaction: events, alarms, sensors, sites
  → dashboard  worker publishes the change (Redis pub/sub → backend → WS)
  → ACK        XACK after the transaction committed
```

A **source timestamp chain** is captured for latency analysis:

```
source_ts          - the sensor's own timestamp
received_at        - backend receive time
redis_ms           - Redis stream ID millisecond (durable append)
worker_started_at  - worker read time
persisted_at       - database commit time
dashboard received - measured client-side against source_ts
```

---

## Delivery guarantee

### What "accepted" means

An event is **accepted by Project Sentinel only when it has been appended to
the Redis Stream** (`XADD` succeeded). Until then it is _received but not
accepted_ — the backend never claims durability for it. This is the
[durability boundary](#event-lifecycle): nothing before the `XADD` is covered.

### What "durable" means

The Redis Stream runs with **AOF persistence (`appendfsync everysec`)**. On a
Redis restart, the stream and consumer-group pending entries are reloaded from
the AOF. Limitation: with `everysec`, up to ~1 second of very recent appends
can be lost on a _hard_ Redis crash (see
[Redis restart](#e-redis-restart) and
[Trade-offs](#trade-offs--known-limitations)). Tune `appendfsync always` for a
tighter window at a throughput cost.

### When ACK occurs

The worker calls `XACK` **only after the PostgreSQL transaction committed**.
If the worker crashes before ACK, the message stays in the consumer group's
pending-entries list.

### How pending events are recovered

- On startup and every `PENDING_CLAIM_INTERVAL` (10s) the worker runs
  `XAUTOCLAIM` with `PENDING_CLAIM_IDLE_MS` (30s): any message left idle in
  the pending list (crashed/disconnected consumer) is reclaimed and
  reprocessed.
- Reprocessing is idempotent: `events.event_id` is the primary key and
  `alarms.event_id` is `UNIQUE`, so `INSERT ... ON CONFLICT DO NOTHING`
  cannot create a second logical event or alarm.

### How duplicates are handled

- Duplicate detection happens **at the database layer** via the `event_id`
  uniqueness constraints, plus an in-worker dedup metric. A duplicate arrives
  → the insert is a no-op → the message is ACKed → `duplicates_detected` is
  incremented. No second logical alarm is ever created.
- This is why worker-restart recovery is safe: re-delivering an already
  committed event is harmless.

---

## Backpressure

The system never drops an alarm under load and never accumulates unbounded
memory:

1. **Durable backlog** — the Redis Stream is the buffer. If processing slows
   down, accepted events queue in the stream instead of being dropped.
2. **Bounded ingestion buffer** — the sensor consumer uses a small bounded
   deque (10k) as a _temporary_ buffer for a Redis blip. If Redis is
   unavailable the consumer **pauses reading** from the sensor WebSocket,
   propagating TCP backpressure to the generator (whose `send` then blocks
   instead of discarding).
3. **Batched writes** — the worker persists events in single multi-row
   transactions (default batch 100), which sustains the generator's actual
   rate (~1000 events/s) with headroom.
4. **Bounded concurrency / DB pooling** — a bounded asyncpg pool; the worker
   reads one batch at a time.
5. **Retry, not loss** — failed batches are left unacked and reclaimed later.

`GET /metrics` reports `backlog_depth` (pending/unacknowledged messages) and
`stream_length`. During bursts the backlog absorbs the spike and the worker
drains it (verified by failure test **B**).

---

## Severity rules

`severity_hint` from the sensor is **not trusted**. The effective severity is
derived deterministically from the event type (`backend/app/processing/severity.py`):

| Event type                                             | Effective severity |
| ------------------------------------------------------ | ------------------ |
| `fire_alarm`, `panic_button`                           | **critical**       |
| `smoke_detected`, `perimeter_breach`, `door_forced`    | high               |
| `camera_offline`, `motion_detected`, `object_detected` | medium             |
| `heartbeat`                                            | informational      |
| any unknown type                                       | low                |

The same type always maps to the same severity.

---

## Heartbeat / sensor liveness policy

Liveness is tracked per sensor in the `sensor:liveness` Redis hash. The
ingestion records the **acceptance time** (Redis append timestamp) whenever an
event for a sensor is durably accepted.

- **Any event refreshes liveness** (heartbeat _or_ alarm). Because liveness is
  keyed to _acceptance_ (Redis), it is independent of processing lag — a
  busy-but-healthy worker never makes live sensors look offline.
- **Offline detection** — a sensor is declared offline when no event has been
  accepted for `HEARTBEAT_OFFLINE_TIMEOUT` (default **30s**). The worker's
  liveness scan runs every `HEARTBEAT_SCAN_INTERVAL` (5s) and flips
  `sensors.online = false`, broadcasting the transition to the dashboard.
- **A single missed heartbeat never marks a sensor offline.** The generator
  emits ~1 event/s per sensor, so several missed heartbeats/events are
  required.
- **Return to online** — as soon as any fresh event is accepted for an offline
  sensor, it is flipped back online and the transition is broadcast.
- Offline state is a **sensor flag**, kept separate from alarm state: going
  offline does not create, cancel or resolve any alarm, and the dashboard
  shows sensor status and alarm status independently.

Note: because the provided generator emits events for _all_ sensors
simultaneously, the heartbeat failure-test stops the host `stream.py` process
to simulate heartbeats ceasing. The per-sensor path is covered precisely by
the pytest integration test (`test_stale_sensor_becomes_offline`).

---

## Correlation & escalation

The worker runs a **pattern-detection scan** (`backend/app/processing/correlation.py`)
every `CORRELATION_SCAN_INTERVAL` (default 5s). It looks for deterministic
patterns in recent, non-resolved, non-escalated alarms and **escalates** the
alarms involved; every detection is recorded in the `correlations` table and
pushed to the dashboard.

| Rule                | Pattern                                                                                                                                     | Escalation                                                               |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `repeat_event`      | ≥ `CORRELATION_REPEAT_THRESHOLD` (3) alarms of the **same type** from the **same sensor** within `CORRELATION_WINDOW` (60s)                 | involved alarms move **one severity step up** (low→medium→high→critical) |
| `multi_signal_site` | ≥ `CORRELATION_MULTI_SIGNAL_THRESHOLD` (3) **distinct alarm types** at the **same site** within the window, with at least one high/critical | involved alarms escalate to **critical**                                 |
| `critical_burst`    | ≥ `CORRELATION_BURST_THRESHOLD` (3) **critical** alarms at the **same site** within the window                                              | recorded as a burst incident (severity stays critical)                   |

Escalation is **idempotent**: only `escalated = false` alarms are considered,
every escalation `UPDATE` is guarded on that flag, and a Redis lock
(`sentinel:correlation:lock`) serializes scans across multiple worker replicas
so the same alarms are never escalated or recorded twice. Escalated alarms keep
their state (ACTIVE/ACKNOWLEDGED/RESOLVED); only severity is raised, which moves
them up the dashboard's severity ordering.

History is available through the timeline API and dashboard:

- `GET /sites/{site_id}/timeline` — the site's current state, recent events
  (with alarm status + escalation flag) and its correlated incidents.
- `GET /sensors/{sensor_id}/timeline` — a sensor's recent events.
- `GET /correlations` — detected patterns / escalations (optionally
  `?site_id=`).

The dashboard shows a **Correlations & escalations** panel (live via WebSocket
`{kind:"correlations"}` plus a periodic poll) and a per-site **timeline** panel
that opens when a site card is clicked. Timelines are read from the
authoritative PostgreSQL state, so they survive restarts and dashboard
reconnects.

---

## Failure recovery

### A. Sustained baseline load

The generator runs at `RATE=200` (its effective rate is higher because of
built-in bursts). Verified: events accepted, processed, dashboard updated, no
unexpected loss, zero processing failures, backlog controlled. See
[Performance](#performance).

### B. Burst traffic

A 500-event burst is absorbed by the durable backlog and drained; pending
returns to within one in-flight batch. No events discarded.

### C. Worker restart

Accepted events remain in the Redis stream; unacknowledged messages are
reclaimed via `XAUTOCLAIM` and reprocessed idempotently; processing resumes;
no duplicate logical events are created (verified by `count(*) =
count(DISTINCT event_id)` in a single snapshot).

### D. Backend restart

The backend reconnects to the sensor stream with exponential backoff; the
durable backlog and PostgreSQL state remain available; processing resumes.

### E. Redis restart

Redis is configured with AOF (`appendfsync everysec`). On restart the stream
and pending entries are reloaded from AOF and processing resumes. The backend
dashboard hub re-subscribes to its pub/sub channel automatically after the
connection drop (exponential backoff), so live dashboard updates resume
without a backend restart. **Limitation:** up to ~1s of very recent appends
may be lost on a hard crash with this configuration — this is the documented
guarantee; increase fsync strength for a tighter window.

### F. Dashboard disconnect

The WebSocket closes while events continue. On reconnect the dashboard
receives a fresh authoritative **snapshot** from the backend and reconciles
state; it never depends on having received every transient message.

### G. Duplicate events

The same `event_id` delivered 3× → exactly one event row and one alarm row.

### H. Sensor heartbeat failure

When heartbeats cease, sensors go offline after the documented timeout,
tracked separately from alarm state; they return online when events flow
again.

---

## API

REST:

```
GET  /health                        health + readiness checks
GET  /metrics                       counters, gauges, latency percentiles
GET  /snapshot                      authoritative dashboard state
GET  /alarms?status=active          active alarms (priority-ordered)
GET  /alarms/{id}
POST /alarms/{id}/acknowledge       ACTIVE -> ACKNOWLEDGED
POST /alarms/{id}/resolve           ACTIVE/ACKNOWLEDGED -> RESOLVED
GET  /sites, /sites/{id}
GET  /sensors, /sensors/{id}
GET  /sites/{id}/timeline, /sensors/{id}/timeline   history/timelines
GET  /correlations                                  detected patterns/escalations
```

WebSocket:

```
/ws/dashboard    sends a snapshot on connect, then live updates:
                 {kind:"alarms", updates:[...]}, {kind:"sensor", ...},
                 {kind:"sites", ...}, {kind:"ping"}
```

Alarm state transitions are validated on the backend
(`ACTIVE → ACKNOWLEDGED → RESOLVED`); invalid transitions return `409`,
missing alarms `404`. State survives page refresh, dashboard reconnect and
backend restart because PostgreSQL is authoritative.

---

## Performance

Measured on a single workstation (see _test environment_ below) with the
provided generator at `RATE=200` — whose effective sustained rate is ~900–1100
events/s because the simulator emits a 500-event burst ~1% of the time.

| Metric                                                | p50                                                          | p95     | p99     |
| ----------------------------------------------------- | ------------------------------------------------------------ | ------- | ------- |
| Ingestion latency (receive → Redis append)            | 0.07 ms                                                      | 0.5 ms  | 1.8 ms  |
| Queue latency (append → worker read)                  | ~80 ms                                                       | ~500 ms | ~600 ms |
| In-process processing (worker batch persist → commit) | ~55 ms                                                       | ~68 ms  | ~73 ms  |
| Total processing (backend receive → DB commit)        | ~137 ms                                                      | ~562 ms | ~673 ms |
| End-to-end dashboard (source → client render)         | measured client-side (avg/p95 shown in the dashboard header) |

- **Throughput:** ~1000 events/s sustained through ingest → Redis → worker →
  PostgreSQL with zero processing failures and no unexpected loss (failure
  test **A**).
- **Burst:** a 500-event burst is drained within one worker batch cycle
  (test **B**).
- **Higher rates:** run `RATE=1000 python scripts/stream.py` to push the
  generator; the worker sustains the default-config capacity by batching.

Interpretation:

- _In-process processing latency_ is well under the **100 ms** target: the
  worker persists each batch of up to 100 events in ~55 ms (p50).
- _Queueing latency_ is the time an accepted event waits in the durable
  backlog before a worker reads it; it rises during bursts and falls back to
  zero as the backlog drains (test **B**).
- _End-to-end latency_ = source → ingest → Redis → queue → process → DB →
  pub/sub → WS → client render.

### Test environment

- Python 3.12.7, Node 22.13.0, Docker 25.0.4 + Compose v2.24.7
- Redis 7.2.5 (`redis:7-alpine`, AOF `everysec`), PostgreSQL 16 (`postgres:16-alpine`)
- Single host; Redis and PostgreSQL in Docker; ~900–1100 events/s sustained input
- Timestamps: source `ts`, `received_at`, Redis stream ID, worker start, DB
  commit, client receive

---

## Failure-test suite

Reproducible scripts in `scripts/failure_tests/` drive the running stack
(Docker Compose for `postgres`/`redis`/`backend`/`worker`/`frontend`, plus the
manually-run sensor stream) and verify every failure scenario. Results from
the last full run: **23/23 assertions passed, 0 failures** (each test's PASS
lines are printed to the terminal).

```bash
# sensor stream must be running on the host first:
#   RATE=200 python scripts/stream.py
bash scripts/failure_tests/run_all.sh
# or individually
bash scripts/failure_tests/a_load.sh
bash scripts/failure_tests/b_burst.sh
bash scripts/failure_tests/c_worker_restart.sh
bash scripts/failure_tests/d_backend_restart.sh
bash scripts/failure_tests/e_redis_restart.sh
bash scripts/failure_tests/f_dashboard_disconnect.sh
bash scripts/failure_tests/g_duplicates.sh
bash scripts/failure_tests/h_heartbeat_failure.sh
```

Backend unit + integration tests (54 tests) are in `backend/tests/`:

```bash
cd backend && python -m pytest -q
```

---

## Running locally

The sensor stream (`scripts/stream.py`) is **run manually on the host** — it
is not part of the Docker stack.

### 1. Start the sensor stream (host)

```bash
pip install websockets
RATE=200 python scripts/stream.py    # listens on ws://localhost:8765
```

### 2. Start the stack with Docker Compose

```bash
docker compose up -d --build
```

Services: `postgres`, `redis`, `backend` (:8000), `worker`, `frontend`
(:8080). The backend reaches the manually-run sensor on the host via
`ws://host.docker.gateway:8765` (needs the generator from step 1 to be
running).

Open the dashboard at **http://localhost:8080** (or http://localhost:8000 for
the API). `GET /health` and `GET /metrics` are available on both ports.

Stop with `docker compose down` (add `-v` to also remove volumes).

All configuration is environment-driven (`backend/app/config.py`); see
`env.example`. Nothing requires undocumented manual modification.

### 2a. Self-contained run (optional containerized generator)

The generator is also packaged as an optional Compose service behind the
`sensor` profile, so the whole system can run without a manual host process:

```bash
SENSOR_WS_URL=ws://sensor:8765 docker compose --profile sensor up -d --build
```

`sensor` emits at `SENSOR_RATE` (default 200). The `backend` is pointed at it
via `SENSOR_WS_URL` (default `ws://host.docker.gateway:8765` for a host-run
generator). Note that the failure-test suite **H** (heartbeat failure) must
stop/restart the generator process and therefore expects the host-run
`stream.py`, not the containerized generator.

### Backend + worker without Docker

Requires PostgreSQL and Redis reachable at the defaults:

```bash
cd backend
pip install -r requirements.txt
# terminal 1 (sensor stream, host)
RATE=200 python ../scripts/stream.py
# terminal 2
python -m app.worker
# terminal 3
uvicorn app.main:app --host 0.0.0.0 --port 8000
# terminal 4 (frontend dev)
cd frontend && npm install && npm run dev
```

---

## Trade-offs & known limitations

1. **Per-event alarm model.** Every alarm event creates one alarm row
   (`alarms.event_id` unique). The provided generator emits ~8/9 of its
   traffic as alarm-type events, so the alarm table grows quickly and "active
   alarms" accumulates (the dashboard shows the top 500 by severity/recency,
   and `/metrics` reports the true counts). Real deployments would aggregate
   alarm types per sensor/site or auto-resolve after a policy window; the
   per-event model was chosen to satisfy the explicit dashboard/ack/resolve
   requirements and to make dedup DB-level and unambiguous.
2. **Redis AOF `everysec`.** On a hard Redis crash, up to ~1s of very recent
   appends may be lost (events received but not yet fsync'd). Raise
   `appendfsync` for a tighter guarantee; every accepted event _before_ the
   loss window is preserved.
3. **Sensor→site mapping is unstable in the simulator.** `stream.py` picks
   `sensor_id` and `site_id` independently, so a sensor's `sites.site_id`
   reflects its most recent event. Events and alarms always use the event's
   own `site_id`.
4. **Liveness uses "any event".** A sensor is considered live if it emits any
   event (not just heartbeats), because the simulator's heartbeat cadence
   (~9s/sensor) makes heartbeat-only tracking noisy. `last_heartbeat_ts` is
   still tracked and surfaced separately.
5. **Dashboard fan-out is transient.** Redis pub/sub forwards live updates;
   a disconnected dashboard catches up via the authoritative snapshot on
   reconnect. Pub/Sub is not part of the durability story.
6. **Single worker process by default.** The worker can be scaled horizontally
   (multiple worker containers share the same consumer group; `XAUTOCLAIM`
   balances recovered work), but only one worker is shipped in the default
   Compose config because one is sufficient for the tested rate.
7. **Sampled percentile windows.** Latency histograms keep the last 10,000
   samples in memory; percentiles are computed on demand, so they describe a
   rolling window, not the full history.

---

## Final engineering question

> **If an alarm has been accepted by Project Sentinel and the system
> experiences a burst, a consumer disconnect, or a worker/process restart,
> what mechanism ensures that the accepted alarm remains recoverable and is
> processed at least once?**

1. **Accepted = appended to the Redis Stream** (durability boundary). The
   event is on durable storage before any processing begins.
2. **Consumer group + explicit ACK.** The worker ACKs only after the
   PostgreSQL transaction commits. If it dies first, the message stays in the
   pending-entries list.
3. **XAUTOCLAIM recovery.** On startup and periodically, idle pending messages
   are reclaimed and reprocessed.
4. **Idempotent reprocessing.** `event_id` is `PRIMARY KEY` on `events` and
   `UNIQUE` on `alarms`, so at-least-once delivery cannot corrupt state.

This is exercised end-to-end by failure tests **B, C, D, E, G** and by the
pytest integration suite (`test_worker_restart_recovers_pending_messages`,
`test_duplicate_event_id_is_idempotent`, `test_500_event_burst_is_absorbed_and_drained`).

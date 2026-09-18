"""Pagination + stats API integration tests.

Seeds more than 500 records (well beyond the old list caps) and verifies the
``/browse/*`` endpoints return correct pages, true totals after filters, and
that ``/stats`` reports authoritative counts (never page-derived).
"""

from __future__ import annotations

import httpx

from app.db import get_db_pool
from app.services.state_service import recompute_all_sites


async def _seed_site_sensor(pool, site_id="site-bulk", sensor_id="sensor-bulk"):
    await pool.execute(
        "INSERT INTO sites (site_id, name) VALUES ($1, $1) ON CONFLICT (site_id) DO NOTHING",
        site_id,
    )
    await pool.execute(
        """
        INSERT INTO sensors (sensor_id, site_id) VALUES ($1, $2)
        ON CONFLICT (sensor_id) DO NOTHING
        """,
        sensor_id,
        site_id,
    )


async def _seed_events_and_alarms(
    pool, n, status="ACTIVE", severity="critical",
    site_id="site-bulk", sensor_id="sensor-bulk", prefix="bulk",
):
    """Bulk-insert ``n`` events + alarms directly (fast path for >500 rows)."""
    await pool.execute(
        """
        INSERT INTO events
            (event_id, sensor_id, site_id, type, severity, confidence,
             source_ts, received_at, processed_at, raw)
        SELECT $5 || '_evt_' || g, $3, $4, 'fire_alarm', $2,
               0.9, now() - make_interval(secs => g), now(), now(), '{}'::jsonb
        FROM generate_series(1, $1) AS g
        """,
        n,
        severity,
        sensor_id,
        site_id,
        prefix,
    )
    await pool.execute(
        """
        INSERT INTO alarms
            (event_id, sensor_id, site_id, type, severity, status, created_at)
        SELECT $5 || '_evt_' || g, $3, $4, 'fire_alarm', $2,
               $6, now() - make_interval(secs => g)
        FROM generate_series(1, $1) AS g
        """,
        n,
        severity,
        sensor_id,
        site_id,
        prefix,
        status,
    )


async def _seed_correlations(pool, n, rule="repeat_event", site_id="site-bulk"):
    await pool.execute(
        """
        INSERT INTO correlations
            (rule, site_id, sensor_id, window_start, window_end,
             severity_before, severity_after, event_ids, alarm_ids,
             description, detected_at)
        SELECT $2, $3, NULL, now(), now(), 'low', 'medium',
               '[]'::jsonb, '[]'::jsonb, 'bulk',
               now() - make_interval(mins => g)
        FROM generate_series(1, $1) AS g
        """,
        n,
        rule,
        site_id,
    )


async def test_stats_counts_true_totals(api_server):
    pool = await get_db_pool()
    await _seed_site_sensor(pool)
    await _seed_events_and_alarms(pool, 520, status="ACTIVE", severity="critical", prefix="a")
    await _seed_events_and_alarms(pool, 7, status="ACKNOWLEDGED", severity="high", prefix="b")
    await _seed_events_and_alarms(pool, 3, status="RESOLVED", severity="low", prefix="c")
    await pool.execute("UPDATE sensors SET online = false WHERE sensor_id = 'sensor-bulk'")
    await _seed_correlations(pool, 12)
    await recompute_all_sites(pool)

    async with httpx.AsyncClient(base_url=api_server, timeout=10) as client:
        resp = await client.get("/stats")
        assert resp.status_code == 200
        body = resp.json()
        # active = ACTIVE + ACKNOWLEDGED (520 + 7); resolved excluded.
        assert body["alarms_active"] == 527
        assert body["alarms_acknowledged"] == 7
        assert body["alarms_critical"] == 520
        assert body["alarms_high"] == 7
        assert body["alarms_low"] == 0
        assert body["sensors_total"] == 1
        assert body["sensors_offline"] == 1
        assert body["sites_total"] == 1
        assert body["sites_active"] == 1
        assert body["correlations_total"] == 12


async def test_browse_alarms_paginates_beyond_500(api_server):
    pool = await get_db_pool()
    await _seed_site_sensor(pool)
    await _seed_events_and_alarms(pool, 520)

    async with httpx.AsyncClient(base_url=api_server, timeout=10) as client:
        # Page 1.
        resp = await client.get("/browse/alarms?page=1&page_size=50")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 520
        assert body["total_pages"] == 11
        assert len(body["items"]) == 50

        # A page well past the first 500 records.
        resp = await client.get("/browse/alarms?page=11&page_size=50")
        body = resp.json()
        assert len(body["items"]) == 20
        assert body["total"] == 520
        assert body["page"] == 11

        # Page beyond the end -> empty items, accurate total.
        resp = await client.get("/browse/alarms?page=12&page_size=50")
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 520


async def test_browse_alarms_status_filter_total(api_server):
    pool = await get_db_pool()
    await _seed_site_sensor(pool)
    await _seed_events_and_alarms(pool, 300, status="ACTIVE", severity="critical", prefix="a")
    await _seed_events_and_alarms(pool, 40, status="ACKNOWLEDGED", severity="high", prefix="b")

    async with httpx.AsyncClient(base_url=api_server, timeout=10) as client:
        body = (await client.get("/browse/alarms?status=ACKNOWLEDGED&page_size=10")).json()
        assert body["total"] == 40
        assert len(body["items"]) == 10
        assert all(a["status"] == "ACKNOWLEDGED" for a in body["items"])

        body = (await client.get("/browse/alarms?status=active&page_size=10")).json()
        assert body["total"] == 340

        bad = await client.get("/browse/alarms?status=bogus")
        assert bad.status_code == 400


async def test_browse_sites_severity_filter(api_server):
    pool = await get_db_pool()
    await _seed_site_sensor(pool, "site-a")
    await _seed_site_sensor(pool, "site-b")
    await _seed_events_and_alarms(pool, 5, severity="critical", site_id="site-a")
    await recompute_all_sites(pool)

    async with httpx.AsyncClient(base_url=api_server, timeout=10) as client:
        all_sites = (await client.get("/browse/sites")).json()
        assert all_sites["total"] == 2

        crit = (await client.get("/browse/sites?severity=critical")).json()
        assert crit["total"] == 1
        assert crit["items"][0]["site_id"] == "site-a"

        clear = (await client.get("/browse/sites?severity=clear")).json()
        assert clear["total"] == 1


async def test_browse_sensors_online_filter(api_server):
    pool = await get_db_pool()
    await _seed_site_sensor(pool)
    await pool.execute(
        "INSERT INTO sensors (sensor_id, site_id, online) VALUES ($1, 'site-bulk', false)",
        "sensor-off",
    )
    await pool.execute(
        "INSERT INTO sensors (sensor_id, site_id, online) VALUES ($1, 'site-bulk', true)",
        "sensor-on",
    )

    async with httpx.AsyncClient(base_url=api_server, timeout=10) as client:
        offline = (await client.get("/browse/sensors?online=false")).json()
        assert offline["total"] == 1
        assert offline["items"][0]["sensor_id"] == "sensor-off"

        online = (await client.get("/browse/sensors?online=true")).json()
        assert online["total"] == 2  # sensor-bulk defaults to online

        all_sensors = (await client.get("/browse/sensors?page_size=2")).json()
        assert all_sensors["total"] == 3


async def test_browse_correlations_rule_filter(api_server):
    pool = await get_db_pool()
    await _seed_site_sensor(pool)
    await _seed_correlations(pool, 25, rule="repeat_event")
    await _seed_correlations(pool, 8, rule="critical_burst")

    async with httpx.AsyncClient(base_url=api_server, timeout=10) as client:
        body = (await client.get("/browse/correlations?page_size=10")).json()
        assert body["total"] == 33
        assert len(body["items"]) == 10

        burst = (await client.get("/browse/correlations?rule=critical_burst")).json()
        assert burst["total"] == 8
        assert all(c["rule"] == "critical_burst" for c in burst["items"])

        site_filtered = (await client.get("/browse/correlations?site_id=site-bulk")).json()
        assert site_filtered["total"] == 33
import asyncio, json, random, uuid, datetime, os, websockets

SENSORS = [f"sensor-{s:03d}" for s in range(1, 201)]  # 200 sensors
SITES = [f"site-{n}" for n in range(100, 140)]        # 40 sites
TYPES = [
    "motion_detected",
    "perimeter_breach",
    "door_forced",
    "smoke_detected",
    "fire_alarm",
    "object_detected",
    "camera_offline",
    "panic_button",
    "heartbeat",
]

RATE = float(os.getenv("RATE", "200"))  # steady events/sec


def make_event():
    return {
        "event_id": "evt_" + uuid.uuid4().hex[:12],
        "sensor_id": random.choice(SENSORS),
        "site_id": random.choice(SITES),
        "type": random.choice(TYPES),
        "confidence": round(random.uniform(0.4, 0.99), 2),
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
    }


async def handler(ws):
    interval = 1.0 / RATE
    while True:
        burst = 500 if random.random() < 0.01 else 1  # ~1% chance: 500 at once
        for _ in range(burst):
            await ws.send(json.dumps(make_event()))
        await asyncio.sleep(interval)


async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print(f"Sensor fleet streaming ~{RATE}/s on ws://localhost:8765")
        await asyncio.Future()


asyncio.run(main())
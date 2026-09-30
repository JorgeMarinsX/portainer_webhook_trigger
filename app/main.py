"""Minimal ASGI app: cron-scheduled Portainer webhook calls, plus /health and /trigger."""

import asyncio
import json
import logging
import os
from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from jobs import fire, parse_jobs
from notifications import notify

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("webhook_cron_trigger")

# Fail fast at import time: a bad config must kill the process, not serve a silent no-op.
TZ_NAME = (os.environ.get("TZ") or "").strip()
if not TZ_NAME:
    raise SystemExit("TZ is required, e.g. TZ=America/Sao_Paulo")
try:
    TZ = ZoneInfo(TZ_NAME)
except (ZoneInfoNotFoundError, ValueError) as e:
    raise SystemExit(f"TZ {TZ_NAME!r} is not a valid IANA timezone: {e}") from e

try:
    JOBS = parse_jobs(os.environ.get("JOBS"), TZ)
except ValueError as e:
    raise SystemExit(f"invalid JOBS config: {e}") from e

BY_NAME = {job.name: job for job in JOBS}

scheduler = AsyncIOScheduler(
    timezone=TZ,
    job_defaults={
        # Missed runs (container was down) are dropped, not backfilled.
        "coalesce": True,
        "misfire_grace_time": 60,
        "max_instances": 1,
    },
)


async def _run(name: str) -> bool:
    ok = await asyncio.to_thread(fire, BY_NAME[name])
    await asyncio.to_thread(notify, name, ok, _next_run(name))
    return ok


def _start() -> None:
    for job in JOBS:
        scheduler.add_job(_run, job.trigger, args=[job.name], id=job.name, name=job.name)
    scheduler.start()
    for job in JOBS:
        log.info(
            "scheduled %s cron=%r next=%s", job.name, job.cron, scheduler.get_job(job.name).next_run_time
        )


def _next_run(name: str) -> str | None:
    job = scheduler.get_job(name)
    return job.next_run_time.isoformat() if job and job.next_run_time else None


async def _send_json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})


async def _http(scope, send) -> None:
    method = scope["method"]
    path = scope["path"].rstrip("/") or "/"

    if method == "GET" and path == "/health":
        return await _send_json(send, 200, {
            "status": "ok",
            "timezone": TZ_NAME,
            "jobs": [
                {"name": j.name, "cron": j.cron, "next_run": _next_run(j.name)} for j in JOBS
            ],
        })

    if method == "POST" and path.startswith("/trigger/"):
        name = unquote(path[len("/trigger/"):])
        if name not in BY_NAME:
            return await _send_json(send, 404, {"error": f"unknown job {name!r}", "jobs": list(BY_NAME)})
        log.info("job %s triggered manually", name)
        ok = await _run(name)
        return await _send_json(send, 200 if ok else 502, {"job": name, "ok": ok})

    await _send_json(send, 404, {"error": "not found", "routes": ["GET /health", "POST /trigger/{job_name}"]})


async def app(scope, receive, send) -> None:
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                _start()
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                scheduler.shutdown(wait=False)
                await send({"type": "lifespan.shutdown.complete"})
                return
    elif scope["type"] == "http":
        await _http(scope, send)

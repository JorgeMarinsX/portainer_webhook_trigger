"""JOBS parsing/validation and the webhook call."""

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger("webhook_cron_trigger")

RETRIES = 3
BACKOFF_SECONDS = 2.0
TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class Job:
    name: str
    cron: str
    url: str
    trigger: CronTrigger


def parse_jobs(raw: str | None, timezone) -> list[Job]:
    """Parse the JOBS env var. Raises ValueError with a clear message on any problem."""
    if not raw or not raw.strip():
        raise ValueError("JOBS is required: a JSON array of {name, cron, url} objects")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"JOBS is not valid JSON: {e}") from e

    if not isinstance(data, list) or not data:
        raise ValueError("JOBS must be a non-empty JSON array of job objects")

    jobs: list[Job] = []
    seen: set[str] = set()

    for i, item in enumerate(data):
        where = f"JOBS[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be an object, got {type(item).__name__}")

        bad = [
            k
            for k in ("name", "cron", "url")
            if not isinstance(item.get(k), str) or not item[k].strip()
        ]
        if bad:
            raise ValueError(f"{where} missing or empty string field(s): {', '.join(bad)}")

        name = item["name"].strip()
        if name in seen:
            raise ValueError(f"{where} duplicate job name {name!r}")
        seen.add(name)

        url = item["url"].strip()
        if not url.startswith(("https://", "http://")):
            raise ValueError(f"{where} ({name}) url must start with https:// or http://, got {url!r}")

        cron = item["cron"].strip()
        try:
            trigger = CronTrigger.from_crontab(cron, timezone=timezone)
        except ValueError as e:
            raise ValueError(f"{where} ({name}) invalid cron expression {cron!r}: {e}") from e

        jobs.append(Job(name=name, cron=cron, url=url, trigger=trigger))

    return jobs


def fire(job: Job) -> bool:
    """POST an empty body to the webhook. Retries a few times, never raises."""
    request = urllib.request.Request(job.url, data=b"", method="POST")

    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                log.info("job %s fired: status=%s", job.name, response.status)
                return True
        except urllib.error.HTTPError as e:
            body = e.read(2000).decode("utf-8", "replace").strip()
            log.error(
                "job %s failed (attempt %d/%d): status=%s body=%s",
                job.name, attempt, RETRIES, e.code, body or "<empty>",
            )
        except Exception as e:  # network errors, timeouts, bad DNS
            log.error("job %s failed (attempt %d/%d): %s: %s",
                      job.name, attempt, RETRIES, type(e).__name__, e)

        if attempt < RETRIES:
            time.sleep(BACKOFF_SECONDS * attempt)

    log.error("job %s gave up after %d attempts; waiting for next scheduled run", job.name, RETRIES)
    return False

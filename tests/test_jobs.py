"""JOBS config parsing + validation."""

import json
from zoneinfo import ZoneInfo

import pytest

from jobs import parse_jobs

TZ = ZoneInfo("America/Sao_Paulo")
URL = "https://portainer.example.com/api/webhooks/8f1c-uuid"


def _raw(*jobs):
    return json.dumps(list(jobs))


def test_parses_valid_jobs():
    jobs = parse_jobs(
        _raw(
            {"name": "prod-api", "cron": "0 2 * * *", "url": URL},
            {"name": "prod-worker", "cron": "30 2 * * *", "url": URL},
        ),
        TZ,
    )
    assert [j.name for j in jobs] == ["prod-api", "prod-worker"]
    assert jobs[0].trigger.get_next_fire_time(None, __import__("datetime").datetime.now(TZ)).hour == 2


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, "JOBS is required"),
        ("", "JOBS is required"),
        ("not json", "not valid JSON"),
        ("[]", "non-empty JSON array"),
        ('{"name": "a"}', "non-empty JSON array"),
        ("[1]", "must be an object"),
        ('[{"cron": "0 2 * * *", "url": "%s"}]' % URL, "missing or empty string field"),
        ('[{"name": " ", "cron": "0 2 * * *", "url": "%s"}]' % URL, "missing or empty"),
        ('[{"name": "a", "cron": "0 2 * * *", "url": "ftp://x/y"}]', "must start with https://"),
        ('[{"name": "a", "cron": "nope", "url": "%s"}]' % URL, "invalid cron expression"),
        ('[{"name": "a", "cron": "0 2 * *", "url": "%s"}]' % URL, "invalid cron expression"),
        ('[{"name": "a", "cron": "99 2 * * *", "url": "%s"}]' % URL, "invalid cron expression"),
    ],
)
def test_rejects_bad_config(raw, expected):
    with pytest.raises(ValueError, match=expected):
        parse_jobs(raw, TZ)


def test_rejects_duplicate_names():
    raw = _raw(
        {"name": "prod-api", "cron": "0 2 * * *", "url": URL},
        {"name": "prod-api", "cron": "0 3 * * *", "url": URL},
    )
    with pytest.raises(ValueError, match="duplicate job name 'prod-api'"):
        parse_jobs(raw, TZ)

"""Trigger outcome -> every configured channel. Never raises: a broken notifier must not break a trigger."""

import logging

from . import discord

log = logging.getLogger("webhook_cron_trigger")

CHANNELS = [discord]


def notify(job: str, ok: bool, next_run: str | None = None) -> None:
    # Success is posted silently (daily per env, would be noise); only failures ping.
    if ok:
        text = f"✅ `{job}` triggered"
    else:
        text = f"❌ `{job}` failed after retries, check the logs. Next run: {next_run or 'none'}"
    for channel in CHANNELS:
        try:
            channel.send(text, silent=ok)
        except Exception as e:
            log.error("notify via %s failed: %s: %s", channel.__name__, type(e).__name__, e)

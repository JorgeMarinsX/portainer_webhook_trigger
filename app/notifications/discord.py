"""Discord channel: posts to DISCORD_WEBHOOK. No-op when unset."""

import json
import os
import threading
import time
import urllib.request

WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
SUPPRESS_NOTIFICATIONS = 1 << 12  # message is posted, but nobody gets a push/ping
SPACING_SECONDS = 3  # jobs sharing a cron time would otherwise burst past Discord's ~5 posts/2s

_lock = threading.Lock()
_last = 0.0


def send(text: str, silent: bool) -> None:
    global _last
    if not WEBHOOK:
        return
    with _lock:
        time.sleep(max(0.0, _last + SPACING_SECONDS - time.monotonic()))
        _last = time.monotonic()
        _post(text, silent)


def _post(text: str, silent: bool) -> None:
    request = urllib.request.Request(
        WEBHOOK,
        data=json.dumps({"content": text, "flags": SUPPRESS_NOTIFICATIONS if silent else 0}).encode(),
        # Discord's Cloudflare rejects the default Python-urllib user agent with a 403.
        headers={"Content-Type": "application/json", "User-Agent": "webhook-cron-trigger"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10):
        pass

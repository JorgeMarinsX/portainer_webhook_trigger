"""Notification fan-out: silent on success, pings on failure, never raises. Discord posts are spaced."""

import notifications
from notifications import discord


def test_discord_spaces_posts(monkeypatch):
    monkeypatch.setattr(discord, "WEBHOOK", "https://discord.example/webhook")
    monkeypatch.setattr(discord, "_post", lambda text, silent: None)
    sleeps = []
    monkeypatch.setattr(discord.time, "sleep", sleeps.append)
    discord.send("a", silent=True)
    discord.send("b", silent=True)
    assert sleeps[-1] > discord.SPACING_SECONDS - 0.1


def test_notify(monkeypatch):
    sent = []
    monkeypatch.setattr(notifications.discord, "send", lambda text, silent: sent.append((text, silent)))
    notifications.notify("prod-api", True)
    notifications.notify("prod-api", False, "2026-10-01T02:00:00-03:00")
    assert [silent for _, silent in sent] == [True, False]
    assert "prod-api" in sent[1][0] and "2026-10-01T02:00:00-03:00" in sent[1][0]

    def down(text, silent):
        raise OSError("discord is down")

    monkeypatch.setattr(notifications.discord, "send", down)
    notifications.notify("prod-api", False)  # must not raise

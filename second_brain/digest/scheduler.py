"""APScheduler wiring for the daily digest."""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from second_brain.digest.digest import send_digest


def _parse_time(value: str) -> tuple[int, int]:
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)


def start_scheduler(app) -> None:
    settings = app.bot_data["settings"]
    hour, minute = _parse_time(settings.digest_time)

    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        send_digest,
        CronTrigger(hour=hour, minute=minute, timezone=settings.timezone),
        args=[app],
        id="daily_digest",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    app.bot_data["scheduler"] = scheduler


def stop_scheduler(app) -> None:
    scheduler = app.bot_data.get("scheduler")
    if scheduler:
        scheduler.shutdown(wait=False)
        app.bot_data["scheduler"] = None

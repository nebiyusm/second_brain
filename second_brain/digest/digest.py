"""Compose and send the daily digest and weekly review."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import Settings
from second_brain.notion.client import NotionClient
from second_brain.notion.databases import IDEAS, INBOX, PROJECTS, TASKS

_PRIORITY_WEIGHT = {"High": 3, "Medium": 2, "Low": 1}
_OPEN_FILTER = {"property": "Status", "select": {"does_not_equal": "Done"}}


def _days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(dt.tzinfo) - dt).days
    except ValueError:
        return None


def _task_due(task: dict) -> str | None:
    due = task.get("properties", {}).get("Due", {})
    if due.get("type") == "date" and due.get("date"):
        return due["date"].get("start")
    return None


def _relation_ids(task: dict) -> list[str]:
    rel = task.get("properties", {}).get("Project", {})
    if rel.get("type") == "relation":
        return [r.get("id", "") for r in rel.get("relation", []) if r.get("id")]
    return []


async def build_digest(notion: NotionClient, settings: Settings) -> tuple[str, dict | None]:
    today = date.today()
    tasks_db = settings.require_db_id(TASKS)

    open_tasks = await notion.query_database(tasks_db, filter=_OPEN_FILTER)

    # Project staleness map
    project_meta: dict[str, dict] = {}
    projects_db = settings.db_id(PROJECTS)
    if projects_db:
        projects = await notion.query_database(projects_db)
        for p in projects:
            project_meta[p["id"]] = {
                "title": notion.title_of(p),
                "days": _days_since(p.get("last_edited_time")),
            }

    today_tasks: list[dict] = []
    overdue_tasks: list[dict] = []
    scored: list[tuple[int, dict]] = []
    today_iso = today.isoformat()

    for task in open_tasks:
        due = _task_due(task)
        if due:
            if due < today_iso:
                overdue_tasks.append(task)
            elif due == today_iso:
                today_tasks.append(task)

        score = _PRIORITY_WEIGHT.get(
            notion.property_text(task, "Priority") or "Medium", 2
        )
        rel_ids = _relation_ids(task)
        stale = any(
            project_meta.get(pid, {}).get("days") is not None
            and project_meta.get(pid, {}).get("days", 0) >= 14
            for pid in rel_ids
        )
        if stale:
            score += 2
        if due and due < today_iso:
            score += 1
        scored.append((score, task))

    scored.sort(key=lambda x: x[0], reverse=True)
    suggestions = scored[:3]

    lines: list[str] = ["🌅 Rise and shine. Here's what you're ignoring today."]

    lines.append("📅 Today's tasks")
    if today_tasks:
        for t in today_tasks:
            lines.append(f"  • {notion.title_of(t)}")
    else:
        lines.append("  • None")

    lines.append("⏰ Overdue")
    if overdue_tasks:
        for t in overdue_tasks[:5]:
            due = _task_due(t) or "?"
            lines.append(f"  • {notion.title_of(t)} (due {due})")
    else:
        lines.append("  • None")

    lines.append("🎯 Suggested focus")
    if suggestions:
        for _score, t in suggestions:
            prio = notion.property_text(t, "Priority") or "Medium"
            title = notion.title_of(t)
            extra = ""
            for pid in _relation_ids(t):
                meta = project_meta.get(pid)
                if meta and meta.get("days", 0) >= 14:
                    extra = f" — stale project: {meta['title']}"
                    break
            lines.append(f"  • [{prio}] {title}{extra}")
    else:
        lines.append("  • Nothing open")

    # Idle idea nudge
    idea: dict | None = None
    ideas_db = settings.db_id(IDEAS)
    if ideas_db:
        cutoff = (today - timedelta(days=30)).isoformat()
        idle_ideas = await notion.query_database(
            ideas_db,
            filter={
                "and": [
                    {
                        "or": [
                            {"property": "Stage", "select": {"equals": "Seed"}},
                            {"property": "Stage", "select": {"equals": "Exploring"}},
                        ]
                    },
                    {"property": "Last Touched", "date": {"on_or_before": cutoff}},
                ]
            },
        )
        if idle_ideas:
            idea = random.choice(idle_ideas)
            lines.append("💡 Idle idea")
            lines.append(f"  • {notion.title_of(idea)}")

    return "\n".join(lines), idea


async def send_digest(app) -> None:
    settings: Settings = app.bot_data["settings"]
    notion: NotionClient = app.bot_data["notion"]
    text, idea = await build_digest(notion, settings)

    keyboard = None
    if idea:
        idea_id = notion.page_id(idea)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚀 Promote", callback_data=f"digest:idea:{idea_id}:promote"),
                InlineKeyboardButton("🌱 Keep", callback_data=f"digest:idea:{idea_id}:keep"),
                InlineKeyboardButton("🗑️ Drop", callback_data=f"digest:idea:{idea_id}:drop"),
            ]
        ])

    await app.bot.send_message(
        chat_id=settings.telegram_allowed_user_id,
        text=text,
        reply_markup=keyboard,
    )


async def build_review(notion: NotionClient, settings: Settings) -> str:
    today = date.today()
    lines: list[str] = ["📋 Weekly review. Let's see what you've been avoiding."]

    if settings.db_id(INBOX):
        inbox = await notion.query_database(
            settings.require_db_id(INBOX),
            filter={"property": "Status", "select": {"equals": "Unprocessed"}},
        )
        lines.append(f"🗃️ Inbox unprocessed: {len(inbox)}")

    if settings.db_id(PROJECTS):
        projects = await notion.query_database(settings.require_db_id(PROJECTS))
        stale = [p for p in projects if (_days_since(p.get("last_edited_time")) or 0) >= 14]
        lines.append(f"📁 Stale projects ({len(stale)}):")
        for p in stale[:5]:
            lines.append(f"  • {notion.title_of(p)}")

    if settings.db_id(IDEAS):
        cutoff = (today - timedelta(days=30)).isoformat()
        ideas = await notion.query_database(
            settings.require_db_id(IDEAS),
            filter={
                "and": [
                    {
                        "or": [
                            {"property": "Stage", "select": {"equals": "Seed"}},
                            {"property": "Stage", "select": {"equals": "Exploring"}},
                        ]
                    },
                    {"property": "Last Touched", "date": {"on_or_before": cutoff}},
                ]
            },
        )
        lines.append(f"💡 Idle ideas: {len(ideas)}")

    return "\n".join(lines)


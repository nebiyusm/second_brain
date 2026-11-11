"""Capability #5: Q&A over the second brain."""
from __future__ import annotations

import html

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from second_brain.ai.brain import answer_question
from second_brain.notion.client import NotionClient
from second_brain.notion.databases import AREAS, IDEAS, INBOX, MEDIA, PROJECTS, RESOURCES, TASKS
from second_brain.handlers.util import send_typing
from config import Settings


async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str) -> None:
    message = update.effective_message
    notion: NotionClient = context.bot_data["notion"]
    settings: Settings = context.bot_data["settings"]
    llm = context.bot_data["llm"]

    await send_typing(message)

    entries = await _read_notion(notion, settings, question)

    if not entries:
        await message.reply_text(
            "I've got nothing in here about that. Maybe actually tell me things once in a while. 🤷"
        )
        return

    top = entries[:12]
    answer = await answer_question(llm, question, top)

    sources = "\n".join(
        f"[{i}] <a href=\"{html.escape(e['url'])}\">{html.escape(e['title'])}</a>"
        for i, e in enumerate(top, 1)
    )

    await message.reply_text(
        f"{answer}\n\n<b>Sources</b>\n{sources}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


_DB_KEYWORDS = {
    TASKS: ("task", "todo", "to-do", "to do", "due", "deadline", "doing"),
    IDEAS: ("idea",),
    PROJECTS: ("project",),
    INBOX: ("inbox", "unprocessed", "triaged"),
    RESOURCES: ("note", "resource", "knowledge", "read", "research", "summary", "documentation"),
    MEDIA: ("book", "watch", "movie", "podcast", "documentary", "video", "reading", "media", "watchlist"),
    AREAS: ("area", "responsibility"),
}

_COMMON_PROPS = [
    "Status", "Due", "Priority", "Stage", "Domain", "Tags", "Type", "Topic",
    "Summary", "AI Summary", "Why Added", "Last Touched", "Captured On",
]


def _detect_db_intent(question: str) -> list[str]:
    q = question.lower()
    return [db for db, kws in _DB_KEYWORDS.items() if any(k in q for k in kws)]


def _row_snippet(notion: NotionClient, page: dict) -> str:
    parts = []
    for name in _COMMON_PROPS:
        value = notion.property_text(page, name)
        if value:
            parts.append(f"{name}: {value}")
    return "; ".join(parts)


async def _query_db_entries(notion: NotionClient, settings: Settings, db_key: str, limit: int = 40) -> list[dict]:
    db_id = settings.db_id(db_key)
    if not db_id:
        return []
    pages = await notion.query_database(db_id, page_size=limit)
    entries: list[dict] = []
    for p in pages[:limit]:
        title = notion.title_of(p)
        if not title or title == "Untitled":
            continue
        entries.append({"title": title, "url": p.get("url", ""), "snippet": _row_snippet(notion, p)})
    return entries


async def _read_notion(notion: NotionClient, settings: Settings, question: str) -> list[dict]:
    """Read the user's Notion: query matching databases directly, then full-text search."""
    entries: list[dict] = []
    seen: set[str] = set()

    # 1) Structured questions ("list my tasks", "what's in my inbox") -> query DBs.
    for db_key in _detect_db_intent(question):
        for entry in await _query_db_entries(notion, settings, db_key):
            key = entry["url"] or entry["title"]
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)

    # 2) Full-text search for general / semantic questions.
    try:
        results = await notion.search(question, page_size=30)
    except Exception:
        results = []

    for p in results:
        if p.get("object") != "page":
            continue
        pid = p.get("id", "")
        title = notion.title_of(p)
        if not title or title == "Untitled":
            continue
        if pid in seen:
            continue
        seen.add(pid)

        snippet = _row_snippet(notion, p)
        if not snippet:
            try:
                blocks = await notion.get_blocks(pid)
                snippet = notion.blocks_to_text(blocks)[:600]
            except Exception:
                snippet = ""
        entries.append({"title": title, "url": p.get("url", ""), "snippet": snippet})

    return entries

"""Capability #4: execute work instructions (/do or TASK_FOR_BOT)."""
from __future__ import annotations

import html
from datetime import date

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from config import Settings
from second_brain.ai.brain import execute_instruction
from second_brain.notion import builders as B
from second_brain.notion.client import NotionClient
from second_brain.notion.databases import PROJECTS, RESOURCES
from second_brain.handlers.util import send_typing
from second_brain.store.queue import PendingItem


async def do_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args).strip()
    if not text:
        await update.effective_message.reply_text("Usage: /do <instruction>")
        return
    await handle_instruction(update, context, text)


async def handle_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE, instruction: str) -> None:
    message = update.effective_message
    notion: NotionClient = context.bot_data["notion"]
    settings: Settings = context.bot_data["settings"]
    llm = context.bot_data["llm"]
    user_id = update.effective_user.id

    await send_typing(message)

    context_text = await _gather_context(notion, settings, instruction)
    result = await execute_instruction(llm, instruction, context_text)

    title = result["title"]
    body = result["body"] or ""
    tags = result["tags"]

    project = None
    if result["destination"] == "project" and result["project_name"]:
        project = await _find_project(notion, settings, result["project_name"])

    children = B.md_to_blocks(body)
    props = _resource_props(title, tags, body[:250])

    try:
        if project:
            page = await notion.create_child_page(
                project["id"], {"title": B.title_prop(title)}, children, B.emoji_icon("🤖")
            )
        else:
            page = await notion.create_page_in_db(
                settings.require_db_id(RESOURCES), props, children, B.emoji_icon("🤖")
            )
    except Exception as exc:  # noqa: BLE001
        queue = context.bot_data["queue"]
        await queue.push(
            PendingItem(
                database=RESOURCES, properties=props, children=children,
                icon=B.emoji_icon("🤖"), note=f"Deliverable: {title}", user_id=user_id,
            )
        )
        await message.reply_text(f"⚠️ Notion write failed — queued for /retry. ({exc})")
        return

    url = notion.page_url(page)
    extra = ""

    if len(body.split()) > 2000:
        try:
            summary = await _summarize_deliverable(llm, body)
            summary_page = await notion.create_page_in_db(
                settings.require_db_id(RESOURCES),
                _resource_props(f"{title} — Summary", tags, summary[:250]),
                B.md_to_blocks(summary),
                B.emoji_icon("📄"),
            )
            await notion.append_blocks(
                notion.page_id(page),
                [B.heading_2("Summary"), B.link_to_page_block(notion.page_id(summary_page))],
            )
            await notion.append_blocks(
                notion.page_id(summary_page),
                [B.heading_2("Full document"), B.link_to_page_block(notion.page_id(page))],
            )
            extra = " (+ 1-page summary)"
        except Exception:  # noqa: BLE001
            extra = ""

    reply = result.get("reply") or "Done — and I did it myself, no hands needed. 😏"
    await message.reply_text(
        f"{reply}\n\n🔗 <a href=\"{html.escape(url)}\">{html.escape(title)}</a>{extra}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


def _resource_props(title: str, tags: list[str], summary: str) -> dict:
    return {
        "Name": B.title_prop(title),
        "Tags": B.multi_select_prop(tags),
        "Last Touched": B.date_prop(date.today()),
        "Summary": B.rich_text_prop(summary),
    }


async def _gather_context(notion: NotionClient, settings: Settings, instruction: str) -> str:
    from second_brain.handlers.qa import _read_notion

    entries = await _read_notion(notion, settings, instruction)
    if not entries:
        return ""
    parts = [f"[{i}] {e['title']}\n{e['snippet']}" for i, e in enumerate(entries[:6], 1)]
    return "\n\n".join(parts)


async def _find_project(notion: NotionClient, settings: Settings, name: str) -> dict | None:
    if not name or not settings.db_id(PROJECTS):
        return None
    projects = await notion.query_database(
        settings.require_db_id(PROJECTS),
        filter={"property": "Status", "select": {"equals": "Active"}},
    )
    n = name.lower()
    for p in projects:
        if notion.title_of(p).lower() == n:
            return p
    for p in projects:
        t = notion.title_of(p).lower()
        if n in t or t in n:
            return p
    return None


async def _summarize_deliverable(llm, body: str) -> str:
    return await llm.chat([
        {
            "role": "system",
            "content": "Summarize this document into a one-page summary using Markdown headings and bullets.",
        },
        {"role": "user", "content": body[:8000]},
    ])

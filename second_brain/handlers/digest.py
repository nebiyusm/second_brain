"""Capability #3 + /today and /review command handlers."""
from __future__ import annotations

from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from second_brain.digest.digest import build_digest, build_review
from second_brain.notion import builders as B
from second_brain.notion.client import NotionClient
from second_brain.notion.databases import IDEAS, PROJECTS
from second_brain.handlers.util import send_typing


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    notion: NotionClient = context.bot_data["notion"]
    settings = context.bot_data["settings"]
    await send_typing(update.effective_message)

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
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    notion: NotionClient = context.bot_data["notion"]
    settings = context.bot_data["settings"]
    await send_typing(update.effective_message)
    text = await build_review(notion, settings)
    await update.effective_message.reply_text(text)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    parts = data.split(":")
    if len(parts) != 4:
        return
    _kind, _idea, idea_id, action = parts

    notion: NotionClient = context.bot_data["notion"]
    settings = context.bot_data["settings"]

    if action == "promote":
        await _promote_idea(update, context, notion, settings, idea_id)
    elif action == "keep":
        await notion.update_page(idea_id, {"Last Touched": B.date_prop(date.today())})
        await q.edit_message_text(q.message.text + "\n\n🌱 Kept incubating.")
    elif action == "drop":
        await notion.update_page(idea_id, {"Stage": B.select_prop("Dropped")})
        await q.edit_message_text(q.message.text + "\n\n🗑️ Dropped.")


async def _promote_idea(update: Update, context: ContextTypes.DEFAULT_TYPE, notion: NotionClient, settings, idea_id: str) -> None:
    try:
        idea = await notion.get_page(idea_id)
        title = notion.title_of(idea)
        projects_db = settings.require_db_id(PROJECTS)

        project = await notion.create_page_in_db(
            projects_db,
            {"Name": B.title_prop(title)},
            icon=B.emoji_icon("🚀"),
        )
        await notion.update_page(idea_id, {"Stage": B.select_prop("Promoted")})

        url = notion.page_url(project)
        await update.callback_query.edit_message_text(
            f"🚀 Promoted to project: <a href=\"{url}\">{title}</a>",
            parse_mode="HTML",
        )
    except Exception as exc:  # noqa: BLE001
        await update.callback_query.edit_message_text(f"⚠️ Couldn't promote: {exc}")

"""Small command handlers: /start, /cancel, /retry."""
from __future__ import annotations

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from second_brain.notion.client import NotionClient
from second_brain.store.queue import PendingItem


async def send_typing(message) -> None:
    """Best-effort typing indicator; never let a timeout break a handler."""
    try:
        await message.chat.send_action(ChatAction.TYPING)
    except Exception:
        pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from second_brain.handlers.chat import greet

    await greet(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conversations = context.application.bot_data.setdefault("conversations", {})
    conversations.pop(update.effective_user.id, None)
    await update.effective_message.reply_text("Fine. Cancelled. Forget I said anything.")


async def retry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    queue = context.bot_data["queue"]
    notion: NotionClient = context.bot_data["notion"]
    settings = context.bot_data["settings"]

    items = await queue.pop_all()
    if not items:
        await update.effective_message.reply_text("Nothing to retry. Suspiciously efficient of you.")
        return

    saved, failed = 0, 0
    for item in items:
        if item.user_id != update.effective_user.id:
            await queue.push(item)
            continue
        try:
            db_id = settings.require_db_id(item.database)
            await notion.create_page_in_db(db_id, item.properties, item.children, item.icon)
            saved += 1
        except Exception:
            await queue.push(item)
            failed += 1

    await update.effective_message.reply_text(
        f"Retried {saved + failed} item(s): {saved} saved, {failed} still failing. (See? I fix your messes too.)"
    )

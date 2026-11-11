"""Application wiring: build the bot and register all handlers."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import Settings
from second_brain.ai.llm import LLMClient
from second_brain.digest.scheduler import start_scheduler, stop_scheduler
from second_brain.handlers import chat, digest as digest_handlers, executor, util, video
from second_brain.notion.client import NotionClient
from second_brain.store.queue import PendingQueue

logger = logging.getLogger("second_brain.bot")


async def _log_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message
    text = ""
    if msg is not None:
        text = (msg.text or msg.caption or "")[:80]
    logger.info(
        "UPDATE user_id=%s chat_id=%s kind=%s text=%r",
        getattr(user, "id", None),
        getattr(chat, "id", None),
        type(msg).__name__ if msg is not None else "?",
        text,
    )


async def _post_init(app: Application) -> None:
    settings: Settings = app.bot_data["settings"]
    logger.info("Allowed user id = %s", settings.telegram_allowed_user_id)
    app.bot_data["llm"] = LLMClient(settings)
    app.bot_data["notion"] = NotionClient(settings)
    app.bot_data["queue"] = PendingQueue(settings.data_dir)
    start_scheduler(app)


async def _post_shutdown(app: Application) -> None:
    stop_scheduler(app)


def build_app(settings: Settings) -> Application:
    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data["settings"] = settings

    # Catch-all logger (group=-1 runs before filtered handlers) for debugging.
    app.add_handler(MessageHandler(filters.ALL, _log_update), group=-1)

    allowed = filters.User(user_id=settings.telegram_allowed_user_id)

    # Commands
    app.add_handler(CommandHandler("start", util.start, filters=allowed))
    app.add_handler(CommandHandler("cancel", util.cancel, filters=allowed))
    app.add_handler(CommandHandler("retry", util.retry, filters=allowed))
    app.add_handler(CommandHandler("today", digest_handlers.today, filters=allowed))
    app.add_handler(CommandHandler("review", digest_handlers.review, filters=allowed))
    app.add_handler(CommandHandler("do", executor.do_command, filters=allowed))

    # Messages
    app.add_handler(MessageHandler(allowed & filters.TEXT & ~filters.COMMAND, chat.handle_text))
    app.add_handler(MessageHandler(allowed & (filters.VOICE | filters.AUDIO), chat.handle_voice))
    app.add_handler(
        MessageHandler(
            allowed & (filters.VIDEO | filters.VIDEO_NOTE | filters.Document.ALL),
            video.handle_video_file,
        )
    )

    # Callbacks (single dispatcher)
    app.add_handler(CallbackQueryHandler(_handle_callback))

    return app


async def _handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = update.callback_query.data or ""
    if data.startswith("digest:"):
        await digest_handlers.handle_callback(update, context)
    else:
        await chat.handle_callback(update, context)

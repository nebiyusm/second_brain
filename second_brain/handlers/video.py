"""Capability #2: video extraction (TikTok / Instagram / forwarded video)."""
from __future__ import annotations

import asyncio
import html
from datetime import date
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from second_brain.ai.brain import synthesize_video_note
from second_brain.ai.prompts import VISION_SYSTEM
from second_brain.ai.transcribe import transcribe_audio
from second_brain.media.download import download
from second_brain.media.frames import extract_frames
from second_brain.notion import builders as B
from second_brain.notion.client import NotionClient
from second_brain.notion.databases import RESOURCES
from second_brain.handlers.util import send_typing
from second_brain.store.queue import PendingItem


async def handle_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    message = update.effective_message
    settings = context.bot_data["settings"]

    await send_typing(message)
    await message.reply_text("⏬ Downloading video…")

    work = Path(settings.data_dir) / "video"
    try:
        meta = await asyncio.to_thread(download, url, work)
    except Exception as exc:  # noqa: BLE001
        if "instagram" in url.lower() or "tiktok" in url.lower():
            await message.reply_text(
                "⚠️ I couldn't grab that one — the site's blocking me (they do that). "
                "Just forward the video file to me instead and I'll process it."
            )
        else:
            await message.reply_text(f"⚠️ Download failed: {exc}")
        return

    await _process_video(
        update, context, meta["path"], meta.get("uploader", ""), url, meta.get("title", "")
    )


async def handle_video_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    settings = context.bot_data["settings"]

    video = message.video or message.video_note
    doc = message.document

    if video is None and doc is None:
        return
    if video is None and doc is not None:
        if not (doc.mime_type or "").startswith("video/"):
            await message.reply_text("That doesn't look like a video file.")
            return

    await send_typing(message)

    attachment = video or doc
    work = Path(settings.data_dir) / "video"
    work.mkdir(parents=True, exist_ok=True)

    suffix = ".mp4"
    if doc is not None and doc.file_name:
        suffix = Path(doc.file_name).suffix or ".mp4"

    path = work / f"{attachment.file_unique_id}{suffix}"
    tg_file = await attachment.get_file()
    await tg_file.download_to_drive(path)

    await _process_video(update, context, path, "", "", "")


async def _process_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    video_path: Path,
    creator: str,
    source_url: str,
    caption: str,
) -> None:
    message = update.effective_message
    settings = context.bot_data["settings"]
    llm = context.bot_data["llm"]
    notion: NotionClient = context.bot_data["notion"]

    await message.reply_text("🎧 Transcribing audio…")
    transcript = await transcribe_audio(settings, video_path)

    await message.reply_text("🖼️ Extracting frames…")
    frames = await asyncio.to_thread(extract_frames, video_path, 4)

    await message.reply_text("👁️ Analyzing frames…")
    frame_descriptions = ""
    if frames:
        try:
            frame_descriptions = await llm.describe_images(frames, VISION_SYSTEM)
        except Exception:  # noqa: BLE001
            frame_descriptions = ""

    await message.reply_text("🧠 Synthesizing note…")
    note = await synthesize_video_note(
        llm, transcript, frame_descriptions, caption, creator, source_url
    )

    title = note["title"]
    props = {
        "Name": B.title_prop(title),
        "Tags": B.multi_select_prop(note["tags"]),
        "Last Touched": B.date_prop(date.today()),
        "Summary": B.rich_text_prop(note["tldr"]),
    }

    sections: list[tuple[str, str | list[str]]] = []
    if note["key_points"]:
        sections.append(("Key Points", note["key_points"]))
    if note["details"]:
        sections.append(("Details Worth Keeping", [note["details"]]))
    source_items = [f"URL: {source_url}" if source_url else "Forwarded video"]
    source_items.append(f"Creator: {creator}" if creator else "Creator: unknown")
    sections.append(("Source", source_items))
    sections.append(("Transcript", [transcript]))
    sections.append(("Frame Descriptions", [frame_descriptions or "—"]))

    children = B.build_content_children(note["tldr"], sections)

    try:
        page = await notion.create_page_in_db(
            settings.require_db_id(RESOURCES), props, children, B.emoji_icon("🎬")
        )
    except Exception as exc:  # noqa: BLE001
        queue = context.bot_data["queue"]
        await queue.push(
            PendingItem(
                database=RESOURCES, properties=props, children=children,
                icon=B.emoji_icon("🎬"), note=f"Video note: {title}",
                user_id=update.effective_user.id,
            )
        )
        await message.reply_text(f"⚠️ Notion write failed — queued for /retry. ({exc})")
        return

    url = notion.page_url(page)
    summary_line = note["summary_line"] or note["tldr"]
    await message.reply_text(
        f"{summary_line}\n\n🔗 <a href=\"{html.escape(url)}\">{html.escape(title)}</a>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

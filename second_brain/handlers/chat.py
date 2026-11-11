"""Conversational handler: discussion + guided capture into Notion."""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from second_brain.ai.classify import classify_intent
from second_brain.ai.transcribe import transcribe_audio
from second_brain.notion import builders as B
from second_brain.notion.client import NotionClient
from second_brain.notion.databases import AREAS, IDEAS, MEDIA, MEDIA_TYPES, PROJECTS, TASKS
from second_brain.persona import PERSONA_SYSTEM, media_verb
from second_brain.handlers.util import send_typing
from second_brain.store.queue import PendingItem

CHAT_SYSTEM = (
    PERSONA_SYSTEM
    + "\n\nYou are chatting casually with the user, in character. Keep replies short and fun. "
    "If they mention wanting to add a task/idea/media, tell them to just say 'add a task', "
    "'add an idea', or 'add media'."
)

_NEXT = {
    "task": {"title": "project", "project": "area", "area": "notes", "notes": None},
    "idea": {"title": "area", "area": "notes", "notes": None},
    "media": {"title": "type", "type": "notes", "notes": None},
}


@dataclass
class Conversation:
    kind: str
    step: str
    data: dict = field(default_factory=dict)

    @property
    def expects_text(self) -> bool:
        return self.step in ("title", "notes")


def _convs(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.application.bot_data.setdefault("conversations", {})


def _get_conv(context: ContextTypes.DEFAULT_TYPE, uid: int) -> Conversation | None:
    return _convs(context).get(uid)


def _set_conv(context: ContextTypes.DEFAULT_TYPE, uid: int, conv: Conversation) -> None:
    _convs(context)[uid] = conv


def _clear_conv(context: ContextTypes.DEFAULT_TYPE, uid: int) -> None:
    _convs(context).pop(uid, None)


def _short_title(text: str, max_len: int = 60) -> str:
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text or "Untitled"
    return text[: max_len - 1].rstrip() + "…"


def _tldr(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= 300:
        return text
    return text[:299].rstrip() + "…"


def _html_link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url)}">{html.escape(text)}</a>'


async def _reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def _send_question(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    buttons: list[list[InlineKeyboardButton]],
) -> None:
    markup = InlineKeyboardMarkup([*buttons, [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]])
    q = update.callback_query
    if q is not None:
        await q.edit_message_text(text, reply_markup=markup)
    else:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def _confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, page: dict) -> None:
    notion: NotionClient = context.bot_data["notion"]
    url = notion.page_url(page)
    title = notion.title_of(page)
    msg = f"{text}\n🔗 {_html_link(url, title)}" if url else text
    if update.callback_query is not None:
        await update.callback_query.edit_message_text(msg, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(msg, parse_mode="HTML")


async def _create_or_queue(
    context: ContextTypes.DEFAULT_TYPE,
    db_key: str,
    properties: dict,
    children: list[dict] | None,
    icon: dict | None,
    note: str,
    user_id: int,
) -> tuple[dict | None, Exception | None]:
    notion: NotionClient = context.bot_data["notion"]
    settings = context.bot_data["settings"]
    queue = context.bot_data["queue"]

    db_id = settings.require_db_id(db_key)
    try:
        page = await notion.create_page_in_db(db_id, properties, children, icon)
        return page, None
    except Exception as exc:  # noqa: BLE001
        await queue.push(
            PendingItem(
                database=db_key, properties=properties, children=children,
                icon=icon, note=note, user_id=user_id,
            )
        )
        return None, exc


def _is_social_video(text: str) -> bool:
    t = text.lower()
    return any(
        m in t
        for m in ("tiktok.com", "instagram.com/reel", "instagram.com/reels", "instagram.com/p/")
    )


# --------------------------------------------------------------------------- #
# Entry points + intent routing
# --------------------------------------------------------------------------- #
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = (message.text or "").strip()
    if not text:
        return

    uid = update.effective_user.id

    if _is_social_video(text):
        from second_brain.handlers.video import handle_video_link
        return await handle_video_link(update, context, text)

    conv = _get_conv(context, uid)
    if conv and conv.expects_text:
        return await _handle_answer(update, context, conv, text)

    if conv:
        _clear_conv(context, uid)

    await send_typing(message)
    try:
        await _route(update, context, text)
    except Exception as exc:  # noqa: BLE001
        await _reply(update, context, f"⚠️ Something broke: {exc}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    settings = context.bot_data["settings"]

    attachment = message.voice or message.audio
    if attachment is None:
        return

    await send_typing(message)

    suffix = ".ogg"
    if message.audio:
        suffix = Path(message.audio.file_name or "").suffix or ".ogg"

    path = Path(settings.data_dir) / "voice" / f"{attachment.file_unique_id}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)

    tg_file = await attachment.get_file()
    await tg_file.download_to_drive(path)

    try:
        transcript = await transcribe_audio(settings, path)
    except Exception as exc:  # noqa: BLE001
        await message.reply_text(f"⚠️ Transcription failed: {exc}")
        return

    transcript = (transcript or "").strip()
    if not transcript:
        await message.reply_text("⚠️ Couldn't transcribe that.")
        return

    await _route(update, context, transcript)


async def _route(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    llm = context.bot_data["llm"]
    intent = await classify_intent(llm, text)
    itype = intent["intent"]
    title = intent["title"]

    if itype == "GREETING":
        await greet(update, context)
    elif itype == "ADD_TASK":
        await _start_flow(update, context, "task", title)
    elif itype == "ADD_IDEA":
        await _start_flow(update, context, "idea", title)
    elif itype == "ADD_MEDIA":
        await _start_flow(update, context, "media", title)
    elif itype == "LIST":
        await _list_flow(update, context, text)
    elif itype == "QUESTION":
        from second_brain.handlers.qa import handle_question
        await handle_question(update, context, text)
    elif itype == "TASK_FOR_BOT":
        from second_brain.handlers.executor import handle_instruction
        await handle_instruction(update, context, text)
    elif itype == "UNKNOWN":
        await _log_unhandled(update, context, text)
    else:
        await _chat_reply(update, context, text)


# --------------------------------------------------------------------------- #
# Greeting
# --------------------------------------------------------------------------- #
async def greet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Task", callback_data="menu:task"),
            InlineKeyboardButton("💡 Add Idea", callback_data="menu:idea"),
        ],
        [
            InlineKeyboardButton("🎬 Add Media", callback_data="menu:media"),
            InlineKeyboardButton("📋 List Tasks", callback_data="menu:list"),
        ],
        [
            InlineKeyboardButton("🔎 Ask my brain", callback_data="menu:ask"),
            InlineKeyboardButton("💬 Just chat", callback_data="menu:chat"),
        ],
    ])
    await update.effective_message.reply_text(
        "👋 Hey. It's me — your brain, no hands, all sarcasm. What are we doing?",
        reply_markup=markup,
    )


# --------------------------------------------------------------------------- #
# Guided flows
# --------------------------------------------------------------------------- #
def _title_prompt(kind: str) -> str:
    return {"task": "✅ What's the task?", "idea": "💡 What's the idea?", "media": "🎬 What's it called?"}[kind]


async def _list_pages(context: ContextTypes.DEFAULT_TYPE, db_key: str) -> list[dict]:
    notion: NotionClient = context.bot_data["notion"]
    settings = context.bot_data["settings"]
    db_id = settings.db_id(db_key)
    if not db_id:
        return []
    return await notion.query_database(db_id, page_size=50)


async def _page_buttons(context: ContextTypes.DEFAULT_TYPE, db_key: str, prefix: str) -> list[list[InlineKeyboardButton]]:
    notion: NotionClient = context.bot_data["notion"]
    pages = await _list_pages(context, db_key)
    buttons = [
        [InlineKeyboardButton(_short_title(notion.title_of(p), 40), callback_data=f"{prefix}:{p['id']}")]
        for p in pages
    ]
    buttons.append([InlineKeyboardButton("None", callback_data=f"{prefix}:none")])
    return buttons


async def _start_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, title: str) -> None:
    uid = update.effective_user.id
    first_step = "title" if not title else _NEXT[kind]["title"]
    conv = Conversation(kind=kind, step=first_step, data={"title": title})
    _set_conv(context, uid, conv)
    await _ask_step(update, context, conv)


async def _ask_step(update: Update, context: ContextTypes.DEFAULT_TYPE, conv: Conversation) -> None:
    step = conv.step
    if step == "title":
        await _send_question(update, context, _title_prompt(conv.kind), [])
    elif step == "project":
        buttons = await _page_buttons(context, PROJECTS, "task:project")
        await _send_question(update, context, "📁 Which project?", buttons)
    elif step == "area":
        buttons = await _page_buttons(context, AREAS, f"{conv.kind}:area")
        await _send_question(update, context, "🗂️ Which area?", buttons)
    elif step == "type":
        buttons = [[InlineKeyboardButton(t, callback_data=f"media:type:{t}")] for t in MEDIA_TYPES]
        await _send_question(update, context, "🎬 What type of media?", buttons)
    elif step == "notes":
        await _send_question(
            update, context,
            "📝 Any notes? (type them, or tap Skip)",
            [[InlineKeyboardButton("Skip", callback_data=f"{conv.kind}:notes:skip")]],
        )


async def _handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, conv: Conversation, value: str) -> None:
    step = conv.step
    if step == "title":
        conv.data["title"] = _short_title(value)
    elif step == "project":
        conv.data["project_id"] = None if value == "none" else value
    elif step == "area":
        conv.data["area_id"] = None if value == "none" else value
    elif step == "type":
        conv.data["media_type"] = value
    elif step == "notes":
        conv.data["notes"] = None if value == "skip" else value

    nxt = _NEXT[conv.kind].get(step)
    if nxt is None:
        _clear_conv(context, update.effective_user.id)
        if conv.kind == "task":
            await _save_task(update, context, conv)
        elif conv.kind == "idea":
            await _save_idea(update, context, conv)
        elif conv.kind == "media":
            await _save_media(update, context, conv)
    else:
        conv.step = nxt
        await _ask_step(update, context, conv)


# --------------------------------------------------------------------------- #
# Save functions
# --------------------------------------------------------------------------- #
async def _save_task(update: Update, context: ContextTypes.DEFAULT_TYPE, conv: Conversation) -> None:
    d = conv.data
    title = d.get("title") or "Untitled task"
    props = {
        "Name": B.title_prop(title),
        "Status": B.select_prop("To do"),
    }
    if d.get("project_id"):
        props["Project"] = B.relation_prop([d["project_id"]])
    if d.get("area_id"):
        props["Area"] = B.relation_prop([d["area_id"]])
    if d.get("notes"):
        props["Notes"] = B.rich_text_prop(d["notes"])

    sections = [("Notes", [d["notes"]])] if d.get("notes") else []
    children = B.build_content_children(_tldr(title), sections)

    page, err = await _create_or_queue(
        context, TASKS, props, children, B.emoji_icon("✅"),
        f"Saved task: {title}", update.effective_user.id,
    )
    if page:
        await _confirm(update, context, f"Saved to Tasks ✅ {title}", page)
    else:
        await _reply(update, context, f"⚠️ Notion write failed — queued for /retry. ({err})")


async def _save_idea(update: Update, context: ContextTypes.DEFAULT_TYPE, conv: Conversation) -> None:
    d = conv.data
    title = d.get("title") or "Untitled idea"
    props = {
        "Name": B.title_prop(title),
        "Stage": B.select_prop("Seed"),
        "Last Touched": B.date_prop(date.today()),
    }
    if d.get("area_id"):
        props["Area"] = B.relation_prop([d["area_id"]])

    sections = [("Notes", [d["notes"]])] if d.get("notes") else []
    children = B.build_content_children(_tldr(title), sections)

    page, err = await _create_or_queue(
        context, IDEAS, props, children, B.emoji_icon("💡"),
        f"Saved idea: {title}", update.effective_user.id,
    )
    if page:
        await _confirm(update, context, f"Saved to Ideas 💡 {title}", page)
    else:
        await _reply(update, context, f"⚠️ Notion write failed — queued for /retry. ({err})")


async def _save_media(update: Update, context: ContextTypes.DEFAULT_TYPE, conv: Conversation) -> None:
    d = conv.data
    title = d.get("title") or "Untitled"
    media_type = d.get("media_type") or "Book"

    props = {
        "Title": B.title_prop(title),
        "Type": B.select_prop(media_type),
        "Status": B.select_prop("Queue"),
        "Why Added": B.rich_text_prop(d.get("notes") or ""),
    }
    sections = [("Notes", [d["notes"]])] if d.get("notes") else []
    children = B.build_content_children(_tldr(title), sections)

    page, err = await _create_or_queue(
        context, MEDIA, props, children, B.emoji_icon("🎬"),
        f"Saved media: {title}", update.effective_user.id,
    )
    if page:
        verb = media_verb(media_type)
        await _confirm(update, context, f"📚 Saved {title}. Now actually {verb} it, then tell me about it.", page)
    else:
        await _reply(update, context, f"⚠️ Notion write failed — queued for /retry. ({err})")


# --------------------------------------------------------------------------- #
# List + status change
# --------------------------------------------------------------------------- #
def _row_snippet(notion: NotionClient, page: dict) -> str:
    parts = []
    for name in ("Status", "Due", "Priority", "Stage", "Type", "Topic", "Summary"):
        v = notion.property_text(page, name)
        if v:
            parts.append(f"{name}: {v}")
    return "; ".join(parts)


async def _list_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    notion: NotionClient = context.bot_data["notion"]
    t = text.lower()

    if any(k in t for k in ("idea",)):
        db_key = IDEAS
    elif any(k in t for k in ("project",)):
        db_key = PROJECTS
    elif any(k in t for k in ("media", "book", "watch", "movie", "podcast", "documentary")):
        db_key = MEDIA
    elif any(k in t for k in ("area",)):
        db_key = AREAS
    else:
        db_key = TASKS

    pages = await _list_pages(context, db_key)

    if db_key == TASKS:
        await _list_tasks(update, context, notion, pages)
        return

    label = {"ideas": "ideas", "projects": "projects", "media": "media", "areas": "areas"}.get(db_key, db_key)
    if not pages:
        await _reply(update, context, f"No {label} yet. Suspiciously empty.")
        return
    lines = [f"Here's your {label}:"]
    for p in pages:
        title = notion.title_of(p)
        extra = _row_snippet(notion, p)
        lines.append(f"• {title}" + (f" — {extra}" if extra else ""))
    await _reply(update, context, "\n".join(lines[:40]))


async def _list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE, notion: NotionClient, pages: list[dict]) -> None:
    if not pages:
        await _reply(update, context, "No tasks. Are you even working? 😏")
        return
    lines = ["📋 Your tasks:"]
    for i, p in enumerate(pages, 1):
        title = notion.title_of(p)
        status = notion.property_text(p, "Status") or "—"
        due = notion.property_text(p, "Due")
        lines.append(f"{i}. {title} [{status}]" + (f" (due {due})" if due else ""))

    buttons = [
        [InlineKeyboardButton(f"{i}. {notion.title_of(p)}", callback_data=f"status:pick:{p['id']}")]
        for i, p in enumerate(pages[:10])
    ]
    buttons.append([InlineKeyboardButton("No thanks", callback_data="status:none")])

    await update.effective_message.reply_text(
        "\n".join(lines) + "\n\nWant to change a task's status? Tap one:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _task_status_options(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    notion: NotionClient = context.bot_data["notion"]
    settings = context.bot_data["settings"]
    schema = await notion.get_schema(settings.require_db_id(TASKS))
    prop = schema.get("Status", {})
    return [o.get("name") for o in prop.get("select", {}).get("options", [])]


async def _status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    q = update.callback_query
    parts = data.split(":", 2)

    if parts[1] == "none":
        await q.edit_message_text("Okay, leaving them as-is.")
        return

    if parts[1] == "pick":
        task_id = parts[2]
        opts = await _task_status_options(context)
        buttons = [[InlineKeyboardButton(o, callback_data=f"status:set:{task_id}:{o}")] for o in opts]
        await q.edit_message_text("Set status to:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if parts[1] == "set":
        rest = parts[2].split(":", 1)
        task_id, status = rest[0], rest[1]
        notion: NotionClient = context.bot_data["notion"]
        await notion.update_page(task_id, {"Status": B.select_prop(status)})
        await q.edit_message_text(f"✅ Status set to {status}.")


# --------------------------------------------------------------------------- #
# Unhandled message log
# --------------------------------------------------------------------------- #
def _chunks(text: str, size: int = 1900) -> list[str]:
    """Split text into Notion-safe rich_text chunks (2000-char limit per block)."""
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


async def _log_unhandled(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Save a message the bot couldn't route into Tasks for later review."""
    title = f"❓ Unhandled: {_short_title(text, 50)}"
    props = {
        "Name": B.title_prop(title),
        "Status": B.select_prop("To do"),
        "Notes": B.rich_text_prop(_chunks(text)[0]),
    }
    sections = [
        ("Raw message", _chunks(text)),
        ("What to do", "Review this message, tell the bot how to handle messages like it, then mark this task Done."),
    ]
    children = B.build_content_children(_tldr(text), sections)

    page, err = await _create_or_queue(
        context, TASKS, props, children, B.emoji_icon("❓"),
        f"Logged unhandled message: {title}", update.effective_user.id,
    )
    if page:
        await _confirm(
            update, context,
            "🤷 I didn't understand that — saved it to your Tasks. Review it there and tell me what to do with messages like it.",
            page,
        )
    else:
        await _reply(update, context, f"🤷 Didn't understand that, and saving it failed — queued for /retry. ({err})")


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
async def _chat_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    llm = context.bot_data["llm"]
    uid = update.effective_user.id
    history = context.application.bot_data.setdefault("chat_history", {}).setdefault(uid, [])

    messages = [{"role": "system", "content": CHAT_SYSTEM}]
    for h in history[-8:]:
        messages.append(h)
    messages.append({"role": "user", "content": text})

    reply = await llm.chat(messages, temperature=0.7)

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})

    await update.effective_message.reply_text(reply)


# --------------------------------------------------------------------------- #
# Callback dispatcher
# --------------------------------------------------------------------------- #
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    if data == "cancel":
        _clear_conv(context, update.effective_user.id)
        await q.edit_message_text("Fine. Cancelled.")
        return

    if data.startswith("menu:"):
        await _menu_action(update, context, data.split(":", 1)[1])
        return

    if data.startswith("status:"):
        await _status_callback(update, context, data)
        return

    conv = _get_conv(context, update.effective_user.id)
    if not conv:
        await q.edit_message_text("That action is stale — send me a new message.")
        return

    parts = data.split(":", 2)
    if len(parts) < 3:
        return
    kind, step, value = parts[0], parts[1], parts[2]

    if kind != conv.kind or step != conv.step:
        return

    if step == "notes" and value == "skip":
        await _handle_answer(update, context, conv, "skip")
    elif step in ("project", "area"):
        await _handle_answer(update, context, conv, None if value == "none" else value)
    elif step == "type":
        await _handle_answer(update, context, conv, value)


async def _menu_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    if action == "task":
        await _start_flow(update, context, "task", "")
    elif action == "idea":
        await _start_flow(update, context, "idea", "")
    elif action == "media":
        await _start_flow(update, context, "media", "")
    elif action == "list":
        await _list_flow(update, context, "tasks")
    elif action == "ask":
        await update.callback_query.edit_message_text("Go ahead, ask me anything. 🤓")
    elif action == "chat":
        await update.callback_query.edit_message_text("I'm listening. 👂")

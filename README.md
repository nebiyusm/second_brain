# Second Brain — Telegram Bot ↔ Notion

A single-user Telegram bot that acts as the capture, organizing, and query layer
over your Notion second brain (PARA + Inbox).

## What it does

1. **Smart Capture & Triage** — classifies any text/voice note as IDEA / TASK /
   NOTE-RESOURCE / QUESTION / TASK-FOR-BOT / UNCLEAR and files it into the right
   database (with a short, button-driven conversation, never more than 3 questions).
2. **Video Extraction** — TikTok/Instagram links or forwarded video files:
   download (yt-dlp), transcribe (Whisper), extract key frames (ffmpeg), describe
   frames (vision LLM), and save a structured note.
3. **Daily Digest** — scheduled every morning: today's + overdue tasks, suggested
   focus (priority + project staleness), and one idle-idea nudge with buttons.
4. **Task Execution** — `/do <instruction>` (or a work instruction detected
   automatically): searches Notion for context, executes, saves to the right place,
   and auto-adds a 1-page summary for large outputs.
5. **Q&A over your brain** — search all databases and answer with citations.
6. **Hygiene** — every write is confirmed with a link; failed writes are queued and
   replayed with `/retry`; `/today`, `/review`, `/cancel`.

---

## Prerequisites

- Python **3.11+** (developed on 3.12)
- **ffmpeg** on `PATH` (used for key-frame extraction). On Windows: `winget install ffmpeg`.
- A Telegram bot token and your Telegram user id
- A Notion integration and the database ids
- An **OpenAI-compatible** LLM endpoint (OpenAI, Groq, OpenRouter, Together, Ollama, …)

---

## 1. Telegram setup (BotFather)

1. Open **@BotFather** on Telegram.
2. Send `/newbot`, give it a name and username. Copy the **token**.
3. (Optional) `/setcommands` and paste:
   ```
   do - do work for me
   today - daily digest
   review - weekly review
   retry - retry unsaved items
   cancel - abort a flow
   ```

## 2. Get your Telegram user id

Message **@userinfobot** and copy the numeric **Id**.

## 3. Notion setup

1. Go to <https://www.notion.so/my-integrations> → **New integration**, name it,
   choose the workspace, and copy the **Internal Integration Secret** (starts with `secret_`).
2. Share **every database** with the integration. For each of these databases,
   open it in Notion → click the **•••** menu (top-right) → **Connections** →
   **Add connection** → select your integration:
   - **Inbox**, **Projects**, **Areas**, **Resources**, **Tasks**, **Ideas**, **Media**
3. **Find each database id**: open the database in a browser. The URL looks like
   `https://www.notion.so/<workspace>/<32-char-id>?v=...`. Copy the 32-character id.

### Notion database schemas (match these property names)

| DB | Properties |
|----|-----------|
| Inbox | Name, Type (Text/Voice note/Photo/Link/Video), Status (Unprocessed/Triaged/Filed), AI Summary, Routed To (relation→Projects), Captured On |
| Projects | Status (Active/Incubating/Parked/Done) |
| Areas | — (responsibilities) |
| Resources | Tags (multi-select), Last Touched (date), Summary (text) |
| Tasks | Name, Project / Area (relation→Projects), Status (To do/Doing/Done), Due (date), Priority (High/Medium/Low), Notes |
| Ideas | Name, Stage (Seed/Exploring/Validating/Promoted/Parked/Dropped), Domain, Last Touched, Excitement, Effort, Related (relation→Projects) |
| Media | Title, Type, Topic, Status, Why Added, Rating, Finished On |

> Controlled tag vocabulary (used everywhere): `realestate, hospitality, agriculture,
> crypto, software, art-tech, music, content, personal-growth, finance, legal,
> research, idea, meeting, decision`.

## 4. LLM endpoints (split providers)

Chat, vision, and audio transcription can each use a **different** OpenAI-compatible
provider (or all the same one). Each service falls back to `OPENAI_API_KEY` /
`OPENAI_BASE_URL` unless you set its own override:

| Service | Key override | Base URL override | Model |
|---------|-------------|-------------------|-------|
| Chat (classify / Q&A / execute) | `CHAT_API_KEY` | `CHAT_BASE_URL` | `CHAT_MODEL` |
| Vision (frame description) | `VISION_API_KEY` | `VISION_BASE_URL` | `VISION_MODEL` |
| Audio (transcription) | `AUDIO_API_KEY` | `AUDIO_BASE_URL` | `AUDIO_MODEL` |

Common `*_BASE_URL` values:

| Provider | `*_BASE_URL` |
|----------|--------------|
| OpenAI | `https://api.openai.com/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Together | `https://api.together.xyz/v1` |
| DeepSeek | `https://api.deepseek.com` |
| Ollama (local) | `http://localhost:11434/v1` |

### Example: DeepSeek for chat + local Whisper

```ini
# Chat via DeepSeek (no vision, no audio endpoint)
OPENAI_API_KEY=sk-...                    # DeepSeek key (shared fallback)
OPENAI_BASE_URL=https://api.deepseek.com
CHAT_MODEL=deepseek-flash

# DeepSeek has no /audio/transcriptions endpoint -> transcribe locally
TRANSCRIPTION_BACKEND=local
WHISPER_LOCAL_MODEL=base

# DeepSeek has no stable vision model, so frame description is skipped
# automatically. To enable it, add a vision-capable provider:
# VISION_API_KEY=sk-...
# VISION_BASE_URL=https://api.openai.com/v1
# VISION_MODEL=gpt-4o
```

## 5. Configure

```bash
cp .env.example .env   # Windows: copy .env.example .env
```

Fill in `.env`:

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`
- `NOTION_API_KEY`, `NOTION_DB_IDS` (JSON — put each 32-char id under its key)
- `OPENAI_API_KEY` + `OPENAI_BASE_URL` (shared fallback), or per-service `CHAT_*`, `VISION_*`, `AUDIO_*`
- `TRANSCRIPTION_BACKEND=api` (or `local`), `AUDIO_MODEL` (or `WHISPER_LOCAL_MODEL`)
- `TIMEZONE` (IANA name, e.g. `Africa/Nairobi`), `DIGEST_TIME` (`HH:MM`)

## 6. Run

### Locally

```bash
pip install -r requirements.txt
python main.py
```

### Docker (home server)

```bash
docker compose up -d --build
```

---

## Usage

- **Capture**: just send text, a link, or a voice note.
- **Video**: send a TikTok/Instagram link or forward the video file.
- **Do work**: `/do research the Nairobi hotel market` (or just say it).
- **Ask**: "what did I save about crypto regulation?"
- **On demand**: `/today` (digest), `/review` (weekly review).
- **Recover**: `/retry` replays failed writes; `/cancel` aborts a flow.
- **Unhandled messages**: anything the bot genuinely can't understand is saved to
  your Tasks DB (titled `❓ Unhandled: …`) so you can review it and decide how
  such messages should be handled.

---

## Notes & v1 limitations

- **Single user** only (`TELEGRAM_ALLOWED_USER_ID`).
- **Key frames** are described textually and saved in the page body. Attaching the
  actual images to Notion requires a public image host; wire one into
  `second_brain/handlers/video.py` if you want inline images.
- **Local transcription** (`TRANSCRIPTION_BACKEND=local`) needs `faster-whisper` —
  uncomment it in `requirements.txt` and `pip install` it (it pulls a larger deps tree).
- The bot **only appends** to existing pages (no editing beyond that).
- English only.

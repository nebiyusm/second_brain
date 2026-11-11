"""Verify .env configuration and live API credentials (no secrets printed)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REQUIRED = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_ID",
    "NOTION_API_KEY",
    "NOTION_DB_IDS",
    "OPENAI_API_KEY",
    "CHAT_API_KEY",
    "OPENAI_BASE_URL",
    "TRANSCRIPTION_BACKEND",
]


def mask(value: str) -> str:
    if not value:
        return "EMPTY"
    low = value.strip().lower()
    if "xxxx" in low or "your_" in low or low in ("sk-", "secret_", "123456789", "123456789:"):
        return "PLACEHOLDER"
    return "SET"


def main() -> int:
    env = Path(".env")
    if not env.exists():
        print("NO_ENV_FILE")
        return 1

    values: dict[str, str] = {}
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip()

    print("--- .env status ---")
    for key in sorted(values):
        v = values[key]
        quoted = v.startswith('"') or v.startswith("'")
        print(f"{key} = {mask(v)} (len={len(v)}, quoted={quoted})")

    try:
        from config import Settings

        settings = Settings()
        print("--- Settings ---")
        print("SETTINGS_LOADED = OK")
        print("CHAT_MODEL =", settings.chat_model)
        print("TIMEZONE =", settings.timezone, "| DIGEST_TIME =", settings.digest_time)
        print("NOTION_DB_IDS populated =", sum(1 for v in settings.notion_db_ids.values() if v), "of", len(settings.notion_db_ids))
        try:
            settings.chat_credentials()
            print("CHAT_CREDENTIALS = OK")
        except Exception as exc:  # noqa: BLE001
            print("CHAT_CREDENTIALS_ERROR =", exc)
    except Exception as exc:  # noqa: BLE001
        print("SETTINGS_ERROR =", exc)
        return 1

    async def live_checks() -> None:
        print("--- Live checks ---")
        try:
            from telegram import Bot

            me = await Bot(settings.telegram_bot_token).get_me()
            print("TELEGRAM_OK = @", me.username, "| id", me.id)
        except Exception as exc:  # noqa: BLE001
            print("TELEGRAM_ERROR =", exc)

        try:
            from notion_client import AsyncClient

            nc = AsyncClient(auth=settings.notion_api_key)
            try:
                user = await nc.users.me()
                print("NOTION_OK =", user.get("type"), "|", user.get("name", ""))
            except Exception:
                resp = await nc.search(query="__auth_check__", page_size=1)
                print("NOTION_OK = search returned", len(resp.get("results", [])), "results")

            print("--- Notion DB access ---")
            for db_key, db_id in settings.notion_db_ids.items():
                if not db_id:
                    print(f"{db_key}: SKIP (no id)")
                    continue
                try:
                    resp = await nc.databases.query(database_id=db_id, page_size=5)
                    rows = resp.get("results", [])
                    first = ""
                    if rows:
                        for v in rows[0].get("properties", {}).values():
                            if v.get("type") == "title":
                                first = "".join(p.get("plain_text", "") for p in v.get("title", []))
                                break
                    print(f"{db_key}: OK rows(shown {len(rows)}) e.g. '{first}'")
                except Exception as exc:  # noqa: BLE001
                    print(f"{db_key}: ERROR {type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            print("NOTION_ERROR =", exc)

    asyncio.run(live_checks())
    return 0


if __name__ == "__main__":
    sys.exit(main())

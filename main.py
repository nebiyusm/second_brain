"""Entrypoint for the Second Brain Telegram bot."""
from __future__ import annotations

import logging

from config import get_settings
from second_brain.bot import build_app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("debug.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = get_settings()
    app = build_app(settings)
    app.run_polling()


if __name__ == "__main__":
    main()

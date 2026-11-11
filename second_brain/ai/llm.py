"""OpenAI-compatible async LLM client (chat + JSON + vision)."""
from __future__ import annotations

import base64
import json
from typing import Any

from openai import AsyncOpenAI

from config import Settings


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

        chat_key, chat_base = settings.chat_credentials()
        self.chat_client = AsyncOpenAI(api_key=chat_key, base_url=chat_base)

        vision_key, vision_base = settings.vision_credentials()
        self.vision_client = (
            AsyncOpenAI(api_key=vision_key, base_url=vision_base) if vision_key else None
        )

    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        resp = await self.chat_client.chat.completions.create(
            model=model or self.settings.chat_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()

    async def chat_json(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.0,
        retries: int = 2,
    ) -> dict[str, Any]:
        msgs = list(messages)
        last_err: Exception | None = None
        for _ in range(retries + 1):
            text = await self.chat(msgs, model=model, temperature=temperature)
            try:
                return parse_json(text)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                msgs = msgs + [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": "That was not valid JSON. Return ONLY a valid JSON object."},
                ]
        raise ValueError(f"Failed to parse JSON from model: {last_err}")

    async def describe_images(
        self,
        images: list[bytes],
        prompt: str,
        model: str | None = None,
    ) -> str:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for img in images:
            b64 = base64.b64encode(img).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        if self.vision_client is None:
            raise RuntimeError(
                "No vision provider configured. Set VISION_API_KEY (or OPENAI_API_KEY) "
                "with a vision-capable VISION_MODEL."
            )
        resp = await self.vision_client.chat.completions.create(
            model=model or self.settings.vision_model,
            messages=[{"role": "user", "content": content}],
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "").strip()


def parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise

"""Audio transcription with an API/local switch."""
from __future__ import annotations

import asyncio
from pathlib import Path

from openai import AsyncOpenAI

from config import Settings


async def transcribe_audio(settings: Settings, file_path: str | Path) -> str:
    path = Path(file_path)
    if settings.transcription_backend == "local":
        return await asyncio.to_thread(_transcribe_local, settings, path)
    return await _transcribe_api(settings, path)


async def _transcribe_api(settings: Settings, path: Path) -> str:
    key, base = settings.audio_credentials()
    if not key:
        raise RuntimeError(
            "No transcription provider configured. Set AUDIO_API_KEY (or OPENAI_API_KEY) "
            "with an OpenAI-compatible audio endpoint, or set TRANSCRIPTION_BACKEND=local."
        )
    client = AsyncOpenAI(api_key=key, base_url=base)
    resp = await client.audio.transcriptions.create(
        model=settings.audio_model,
        file=path,
    )
    return (resp.text or "").strip()


def _transcribe_local(settings: Settings, path: Path) -> str:
    from faster_whisper import WhisperModel  # local import: heavy dependency

    model = WhisperModel(settings.whisper_local_model, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path))
    return "".join(seg.text for seg in segments).strip()

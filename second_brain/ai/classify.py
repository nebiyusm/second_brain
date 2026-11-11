"""Message classification and disambiguation."""
from __future__ import annotations

from dataclasses import dataclass, field

from second_brain.ai import prompts
from second_brain.ai.llm import LLMClient


class CaptureType:
    IDEA = "IDEA"
    TASK = "TASK"
    NOTE_RESOURCE = "NOTE_RESOURCE"
    QUESTION = "QUESTION"
    TASK_FOR_BOT = "TASK_FOR_BOT"
    MEDIA = "MEDIA"
    UNCLEAR = "UNCLEAR"


_VALID_TYPES = {
    CaptureType.IDEA,
    CaptureType.TASK,
    CaptureType.NOTE_RESOURCE,
    CaptureType.QUESTION,
    CaptureType.TASK_FOR_BOT,
    CaptureType.MEDIA,
    CaptureType.UNCLEAR,
}


@dataclass
class Classification:
    type: str
    title: str = ""
    confidence: str = "medium"
    why: str = ""
    media_type: str = ""
    raw: dict = field(default_factory=dict)


async def classify_message(llm: LLMClient, text: str) -> Classification:
    data = await llm.chat_json([
        {"role": "system", "content": prompts.CLASSIFY_SYSTEM},
        {"role": "user", "content": text},
    ])
    ctype = str(data.get("type", CaptureType.UNCLEAR)).upper()
    if ctype not in _VALID_TYPES:
        ctype = CaptureType.UNCLEAR
    return Classification(
        type=ctype,
        title=str(data.get("title", "")).strip(),
        confidence=str(data.get("confidence", "medium")).lower(),
        why=str(data.get("why", "")).strip(),
        media_type=str(data.get("media_type", "")).strip(),
        raw=data,
    )


async def classify_intent(llm: LLMClient, text: str) -> dict:
    """Route a message to a conversational intent (for the chatbot mode)."""
    data = await llm.chat_json([
        {"role": "system", "content": prompts.INTENT_SYSTEM},
        {"role": "user", "content": text},
    ])
    intent = str(data.get("intent", "CHAT")).strip().upper()
    return {"intent": intent, "title": str(data.get("title", "")).strip()}

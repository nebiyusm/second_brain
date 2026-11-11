"""Higher-level LLM tasks: summarise, synthesize, answer, execute."""
from __future__ import annotations

from typing import Any

from second_brain.ai import prompts
from second_brain.ai.llm import LLMClient
from second_brain.notion.databases import CONTROLLED_TAGS

_CONTROLLED = set(CONTROLLED_TAGS)


def _clean_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    for t in tags:
        name = str(t).strip().lower()
        if name in _CONTROLLED and name not in out:
            out.append(name)
        if len(out) >= 3:
            break
    return out


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


async def summarize_resource(llm: LLMClient, text: str) -> dict[str, Any]:
    data = await llm.chat_json([
        {"role": "system", "content": prompts.SUMMARIZE_RESOURCE_SYSTEM},
        {"role": "user", "content": text},
    ])
    details = data.get("details", "")
    if isinstance(details, list):
        details = "\n".join(str(d) for d in details)
    return {
        "title": str(data.get("title", "")).strip() or "Note",
        "tldr": str(data.get("tldr", "")).strip(),
        "tags": _clean_tags(data.get("tags")),
        "key_points": _as_str_list(data.get("key_points")),
        "details": str(details).strip(),
    }


async def synthesize_video_note(
    llm: LLMClient,
    transcript: str,
    frame_descriptions: str,
    caption: str,
    creator: str,
    source_url: str,
) -> dict[str, Any]:
    user = (
        f"TRANSCRIPT:\n{transcript}\n\n"
        f"FRAME DESCRIPTIONS:\n{frame_descriptions}\n\n"
        f"CAPTION:\n{caption}\n\n"
        f"CREATOR: {creator}\nURL: {source_url}"
    )
    data = await llm.chat_json([
        {"role": "system", "content": prompts.SYNTHESIZE_VIDEO_SYSTEM},
        {"role": "user", "content": user},
    ])
    key_points = _as_str_list(data.get("key_points"))
    details = data.get("details", "")
    if isinstance(details, list):
        details = "\n".join(str(d) for d in details)
    return {
        "title": str(data.get("title", "")).strip() or "Video note",
        "tldr": str(data.get("tldr", "")).strip(),
        "tags": _clean_tags(data.get("tags")),
        "key_points": key_points,
        "details": str(details).strip(),
        "creator": str(data.get("creator", "")).strip(),
        "summary_line": str(data.get("summary_line", "")).strip(),
    }


async def answer_question(llm: LLMClient, question: str, context_entries: list[dict]) -> str:
    if not context_entries:
        return ""
    lines: list[str] = []
    for i, entry in enumerate(context_entries, 1):
        lines.append(f"[{i}] {entry.get('title', 'Untitled')}\n{entry.get('snippet', '')}")
    context = "\n\n".join(lines)
    return await llm.chat([
        {"role": "system", "content": prompts.ANSWER_SYSTEM},
        {"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION:\n{question}"},
    ])


async def execute_instruction(llm: LLMClient, instruction: str, context: str) -> dict[str, Any]:
    data = await llm.chat_json([
        {"role": "system", "content": prompts.EXECUTE_SYSTEM},
        {"role": "user", "content": f"EXISTING CONTEXT:\n{context or '(none)'}\n\nINSTRUCTION:\n{instruction}"},
    ])
    return {
        "title": str(data.get("title", "")).strip() or "Deliverable",
        "body": str(data.get("body", "")).strip(),
        "destination": str(data.get("destination", "resource")).strip().lower(),
        "project_name": str(data.get("project_name", "")).strip(),
        "tags": _clean_tags(data.get("tags")),
        "reply": str(data.get("reply", "")).strip(),
    }

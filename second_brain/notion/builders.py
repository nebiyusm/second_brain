"""Property and block builders for Notion pages."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable


# --------------------------------------------------------------------------- #
# Property builders
# --------------------------------------------------------------------------- #
def title_prop(text: str) -> dict:
    return {"title": [{"text": {"content": text}}]}


def rich_text_prop(text: str) -> dict:
    return {"rich_text": [{"text": {"content": text}}]}


def select_prop(name: str | None) -> dict:
    if not name:
        return {"select": None}
    return {"select": {"name": name}}


def multi_select_prop(names: Iterable[str]) -> dict:
    return {"multi_select": [{"name": n} for n in names]}


def date_prop(value: str | date | datetime | None) -> dict:
    if not value:
        return {"date": None}
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        value = value.isoformat()
    return {"date": {"start": value}}


def number_prop(value: float | int | None) -> dict:
    return {"number": value}


def relation_prop(page_ids: Iterable[str]) -> dict:
    return {"relation": [{"id": pid} for pid in page_ids]}


def checkbox_prop(value: bool) -> dict:
    return {"checkbox": value}


def url_prop(value: str) -> dict:
    return {"url": value}


# --------------------------------------------------------------------------- #
# Block builders
# --------------------------------------------------------------------------- #
def _rt(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text}}]


def heading_2(text: str) -> dict:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rt(text)}}


def heading_3(text: str) -> dict:
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": _rt(text)}}


def paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rt(text)}}


def bulleted(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rt(text)}}


def numbered(text: str) -> dict:
    return {"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": _rt(text)}}


def callout(text: str, icon: str | None = None) -> dict:
    block: dict[str, Any] = {
        "object": "block",
        "type": "callout",
        "callout": {"rich_text": _rt(text)},
    }
    if icon:
        block["callout"]["icon"] = {"type": "emoji", "emoji": icon}
    return block


def quote(text: str) -> dict:
    return {"object": "block", "type": "quote", "quote": {"rich_text": _rt(text)}}


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def image_block(url: str, caption: str = "") -> dict:
    block: dict[str, Any] = {
        "object": "block",
        "type": "image",
        "image": {"type": "external", "external": {"url": url}},
    }
    if caption:
        block["image"]["caption"] = _rt(caption)
    return block


def link_block(url: str, text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text, "link": {"url": url}}}]},
    }


# --------------------------------------------------------------------------- #
# Content page format: opens with "## TL;DR" then structured sections.
# --------------------------------------------------------------------------- #
def build_content_children(
    tldr: str,
    sections: list[tuple[str, str | list[str]]] | None = None,
) -> list[dict]:
    """Build a page body that opens with a TL;DR heading and then sections.

    ``sections`` is a list of (heading, body) where body is either a plain
    string (rendered as a paragraph) or a list of strings (rendered as bullets).
    """
    children: list[dict] = [heading_2("TL;DR"), paragraph(tldr)]
    for title, body in sections or []:
        children.append(heading_2(title))
        if isinstance(body, str):
            children.append(paragraph(body))
        else:
            for item in body:
                children.append(bulleted(item))
    return children


def emoji_icon(emoji: str) -> dict:
    return {"type": "emoji", "emoji": emoji}


def link_to_page_block(page_id: str) -> dict:
    return {
        "object": "block",
        "type": "link_to_page",
        "link_to_page": {"type": "page_id", "page_id": page_id},
    }


def md_to_blocks(md: str) -> list[dict]:
    """Convert simple Markdown into Notion blocks (headings, bullets, paragraphs)."""
    blocks: list[dict] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            blocks.append(heading_3(line[4:]))
        elif line.startswith("## "):
            blocks.append(heading_2(line[3:]))
        elif line.startswith("# "):
            blocks.append(heading_2(line[2:]))
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append(bulleted(line[2:]))
        elif line.startswith("> "):
            blocks.append(quote(line[2:]))
        else:
            blocks.append(paragraph(line))
    return blocks


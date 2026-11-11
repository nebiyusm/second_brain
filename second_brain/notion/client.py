"""Thin async wrapper around the Notion SDK."""
from __future__ import annotations

from typing import Any, Iterable

from notion_client import AsyncClient

from config import Settings


class NotionClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncClient(auth=settings.notion_api_key)
        self._schema_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------ #
    # Low-level primitives
    # ------------------------------------------------------------------ #
    async def create_page(
        self,
        parent: dict,
        properties: dict,
        children: list[dict] | None = None,
        icon: dict | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"parent": parent, "properties": properties}
        if children:
            payload["children"] = children
        if icon:
            payload["icon"] = icon
        return await self.client.pages.create(**payload)

    async def create_page_in_db(
        self,
        database_id: str,
        properties: dict,
        children: list[dict] | None = None,
        icon: dict | None = None,
    ) -> dict:
        properties = await self._sanitize_properties(database_id, properties)
        return await self.create_page({"database_id": database_id}, properties, children, icon)

    async def get_schema(self, database_id: str) -> dict:
        if database_id not in self._schema_cache:
            db = await self.client.databases.retrieve(database_id=database_id)
            self._schema_cache[database_id] = db.get("properties", {})
        return self._schema_cache[database_id]

    async def _sanitize_properties(self, database_id: str, properties: dict) -> dict:
        """Drop unknown properties/options and rename the title property.

        Your live Notion schema may differ from the code's assumptions, so we
        keep only properties that actually exist, and move a title-shaped value
        under the database's real title property name.
        """
        schema = await self.get_schema(database_id)

        title_name: str | None = None
        for name, prop in schema.items():
            if prop.get("type") == "title":
                title_name = name
                break

        cleaned: dict = {}
        for key, value in properties.items():
            prop_def = schema.get(key)
            if prop_def is None:
                if title_name and isinstance(value, dict) and "title" in value:
                    cleaned[title_name] = value
                continue

            ptype = prop_def.get("type")

            if ptype == "select" and isinstance(value, dict):
                sel = value.get("select")
                if sel and sel.get("name"):
                    opts = [o.get("name") for o in prop_def.get("select", {}).get("options", [])]
                    if opts and sel["name"] not in opts:
                        continue

            if ptype == "multi_select" and isinstance(value, dict):
                ms = value.get("multi_select", [])
                opts = {o.get("name") for o in prop_def.get("multi_select", {}).get("options", [])}
                valid = [m for m in ms if not opts or m.get("name") in opts]
                if opts and not valid:
                    continue
                value = dict(value)
                value["multi_select"] = valid

            cleaned[key] = value

        return cleaned

    async def create_child_page(
        self,
        parent_page_id: str,
        properties: dict,
        children: list[dict] | None = None,
        icon: dict | None = None,
    ) -> dict:
        return await self.create_page({"page_id": parent_page_id}, properties, children, icon)

    async def query_database(
        self,
        database_id: str,
        filter: dict | None = None,
        sorts: list[dict] | None = None,
        page_size: int = 100,
    ) -> list[dict]:
        results: list[dict] = []
        payload: dict[str, Any] = {"database_id": database_id, "page_size": page_size}
        if filter is not None:
            payload["filter"] = filter
        if sorts is not None:
            payload["sorts"] = sorts

        cursor: str | None = None
        while True:
            kwargs = dict(payload)
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = await self.client.databases.query(**kwargs)
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results

    async def get_page(self, page_id: str) -> dict:
        return await self.client.pages.retrieve(page_id=page_id)

    async def update_page(self, page_id: str, properties: dict) -> dict:
        return await self.client.pages.update(page_id=page_id, properties=properties)


    async def get_blocks(self, block_id: str) -> list[dict]:
        results: list[dict] = []
        cursor: str | None = None
        while True:
            kwargs = {"block_id": block_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = await self.client.blocks.children.list(**kwargs)
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results

    async def append_blocks(self, block_id: str, children: list[dict]) -> dict:
        return await self.client.blocks.children.append(block_id=block_id, children=children)

    async def search(
        self,
        query: str,
        filter: dict | None = None,
        page_size: int = 100,
    ) -> list[dict]:
        results: list[dict] = []
        payload: dict[str, Any] = {"query": query, "page_size": page_size}
        if filter is not None:
            payload["filter"] = filter

        cursor: str | None = None
        while True:
            kwargs = dict(payload)
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = await self.client.search(**kwargs)
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results

    # ------------------------------------------------------------------ #
    # Convenience helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def page_url(page: dict) -> str:
        return page.get("url", "")

    @staticmethod
    def page_id(page: dict) -> str:
        return page.get("id", "")

    @staticmethod
    def title_of(page: dict) -> str:
        """Best-effort extraction of a page's title property."""
        props = page.get("properties", {})
        for value in props.values():
            if value.get("type") == "title":
                parts = value.get("title", [])
                text = "".join(p.get("plain_text", "") for p in parts)
                if text:
                    return text
        for key in ("Name", "Title", "title"):
            value = props.get(key)
            if value and value.get("type") == "title":
                parts = value.get("title", [])
                text = "".join(p.get("plain_text", "") for p in parts)
                if text:
                    return text
        return "Untitled"

    @staticmethod
    def blocks_to_text(blocks: list[dict]) -> str:
        """Flatten a list of blocks into readable plain text (for search context)."""
        lines: list[str] = []
        for block in blocks:
            btype = block.get("type", "")
            rich = _rich_texts(block.get(btype, {}))
            if rich:
                lines.append(" ".join(rich))
        return "\n".join(lines)

    @staticmethod
    def property_text(page: dict, name: str) -> str:
        prop = page.get("properties", {}).get(name, {})
        if not prop:
            return ""
        ptype = prop.get("type", "")
        if ptype == "title":
            return "".join(p.get("plain_text", "") for p in prop.get("title", []))
        if ptype == "rich_text":
            return "".join(p.get("plain_text", "") for p in prop.get("rich_text", []))
        if ptype == "select":
            return prop.get("select", {}).get("name", "") if prop.get("select") else ""
        if ptype == "multi_select":
            return ", ".join(o.get("name", "") for o in prop.get("multi_select", []))
        if ptype == "date":
            d = prop.get("date")
            return d.get("start", "") if d else ""
        if ptype == "number":
            v = prop.get("number")
            return str(v) if v is not None else ""
        if ptype == "relation":
            return ", ".join(r.get("id", "") for r in prop.get("relation", []))
        return ""


def _rich_texts(block_value: dict) -> list[str]:
    texts: list[str] = []
    rt = block_value.get("rich_text", [])
    if isinstance(rt, list):
        for part in rt:
            if isinstance(part, dict):
                texts.append(part.get("plain_text", ""))
    return texts


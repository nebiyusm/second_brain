"""Dump each Notion database's property names and types (no secrets)."""
import asyncio

from config import Settings
from notion_client import AsyncClient


async def main() -> None:
    settings = Settings()
    nc = AsyncClient(auth=settings.notion_api_key)
    for key, db_id in settings.notion_db_ids.items():
        if not db_id:
            print(f"=== {key} === (no id)")
            continue
        db = await nc.databases.retrieve(database_id=db_id)
        props = db.get("properties", {})
        print(f"=== {key} ===")
        for name, prop in props.items():
            t = prop.get("type")
            if t in ("select", "multi_select", "status"):
                opts = prop.get(t, {})
                print(f"  {name}: {t} -> {opts}")
            else:
                print(f"  {name}: {t}")
    await nc.aclose()


asyncio.run(main())

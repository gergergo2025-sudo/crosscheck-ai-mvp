"""Explicit deployment migration entry point."""
import asyncio
from .config import get_settings
from .persistence import Database

async def _main() -> None:
    database = Database(get_settings().database_url)
    await database.initialize()
    await database.migrate()
    await database.dispose()

if __name__ == "__main__":
    asyncio.run(_main())

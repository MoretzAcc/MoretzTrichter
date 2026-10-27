from __future__ import annotations

import asyncio

from moretztrichter.database import Database
from moretztrichter.settings import Settings


async def initialize_database() -> None:
    settings = Settings.from_environment()
    database = Database(settings.database_url)
    await database.connect()
    try:
        await database.apply_migrations()
    finally:
        await database.close()


def main() -> None:
    asyncio.run(initialize_database())

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import asyncpg

from moretztrichter.normalize import NormalizedBatch


class BatchConflictError(Exception):
    """A batch id was reused with a different normalized payload."""


class Database:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=10)

    async def apply_migrations(self) -> None:
        """Apply pending SQL migrations. This is called only by the init command."""
        pool = self._require_pool()
        migration_dir = Path(__file__).parents[2] / "migrations"
        async with pool.acquire() as connection:
            await connection.execute("SELECT pg_advisory_lock(803241781)")
            try:
                await connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migration "
                    "(name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                for migration in sorted(migration_dir.glob("*.sql")):
                    applied = await connection.fetchval(
                        "SELECT 1 FROM schema_migration WHERE name = $1", migration.name
                    )
                    if applied is None:
                        async with connection.transaction():
                            await connection.execute(migration.read_text(encoding="utf-8"))
                            await connection.execute(
                                "INSERT INTO schema_migration (name) VALUES ($1)", migration.name
                            )
            finally:
                await connection.execute("SELECT pg_advisory_unlock(803241781)")

    async def ensure_schema_ready(self) -> None:
        """Fail startup until all bundled migrations were applied manually."""
        migration_dir = Path(__file__).parents[2] / "migrations"
        expected_names = {migration.name for migration in migration_dir.glob("*.sql")}
        pool = self._require_pool()
        async with pool.acquire() as connection:
            schema_exists = await connection.fetchval(
                "SELECT to_regclass('public.schema_migration') IS NOT NULL"
            )
            if not schema_exists:
                raise RuntimeError("database schema is not initialized; run moretztrichter-init-db")
            rows = await connection.fetch("SELECT name FROM schema_migration")
        applied_names = {str(row["name"]) for row in rows}
        missing_names = expected_names - applied_names
        if missing_names:
            raise RuntimeError("database schema has pending migrations; run moretztrichter-init-db")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("database is not connected")
        return self._pool

    async def ping(self) -> None:
        await self._require_pool().fetchval("SELECT 1")

    async def ingest(self, batch: NormalizedBatch) -> tuple[bool, int, int]:
        """Store a batch atomically and return duplicate status and sample counts."""
        pool = self._require_pool()
        async with pool.acquire() as connection, connection.transaction():
            inserted_batch = await connection.fetchval(
                """
                INSERT INTO ingest_batch (batch_id, payload_hash) VALUES ($1, $2)
                ON CONFLICT (batch_id) DO NOTHING RETURNING payload_hash
                """,
                batch.batch_id,
                batch.payload_hash,
            )
            if inserted_batch is None:
                stored_hash = await connection.fetchval(
                    "SELECT payload_hash FROM ingest_batch WHERE batch_id = $1", batch.batch_id
                )
                if stored_hash != batch.payload_hash:
                    raise BatchConflictError
                return True, 0, 0

            series_ids: dict[str, int] = {}
            for channel_name, unit in batch.channels:
                series_id = await connection.fetchval(
                    """
                    INSERT INTO series (device_identifier, channel_name, device_name, unit)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (device_identifier, channel_name) DO UPDATE SET
                        device_name = COALESCE(EXCLUDED.device_name, series.device_name),
                        unit = COALESCE(EXCLUDED.unit, series.unit),
                        last_seen_at = now()
                    RETURNING id
                    """,
                    batch.device_identifier,
                    channel_name,
                    batch.device_name,
                    unit,
                )
                series_ids[channel_name] = int(series_id)

            rows: list[tuple[datetime, int, float | None]] = []
            for item in batch.samples.iter_rows(named=True):
                rows.append(
                    (
                        datetime.fromisoformat(str(item["time"]).replace("Z", "+00:00")),
                        series_ids[str(item["channel"])],
                        item["value"],
                    )
                )
            stored = await connection.fetch(
                """
                INSERT INTO measurement (time, series_id, value)
                SELECT * FROM unnest($1::timestamptz[], $2::bigint[], $3::double precision[])
                ON CONFLICT (series_id, time) DO NOTHING
                RETURNING series_id
                """,
                [row[0] for row in rows],
                [row[1] for row in rows],
                [row[2] for row in rows],
            )
            inserted = len(stored)
            discarded = len(rows) - inserted + batch.local_duplicates
            return False, inserted, discarded

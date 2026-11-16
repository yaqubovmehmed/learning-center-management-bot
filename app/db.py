"""Yengil SQLite qatlami (aiosqlite).

Bitta ulanish + qulf: kichik va o'rta markaz uchun tez va xavfsiz.
WAL rejimi, foreign keys, busy timeout yoqilgan.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Sequence

import aiosqlite

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Tx:
    """Tranzaksiya ichida ishlatiladigan yordamchi (qulfsiz)."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Cursor:
        return await self.conn.execute(sql, params)

    async def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> aiosqlite.Cursor:
        return await self.conn.executemany(sql, seq)

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        cur = await self.conn.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cur = await self.conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]

    async def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = await self.conn.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return row[0] if row else None


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database ulanmagan")
        return self._conn

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA temp_store=MEMORY")
        await self._conn.execute("PRAGMA cache_size=-8000")
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        await self._conn.executescript(schema)
        await self._conn.commit()
        await self._seed_defaults()

    async def _seed_defaults(self) -> None:
        from config import settings

        defaults = {
            "center_name": settings.center_name or "Excellence LC",
            "support_username": "",
            "auto_absence_notify": "1",
            "auto_result_notify": "1",
            "digest_enabled": "1",
            "digest_weekday": str(settings.digest_weekday),
            "digest_hour": str(settings.digest_hour),
            "attendance_threshold": "75",
            "inline_public": "1",
            "last_digest_date": "",
            "schema_version": "1",
        }
        now = utc_now()
        async with self._lock:
            await self.conn.executemany(
                "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES(?, ?, ?)",
                [(k, v, now) for k, v in defaults.items()],
            )
            await self.conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            await self._conn.close()
            self._conn = None

    # ---- qulflangan ommaviy metodlar ----
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Cursor:
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            await self.conn.commit()
            return cur

    async def execute_insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            await self.conn.commit()
            last = cur.lastrowid or 0
            await cur.close()
            return int(last)

    async def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> None:
        async with self._lock:
            await self.conn.executemany(sql, seq)
            await self.conn.commit()

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            row = await cur.fetchone()
            await cur.close()
            return dict(row) if row else None

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            rows = await cur.fetchall()
            await cur.close()
            return [dict(r) for r in rows]

    async def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            row = await cur.fetchone()
            await cur.close()
            return row[0] if row else None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Tx]:
        async with self._lock:
            await self.conn.execute("BEGIN IMMEDIATE")
            tx = Tx(self.conn)
            try:
                yield tx
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback()
                raise

    async def backup(self, target: Path) -> Path:
        """VACUUM INTO orqali izchil nusxa (fayl mavjud bo'lmasligi kerak)."""
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        async with self._lock:
            # SQL parametri bilan xavfsiz
            await self.conn.execute("VACUUM INTO ?", (str(target),))
        return target

    async def integrity_ok(self) -> bool:
        result = await self.scalar("PRAGMA integrity_check")
        return result == "ok"

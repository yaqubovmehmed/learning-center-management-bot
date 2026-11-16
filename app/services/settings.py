"""Sozlamalar xizmati (kichik TTL kesh bilan)."""
from __future__ import annotations

import time
from typing import Any

from app.db import Database, utc_now

_CACHE: tuple[float, dict[str, str]] | None = None
_TTL = 10.0


async def all_settings(db: Database, force: bool = False) -> dict[str, str]:
    global _CACHE
    now = time.monotonic()
    if not force and _CACHE and now - _CACHE[0] < _TTL:
        return _CACHE[1]
    rows = await db.fetchall("SELECT key, value FROM settings")
    data = {row["key"]: row["value"] for row in rows}
    _CACHE = (now, data)
    return data


async def get(db: Database, key: str, default: str = "") -> str:
    data = await all_settings(db)
    return data.get(key, default)


async def get_int(db: Database, key: str, default: int = 0) -> int:
    try:
        return int(await get(db, key, str(default)))
    except ValueError:
        return default


async def get_bool(db: Database, key: str, default: bool = False) -> bool:
    return (await get(db, key, "1" if default else "0")) == "1"


async def set_value(db: Database, key: str, value: Any) -> None:
    global _CACHE
    await db.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, str(value), utc_now()),
    )
    _CACHE = None


def invalidate_cache() -> None:
    global _CACHE
    _CACHE = None

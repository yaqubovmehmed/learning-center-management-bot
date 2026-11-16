"""Foydalanuvchilar (Telegram akkauntlari) xizmati."""
from __future__ import annotations

from typing import Any

from app.db import Database, utc_now


async def by_tg(db: Database, tg_id: int) -> dict[str, Any] | None:
    return await db.fetchone("SELECT * FROM users WHERE tg_id=?", (tg_id,))


async def by_id(db: Database, user_id: int) -> dict[str, Any] | None:
    return await db.fetchone("SELECT * FROM users WHERE id=?", (user_id,))


async def create_user(
    db: Database,
    *,
    tg_id: int,
    role: str,
    full_name: str,
    username: str | None = None,
    phone: str | None = None,
) -> int:
    return await db.execute_insert(
        "INSERT INTO users(tg_id, role, full_name, username, phone, created_at, last_seen) "
        "VALUES(?,?,?,?,?,?,?)",
        (tg_id, role, full_name, username, phone, utc_now(), utc_now()),
    )


async def touch(db: Database, user_id: int, username: str | None = None) -> None:
    await db.execute("UPDATE users SET last_seen=?, username=COALESCE(?, username) WHERE id=?", (utc_now(), username, user_id))


async def set_role(db: Database, user_id: int, role: str) -> None:
    await db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))


async def set_active(db: Database, user_id: int, active: bool) -> None:
    await db.execute("UPDATE users SET is_active=? WHERE id=?", (1 if active else 0, user_id))


async def set_name(db: Database, user_id: int, name: str) -> None:
    await db.execute("UPDATE users SET full_name=? WHERE id=?", (name, user_id))


async def ensure_env_superadmins(db: Database, ids: tuple[int, ...]) -> int:
    """Envda ko'rsatilgan IDlarni super admin qiladi (mavjudni ko'taradi)."""
    count = 0
    for tg_id in ids:
        row = await by_tg(db, tg_id)
        if row:
            if row["role"] != "superadmin" or not row["is_active"]:
                await db.execute(
                    "UPDATE users SET role='superadmin', is_active=1 WHERE id=?",
                    (row["id"],),
                )
                count += 1
        else:
            name = f"Superadmin {tg_id}"
            await create_user(db, tg_id=tg_id, role="superadmin", full_name=name)
            count += 1
    return count


async def superadmin_count(db: Database) -> int:
    return int(await db.scalar("SELECT COUNT(*) FROM users WHERE role='superadmin' AND is_active=1") or 0)


async def list_by_role(db: Database, role: str) -> list[dict[str, Any]]:
    return await db.fetchall("SELECT * FROM users WHERE role=? AND is_active=1 ORDER BY full_name", (role,))


async def parents_without_link(db: Database) -> list[dict[str, Any]]:
    return await db.fetchall(
        "SELECT p.*, (SELECT COUNT(*) FROM student_parents sp WHERE sp.parent_id=p.id) AS children_count "
        "FROM parents p WHERE p.user_id IS NULL ORDER BY p.created_at DESC"
    )

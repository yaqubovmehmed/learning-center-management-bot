"""Bir martalik taklif havolalari (ota-onalar va o'qituvchilar uchun).

Xavfsizlik:
- token 32 bayt random, bazada faqat HMAC-SHA256 hash saqlanadi;
- 72 soat amal qiladi, bir marta ishlaydi;
- telefon egaligi Telegram contact orqali tasdiqlanadi;
- yangi havola yaratilganda eski ishlatilmagan havola bekor qilinadi.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import Database, utc_now
from app.security import hash_token, make_token
from app.services import users

INVITE_TTL_HOURS = 72


async def create_invite(
    db: Database,
    *,
    role: str,
    target_id: int,
    created_by: int | None,
    pepper: bytes,
    ttl_hours: int = INVITE_TTL_HOURS,
) -> tuple[str, int]:
    if role not in ("teacher", "parent"):
        raise ValueError("Noto'g'ri rol")
    token = make_token()
    token_hash = hash_token(token, pepper)
    now = utc_now()
    expires = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).strftime("%Y-%m-%d %H:%M:%S")
    async with db.transaction() as tx:
        # eski ishlatilmagan havolalarni bekor qilamiz
        await tx.execute(
            "UPDATE invites SET used_at=? WHERE role=? AND target_id=? AND used_at IS NULL",
            (now, role, target_id),
        )
        cur = await tx.execute(
            "INSERT INTO invites(token_hash, role, target_id, created_by, expires_at, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (token_hash, role, target_id, created_by, expires, now),
        )
        invite_id = int(cur.lastrowid or 0)
    return token, invite_id


async def find_valid(db: Database, *, token: str, role: str, pepper: bytes) -> dict[str, Any] | None:
    token_hash = hash_token(token, pepper)
    row = await db.fetchone(
        "SELECT * FROM invites WHERE token_hash=? AND role=? AND used_at IS NULL AND expires_at>?",
        (token_hash, role, utc_now()),
    )
    return row


async def revoke_for_target(db: Database, role: str, target_id: int) -> None:
    await db.execute(
        "UPDATE invites SET used_at=? WHERE role=? AND target_id=? AND used_at IS NULL",
        (utc_now(), role, target_id),
    )


async def bind_parent(
    db: Database,
    *,
    invite: dict[str, Any],
    tg_id: int,
    tg_name: str,
    username: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Ota-ona akkauntini bog'laydi. (parent, error) qaytaradi."""
    parent = await db.fetchone("SELECT * FROM parents WHERE id=?", (invite["target_id"],))
    if not parent:
        return None, "Ota-ona topilmadi."
    existing_user = await users.by_tg(db, tg_id)
    if existing_user and existing_user["role"] not in ("parent",):
        return None, "Bu Telegram akkaunt boshqa rol bilan ro'yxatdan o'tgan."
    if parent.get("user_id"):
        bound = await users.by_id(db, int(parent["user_id"]))
        if bound and bound["tg_id"] != tg_id:
            return None, "Bu ota-ona boshqa Telegram akkauntga ulangan."
    now = utc_now()
    async with db.transaction() as tx:
        cur = await tx.execute(
            "UPDATE invites SET used_at=?, used_by=? WHERE id=? AND used_at IS NULL",
            (now, tg_id, invite["id"]),
        )
        if cur.rowcount != 1:
            return None, "Havola allaqachon ishlatilgan."
        if existing_user:
            user_id = int(existing_user["id"])
            await tx.execute(
                "UPDATE users SET role='parent', is_active=1, full_name=?, username=?, last_seen=? WHERE id=?",
                (parent["full_name"], username, now, user_id),
            )
        else:
            cur = await tx.execute(
                "INSERT INTO users(tg_id, role, full_name, username, phone, created_at, last_seen) "
                "VALUES(?, 'parent', ?, ?, ?, ?, ?)",
                (tg_id, parent["full_name"], username, parent["phone"], now, now),
            )
            user_id = int(cur.lastrowid or 0)
        await tx.execute("UPDATE parents SET user_id=? WHERE id=?", (user_id, parent["id"]))
    return await db.fetchone(
        "SELECT p.*, u.tg_id FROM parents p JOIN users u ON u.id=p.user_id WHERE p.id=?",
        (parent["id"],),
    ), None


async def bind_teacher(
    db: Database,
    *,
    invite: dict[str, Any],
    tg_id: int,
    tg_name: str,
    username: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    teacher = await db.fetchone("SELECT * FROM teachers WHERE id=?", (invite["target_id"],))
    if not teacher:
        return None, "O'qituvchi topilmadi."
    existing_user = await users.by_tg(db, tg_id)
    if existing_user and existing_user["role"] not in ("teacher",):
        return None, "Bu Telegram akkaunt boshqa rol bilan ro'yxatdan o'tgan."
    if teacher.get("user_id"):
        bound = await users.by_id(db, int(teacher["user_id"]))
        if bound and bound["tg_id"] != tg_id:
            return None, "Bu o'qituvchi boshqa Telegram akkauntga ulangan."
    now = utc_now()
    async with db.transaction() as tx:
        cur = await tx.execute(
            "UPDATE invites SET used_at=?, used_by=? WHERE id=? AND used_at IS NULL",
            (now, tg_id, invite["id"]),
        )
        if cur.rowcount != 1:
            return None, "Havola allaqachon ishlatilgan."
        if existing_user:
            user_id = int(existing_user["id"])
            await tx.execute(
                "UPDATE users SET role='teacher', is_active=1, full_name=?, username=?, last_seen=? WHERE id=?",
                (teacher["name"], username, now, user_id),
            )
        else:
            cur = await tx.execute(
                "INSERT INTO users(tg_id, role, full_name, username, phone, created_at, last_seen) "
                "VALUES(?, 'teacher', ?, ?, ?, ?, ?)",
                (tg_id, teacher["name"], username, teacher["phone"], now, now),
            )
            user_id = int(cur.lastrowid or 0)
        await tx.execute("UPDATE teachers SET user_id=?, is_active=1 WHERE id=?", (user_id, teacher["id"]))
    return await db.fetchone(
        "SELECT t.*, u.tg_id FROM teachers t JOIN users u ON u.id=t.user_id WHERE t.id=?",
        (teacher["id"],),
    ), None

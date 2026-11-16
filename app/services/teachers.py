"""O'qituvchilar bilan ishlash."""
from __future__ import annotations

from typing import Any

from app.db import Database, utc_now

TEACHER_SELECT = """
SELECT t.*, u.tg_id, u.username, u.is_active AS user_active,
       (SELECT COUNT(*) FROM groups g WHERE g.teacher_id=t.id AND g.status='active') AS groups_count,
       (SELECT COUNT(*) FROM students s JOIN groups g ON g.id=s.group_id
          WHERE g.teacher_id=t.id AND g.status='active' AND s.status='active') AS students_count
FROM teachers t
LEFT JOIN users u ON u.id=t.user_id
"""


async def get_teacher(db: Database, teacher_id: int) -> dict[str, Any] | None:
    return await db.fetchone(TEACHER_SELECT + " WHERE t.id=?", (teacher_id,))


async def by_user(db: Database, user_id: int) -> dict[str, Any] | None:
    return await db.fetchone(TEACHER_SELECT + " WHERE t.user_id=?", (user_id,))


async def by_phone(db: Database, phone: str) -> dict[str, Any] | None:
    return await db.fetchone(TEACHER_SELECT + " WHERE t.phone=?", (phone,))


async def list_teachers(db: Database, include_inactive: bool = False) -> list[dict[str, Any]]:
    sql = TEACHER_SELECT
    params: list[Any] = []
    if not include_inactive:
        sql += " WHERE t.is_active=1"
    sql += " ORDER BY t.is_active DESC, t.name"
    return await db.fetchall(sql, params)


async def create_teacher(
    db: Database,
    *,
    name: str,
    phone: str | None,
    subject: str = "English",
    user_id: int | None = None,
    notes: str | None = None,
) -> int:
    return await db.execute_insert(
        "INSERT INTO teachers(user_id, name, phone, subject, hired_at, is_active, notes, created_at) "
        "VALUES(?,?,?,?,?,1,?,?)",
        (user_id, name, phone, subject, utc_now()[:10], notes, utc_now()),
    )


async def update_teacher(db: Database, teacher_id: int, **fields: Any) -> None:
    allowed = {"name", "phone", "subject", "is_active", "notes", "user_id"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{key}=?" for key in updates)
    await db.execute(f"UPDATE teachers SET {assignments} WHERE id=?", (*updates.values(), teacher_id))


async def set_active(db: Database, teacher_id: int, active: bool) -> None:
    await db.execute("UPDATE teachers SET is_active=? WHERE id=?", (1 if active else 0, teacher_id))
    teacher = await db.fetchone("SELECT user_id FROM teachers WHERE id=?", (teacher_id,))
    if teacher and teacher.get("user_id"):
        # Admin/superadmin akkauntini o'qituvchi kartasi orqali bloklab bo'lmaydi.
        await db.execute(
            "UPDATE users SET is_active=? WHERE id=? AND role='teacher'",
            (1 if active else 0, teacher["user_id"]),
        )


async def phone_taken(db: Database, phone: str, exclude_id: int | None = None) -> bool:
    if exclude_id:
        row = await db.fetchone("SELECT 1 FROM teachers WHERE phone=? AND id<>?", (phone, exclude_id))
    else:
        row = await db.fetchone("SELECT 1 FROM teachers WHERE phone=?", (phone,))
    return row is not None

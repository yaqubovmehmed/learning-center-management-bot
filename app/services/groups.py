"""Patoklar (guruhlar) bilan ishlash."""
from __future__ import annotations

from typing import Any, Sequence

from app.db import Database, utc_now

GROUP_SELECT = """
SELECT g.*, t.name AS teacher_name, t.phone AS teacher_phone, t.user_id AS teacher_user_id,
       (SELECT COUNT(*) FROM students s WHERE s.group_id=g.id AND s.status='active') AS students_count
FROM groups g
LEFT JOIN teachers t ON t.id=g.teacher_id
"""


async def get_group(db: Database, group_id: int) -> dict[str, Any] | None:
    return await db.fetchone(GROUP_SELECT + " WHERE g.id=?", (group_id,))


async def list_groups(
    db: Database,
    *,
    teacher_id: int | None = None,
    include_archived: bool = False,
    limit: int = 300,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if teacher_id is not None:
        where.append("g.teacher_id=?")
        params.append(teacher_id)
    if not include_archived:
        where.append("g.status='active'")
    sql = GROUP_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY g.status='archived', g.name LIMIT ?"
    params.append(limit)
    return await db.fetchall(sql, params)


async def create_group(db: Database, data: dict[str, Any]) -> int:
    return await db.execute_insert(
        "INSERT INTO groups(name, course, level, teacher_id, room, days, time, duration_min, "
        "start_date, end_date, monthly_fee, status, notes, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            data["name"],
            data.get("course"),
            data.get("level"),
            data.get("teacher_id"),
            data.get("room"),
            data.get("days", ""),
            data.get("time"),
            int(data.get("duration_min", 90)),
            data.get("start_date"),
            data.get("end_date"),
            data.get("monthly_fee"),
            data.get("status", "active"),
            data.get("notes"),
            utc_now(),
        ),
    )


GROUP_EDITABLE = {
    "name", "course", "level", "teacher_id", "room", "days", "time",
    "duration_min", "start_date", "end_date", "monthly_fee", "status", "notes",
}


async def update_group(db: Database, group_id: int, **fields: Any) -> None:
    updates = {k: v for k, v in fields.items() if k in GROUP_EDITABLE}
    if not updates:
        return
    assignments = ", ".join(f"{key}=?" for key in updates)
    await db.execute(
        f"UPDATE groups SET {assignments} WHERE id=?",
        (*updates.values(), group_id),
    )


async def archive_group(db: Database, group_id: int) -> None:
    await db.execute("UPDATE groups SET status='archived' WHERE id=?", (group_id,))


async def restore_group(db: Database, group_id: int) -> None:
    await db.execute("UPDATE groups SET status='active' WHERE id=?", (group_id,))


async def group_name_taken(db: Database, name: str, exclude_id: int | None = None) -> bool:
    if exclude_id:
        row = await db.fetchone("SELECT 1 FROM groups WHERE lower(name)=lower(?) AND id<>?", (name, exclude_id))
    else:
        row = await db.fetchone("SELECT 1 FROM groups WHERE lower(name)=lower(?)", (name,))
    return row is not None


async def groups_for_teacher(db: Database, teacher_id: int) -> list[dict[str, Any]]:
    return await list_groups(db, teacher_id=teacher_id)

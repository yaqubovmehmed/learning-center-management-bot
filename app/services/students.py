"""O'quvchilar va ota-onalar bilan ishlash."""
from __future__ import annotations

from typing import Any, Sequence

from app.db import Database, utc_now

STUDENT_SELECT = """
SELECT s.*, g.name AS group_name, g.teacher_id, g.days AS group_days, g.time AS group_time,
       t.name AS teacher_name, t.user_id AS teacher_user_id,
       (SELECT COUNT(*) FROM student_parents sp WHERE sp.student_id=s.id) AS parents_count
FROM students s
LEFT JOIN groups g ON g.id=s.group_id
LEFT JOIN teachers t ON t.id=g.teacher_id
"""


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def get_student(db: Database, student_id: int) -> dict[str, Any] | None:
    return await db.fetchone(STUDENT_SELECT + " WHERE s.id=?", (student_id,))


async def list_students(
    db: Database,
    *,
    group_id: int | None = None,
    teacher_id: int | None = None,
    status: str | None = "active",
    query: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if group_id is not None:
        where.append("s.group_id=?")
        params.append(group_id)
    if teacher_id is not None:
        where.append("g.teacher_id=?")
        params.append(teacher_id)
    if status and status != "all":
        where.append("s.status=?")
        params.append(status)
    if query:
        where.append("(s.full_name LIKE ? ESCAPE '\\' OR s.phone LIKE ? ESCAPE '\\')")
        params.extend([_like(query), _like(query)])
    sql = STUDENT_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.status='left', s.full_name LIMIT ?"
    params.append(limit)
    return await db.fetchall(sql, params)


async def count_students(db: Database, *, group_id: int | None = None, teacher_id: int | None = None) -> int:
    sql = (
        "SELECT COUNT(*) FROM students s LEFT JOIN groups g ON g.id=s.group_id "
        "WHERE s.status='active'"
    )
    params: list[Any] = []
    if group_id is not None:
        sql += " AND s.group_id=?"
        params.append(group_id)
    if teacher_id is not None:
        sql += " AND g.teacher_id=?"
        params.append(teacher_id)
    return int(await db.scalar(sql, params) or 0)


async def create_student(
    db: Database,
    *,
    full_name: str,
    phone: str | None,
    group_id: int | None,
    created_by: int | None,
    parent_name: str | None = None,
    parent_phone: str | None = None,
    notes: str | None = None,
    birth_date: str | None = None,
) -> tuple[int, int | None]:
    """O'quvchi va (ixtiyoriy) ota-onani bitta tranzaksiyada yaratadi."""
    now = utc_now()
    async with db.transaction() as tx:
        cur = await tx.execute(
            "INSERT INTO students(full_name, phone, birth_date, group_id, status, joined_at, notes, created_at, created_by) "
            "VALUES(?,?,?,?,'active',?,?,?,?)",
            (full_name, phone, birth_date, group_id, now[:10], notes, now, created_by),
        )
        student_id = int(cur.lastrowid or 0)
        parent_id: int | None = None
        if parent_name and parent_phone:
            parent = await tx.fetchone("SELECT id FROM parents WHERE phone=?", (parent_phone,))
            if parent:
                parent_id = int(parent["id"])
            else:
                cur = await tx.execute(
                    "INSERT INTO parents(full_name, phone, created_at) VALUES(?,?,?)",
                    (parent_name, parent_phone, now),
                )
                parent_id = int(cur.lastrowid or 0)
            await tx.execute(
                "INSERT OR IGNORE INTO student_parents(student_id, parent_id, relation, is_primary) "
                "VALUES(?,?, 'ota-ona', 1)",
                (student_id, parent_id),
            )
    return student_id, parent_id


STUDENT_EDITABLE = {
    "full_name", "phone", "birth_date", "group_id", "status", "notes", "joined_at", "left_at",
}


async def update_student(db: Database, student_id: int, **fields: Any) -> None:
    updates = {k: v for k, v in fields.items() if k in STUDENT_EDITABLE}
    if not updates:
        return
    assignments = ", ".join(f"{key}=?" for key in updates)
    await db.execute(f"UPDATE students SET {assignments} WHERE id=?", (*updates.values(), student_id))


async def set_status(db: Database, student_id: int, status: str) -> None:
    left_at = utc_now()[:10] if status == "left" else None
    if status == "left":
        await db.execute("UPDATE students SET status=?, left_at=? WHERE id=?", (status, left_at, student_id))
    else:
        await db.execute("UPDATE students SET status=?, left_at=NULL WHERE id=?", (status, student_id))


async def parents_of_student(db: Database, student_id: int) -> list[dict[str, Any]]:
    return await db.fetchall(
        "SELECT p.*, u.tg_id, u.username, u.is_active AS user_active, sp.relation, sp.is_primary "
        "FROM student_parents sp JOIN parents p ON p.id=sp.parent_id "
        "LEFT JOIN users u ON u.id=p.user_id "
        "WHERE sp.student_id=? ORDER BY sp.is_primary DESC, p.id",
        (student_id,),
    )


async def get_parent(db: Database, parent_id: int) -> dict[str, Any] | None:
    return await db.fetchone(
        "SELECT p.*, u.tg_id, u.username, u.is_active AS user_active FROM parents p "
        "LEFT JOIN users u ON u.id=p.user_id WHERE p.id=?",
        (parent_id,),
    )


async def parent_by_user(db: Database, user_id: int) -> dict[str, Any] | None:
    return await get_parent_by_user_id(db, user_id)


async def get_parent_by_user_id(db: Database, user_id: int) -> dict[str, Any] | None:
    return await db.fetchone("SELECT * FROM parents WHERE user_id=?", (user_id,))


async def parent_by_phone(db: Database, phone: str) -> dict[str, Any] | None:
    return await db.fetchone("SELECT * FROM parents WHERE phone=?", (phone,))


async def children_of_parent(db: Database, parent_id: int) -> list[dict[str, Any]]:
    return await db.fetchall(
        STUDENT_SELECT.replace("FROM students s", "FROM students s JOIN student_parents sp ON sp.student_id=s.id")
        + " WHERE sp.parent_id=? ORDER BY s.status='left', s.full_name",
        (parent_id,),
    )


async def children_of_user(db: Database, user_id: int) -> list[dict[str, Any]]:
    return await db.fetchall(
        STUDENT_SELECT.replace("FROM students s", "FROM students s JOIN student_parents sp ON sp.student_id=s.id")
        + " JOIN parents p ON p.id=sp.parent_id WHERE p.user_id=? ORDER BY s.status='left', s.full_name",
        (user_id,),
    )


async def upsert_parent(db: Database, name: str, phone: str) -> int:
    existing = await parent_by_phone(db, phone)
    if existing:
        return int(existing["id"])
    return await db.execute_insert(
        "INSERT INTO parents(full_name, phone, created_at) VALUES(?,?,?)",
        (name, phone, utc_now()),
    )


async def link_parent(db: Database, student_id: int, parent_id: int, relation: str = "ota-ona", primary: bool = True) -> None:
    if primary:
        await db.execute("UPDATE student_parents SET is_primary=0 WHERE student_id=?", (student_id,))
    await db.execute(
        "INSERT INTO student_parents(student_id, parent_id, relation, is_primary) VALUES(?,?,?,?) "
        "ON CONFLICT(student_id, parent_id) DO UPDATE SET relation=excluded.relation, is_primary=excluded.is_primary",
        (student_id, parent_id, relation, 1 if primary else 0),
    )


async def unlink_parent(db: Database, student_id: int, parent_id: int) -> None:
    await db.execute(
        "DELETE FROM student_parents WHERE student_id=? AND parent_id=?",
        (student_id, parent_id),
    )


async def primary_parent(db: Database, student_id: int) -> dict[str, Any] | None:
    return await db.fetchone(
        "SELECT p.*, u.tg_id FROM student_parents sp JOIN parents p ON p.id=sp.parent_id "
        "LEFT JOIN users u ON u.id=p.user_id "
        "WHERE sp.student_id=? ORDER BY sp.is_primary DESC, p.id LIMIT 1",
        (student_id,),
    )


async def student_name_taken(db: Database, name: str, group_id: int | None, exclude_id: int | None = None) -> bool:
    sql = "SELECT 1 FROM students WHERE lower(full_name)=lower(?) AND group_id IS ? AND status<>'left'"
    params: list[Any] = [name, group_id]
    if exclude_id:
        sql += " AND id<>?"
        params.append(exclude_id)
    return await db.fetchone(sql, params) is not None

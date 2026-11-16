"""Rolga asoslangan ruxsatlar. Har bir muhim amaldan oldin tekshiriladi."""
from __future__ import annotations

from typing import Any

from app.db import Database

ADMIN_ROLES = ("superadmin", "admin")
STAFF_ROLES = ("superadmin", "admin", "teacher")


def is_admin(user: dict[str, Any] | None) -> bool:
    return bool(user and user.get("role") in ADMIN_ROLES and user.get("is_active"))


def is_superadmin(user: dict[str, Any] | None) -> bool:
    return bool(user and user.get("role") == "superadmin" and user.get("is_active"))


def is_staff(user: dict[str, Any] | None) -> bool:
    return bool(user and user.get("role") in STAFF_ROLES and user.get("is_active"))


def is_parent(user: dict[str, Any] | None) -> bool:
    return bool(user and user.get("role") == "parent" and user.get("is_active"))


async def teacher_profile(db: Database, user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not user or user.get("role") != "teacher":
        return None
    return await db.fetchone("SELECT * FROM teachers WHERE user_id=? AND is_active=1", (user["id"],))


async def group_scope(db: Database, user: dict[str, Any] | None) -> int | None:
    """Admin uchun None (hammasi), o'qituvchi uchun teacher_id, boshqalar uchun -1."""
    if is_admin(user):
        return None
    if user and user.get("role") == "teacher":
        t = await teacher_profile(db, user)
        return t["id"] if t else -1
    return -1


async def can_manage_group(db: Database, user: dict[str, Any] | None, group_id: int) -> bool:
    if is_admin(user):
        return True
    if not user or user.get("role") != "teacher":
        return False
    t = await teacher_profile(db, user)
    if not t:
        return False
    row = await db.fetchone("SELECT 1 FROM groups WHERE id=? AND teacher_id=?", (group_id, t["id"]))
    return row is not None


async def can_access_student(db: Database, user: dict[str, Any] | None, student_id: int) -> bool:
    if not user:
        return False
    if is_admin(user):
        return True
    if user.get("role") == "teacher":
        t = await teacher_profile(db, user)
        if not t:
            return False
        row = await db.fetchone(
            "SELECT 1 FROM students s JOIN groups g ON g.id=s.group_id "
            "WHERE s.id=? AND g.teacher_id=?",
            (student_id, t["id"]),
        )
        return row is not None
    if user.get("role") == "parent":
        row = await db.fetchone(
            "SELECT 1 FROM student_parents sp JOIN parents p ON p.id=sp.parent_id "
            "WHERE sp.student_id=? AND p.user_id=?",
            (student_id, user["id"]),
        )
        return row is not None
    return False


async def parent_of_student(db: Database, user: dict[str, Any] | None, student_id: int) -> dict[str, Any] | None:
    if not user or user.get("role") != "parent":
        return None
    return await db.fetchone(
        "SELECT p.* FROM parents p JOIN student_parents sp ON sp.parent_id=p.id "
        "WHERE p.user_id=? AND sp.student_id=?",
        (user["id"], student_id),
    )


async def can_manage_test(db: Database, user: dict[str, Any] | None, test_id: int) -> bool:
    if is_admin(user):
        return True
    if not user or user.get("role") != "teacher":
        return False
    t = await teacher_profile(db, user)
    if not t:
        return False
    row = await db.fetchone(
        "SELECT 1 FROM tests te JOIN groups g ON g.id=te.group_id "
        "WHERE te.id=? AND g.teacher_id=?",
        (test_id, t["id"]),
    )
    return row is not None

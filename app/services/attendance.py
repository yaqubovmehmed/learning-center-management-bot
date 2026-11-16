"""Davomat: darslar, keldi/ketdi, ota-ona xabarlari uchun ma'lumotlar."""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from app.db import Database, utc_now

VALID_STATUSES = ("present", "absent", "late", "excused")


async def ensure_lesson(db: Database, group_id: int, date: str, teacher_id: int | None) -> dict[str, Any]:
    now = utc_now()
    await db.execute(
        "INSERT OR IGNORE INTO lessons(group_id, teacher_id, date, status, created_at) VALUES(?,?,?, 'open', ?)",
        (group_id, teacher_id, date, now),
    )
    lesson = await db.fetchone("SELECT * FROM lessons WHERE group_id=? AND date=?", (group_id, date))
    if not lesson:
        raise RuntimeError("Dars yaratilmadi")
    return lesson


async def get_lesson(db: Database, lesson_id: int) -> dict[str, Any] | None:
    return await db.fetchone(
        "SELECT l.*, g.name AS group_name, g.teacher_id AS group_teacher_id, t.name AS teacher_name "
        "FROM lessons l JOIN groups g ON g.id=l.group_id LEFT JOIN teachers t ON t.id=l.teacher_id "
        "WHERE l.id=?",
        (lesson_id,),
    )


async def lesson_entries(db: Database, lesson_id: int) -> dict[int, dict[str, Any]]:
    rows = await db.fetchall("SELECT * FROM attendance WHERE lesson_id=?", (lesson_id,))
    return {int(r["student_id"]): r for r in rows}


async def save_entries(
    db: Database,
    *,
    lesson_id: int,
    entries: Iterable[dict[str, Any]],
    marked_by: int,
    default_check_in: str | None = None,
) -> dict[str, int]:
    """entries: student_id, status, check_in, check_out, minutes_late, note."""
    now = utc_now()
    counts = {"present": 0, "absent": 0, "late": 0, "excused": 0}
    async with db.transaction() as tx:
        for e in entries:
            status = e.get("status", "present")
            if status not in VALID_STATUSES:
                continue
            counts[status] += 1
            check_in = e.get("check_in")
            if status in ("present", "late") and not check_in:
                check_in = default_check_in
            elif status in ("absent", "excused"):
                # Kelmagan/sababli o'quvchida kirish-chiqish vaqti bo'lmasligi kerak.
                check_in = None
            check_out = e.get("check_out") if status in ("present", "late") else None
            await tx.execute(
                "INSERT INTO attendance(lesson_id, student_id, status, check_in, check_out, minutes_late, note, marked_by, marked_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(lesson_id, student_id) DO UPDATE SET "
                "status=excluded.status, "
                "check_in=CASE WHEN excluded.status IN ('absent','excused') THEN NULL "
                "ELSE COALESCE(excluded.check_in, attendance.check_in) END, "
                "check_out=CASE WHEN excluded.status IN ('absent','excused') THEN NULL "
                "ELSE COALESCE(excluded.check_out, attendance.check_out) END, "
                "minutes_late=excluded.minutes_late, note=excluded.note, marked_by=excluded.marked_by, marked_at=excluded.marked_at",
                (
                    lesson_id,
                    e["student_id"],
                    status,
                    check_in,
                    check_out,
                    int(e.get("minutes_late") or 0),
                    e.get("note"),
                    marked_by,
                    now,
                ),
            )
    return counts


async def set_times(
    db: Database,
    *,
    lesson_id: int,
    student_id: int,
    check_in: str | None = None,
    check_out: str | None = None,
    marked_by: int,
) -> None:
    now = utc_now()
    async with db.transaction() as tx:
        row = await tx.fetchone(
            "SELECT id FROM attendance WHERE lesson_id=? AND student_id=?",
            (lesson_id, student_id),
        )
        if row:
            await tx.execute(
                "UPDATE attendance SET check_in=COALESCE(?, check_in), check_out=COALESCE(?, check_out), "
                "status=CASE WHEN ? IS NOT NULL AND status IN ('absent','excused') THEN 'late' ELSE status END, "
                "marked_by=?, marked_at=? WHERE lesson_id=? AND student_id=?",
                (check_in, check_out, check_in, marked_by, now, lesson_id, student_id),
            )
        else:
            await tx.execute(
                "INSERT INTO attendance(lesson_id, student_id, status, check_in, check_out, marked_by, marked_at) "
                "VALUES(?,?, 'present', ?, ?, ?, ?)",
                (lesson_id, student_id, check_in, check_out, marked_by, now),
            )


async def set_status(
    db: Database,
    *,
    lesson_id: int,
    student_id: int,
    status: str,
    marked_by: int,
    check_in: str | None = None,
) -> None:
    if status not in VALID_STATUSES:
        return
    now = utc_now()
    async with db.transaction() as tx:
        current = await tx.fetchone(
            "SELECT check_in FROM attendance WHERE lesson_id=? AND student_id=?",
            (lesson_id, student_id),
        )
        existing_in = current.get("check_in") if current else None
        if status in ("present", "late"):
            check_in = existing_in or check_in
        else:
            check_in = None
        await tx.execute(
            "INSERT INTO attendance(lesson_id, student_id, status, check_in, marked_by, marked_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(lesson_id, student_id) DO UPDATE SET "
            "status=excluded.status, "
            "check_in=CASE WHEN excluded.status IN ('absent','excused') THEN NULL "
            "ELSE COALESCE(excluded.check_in, attendance.check_in) END, "
            "check_out=CASE WHEN excluded.status IN ('absent','excused') THEN NULL ELSE attendance.check_out END, "
            "marked_by=excluded.marked_by, marked_at=excluded.marked_at",
            (lesson_id, student_id, status, check_in, marked_by, now),
        )


async def set_note(db: Database, *, lesson_id: int, student_id: int, note: str | None) -> None:
    await db.execute(
        "UPDATE attendance SET note=? WHERE lesson_id=? AND student_id=?",
        (note, lesson_id, student_id),
    )


async def clear_times(db: Database, *, lesson_id: int, student_id: int) -> None:
    await db.execute(
        "UPDATE attendance SET check_in=NULL, check_out=NULL WHERE lesson_id=? AND student_id=?",
        (lesson_id, student_id),
    )


async def set_topic(db: Database, lesson_id: int, topic: str | None) -> None:
    await db.execute("UPDATE lessons SET topic=? WHERE id=?", (topic, lesson_id))


async def close_lesson(db: Database, lesson_id: int) -> None:
    await db.execute("UPDATE lessons SET status='closed' WHERE id=?", (lesson_id,))


async def recent_lessons(db: Database, group_id: int, limit: int = 12) -> list[dict[str, Any]]:
    return await db.fetchall(
        "SELECT l.*, "
        "(SELECT COUNT(*) FROM attendance a WHERE a.lesson_id=l.id AND a.status='present') AS present_count, "
        "(SELECT COUNT(*) FROM attendance a WHERE a.lesson_id=l.id AND a.status='absent') AS absent_count, "
        "(SELECT COUNT(*) FROM attendance a WHERE a.lesson_id=l.id AND a.status='late') AS late_count, "
        "(SELECT COUNT(*) FROM attendance a WHERE a.lesson_id=l.id AND a.status='excused') AS excused_count "
        "FROM lessons l WHERE l.group_id=? ORDER BY l.date DESC LIMIT ?",
        (group_id, limit),
    )


async def summary(db: Database, student_id: int, start: str, end: str) -> dict[str, Any]:
    row = await db.fetchone(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) AS present, "
        "SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) AS absent, "
        "SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) AS late, "
        "SUM(CASE WHEN a.status='excused' THEN 1 ELSE 0 END) AS excused "
        "FROM attendance a JOIN lessons l ON l.id=a.lesson_id "
        "WHERE a.student_id=? AND l.date BETWEEN ? AND ?",
        (student_id, start, end),
    ) or {}
    total = int(row.get("total") or 0)
    present = int(row.get("present") or 0)
    absent = int(row.get("absent") or 0)
    late = int(row.get("late") or 0)
    excused = int(row.get("excused") or 0)
    denominator = max(0, total - excused)
    rate = (present + late) / denominator * 100 if denominator else None
    return {
        "total": total,
        "present": present,
        "absent": absent,
        "late": late,
        "excused": excused,
        "attended": present + late,
        "rate": rate,
    }


async def group_stats(db: Database, group_id: int, start: str, end: str) -> list[dict[str, Any]]:
    return await db.fetchall(
        "SELECT s.id, s.full_name, s.status AS student_status, "
        "COUNT(att.student_id) AS total, "
        "SUM(CASE WHEN att.status='present' THEN 1 ELSE 0 END) AS present, "
        "SUM(CASE WHEN att.status='absent' THEN 1 ELSE 0 END) AS absent, "
        "SUM(CASE WHEN att.status='late' THEN 1 ELSE 0 END) AS late, "
        "SUM(CASE WHEN att.status='excused' THEN 1 ELSE 0 END) AS excused "
        "FROM students s LEFT JOIN ("
        "  SELECT a.student_id, a.status FROM attendance a JOIN lessons l ON l.id=a.lesson_id "
        "  WHERE l.date BETWEEN ? AND ?"
        ") att ON att.student_id=s.id "
        "WHERE s.group_id=? "
        "GROUP BY s.id ORDER BY s.status='left', s.full_name",
        (start, end, group_id),
    )


async def student_history(db: Database, student_id: int, limit: int = 15) -> list[dict[str, Any]]:
    return await db.fetchall(
        "SELECT a.*, l.date, l.topic, g.name AS group_name FROM attendance a "
        "JOIN lessons l ON l.id=a.lesson_id JOIN groups g ON g.id=l.group_id "
        "WHERE a.student_id=? ORDER BY l.date DESC LIMIT ?",
        (student_id, limit),
    )


async def today_counts(db: Database, date: str) -> dict[str, int]:
    row = await db.fetchone(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN a.status IN ('present','late') THEN 1 ELSE 0 END) AS attended, "
        "SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) AS absent, "
        "SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) AS late "
        "FROM attendance a JOIN lessons l ON l.id=a.lesson_id WHERE l.date=?",
        (date,),
    ) or {}
    return {
        "total": int(row.get("total") or 0),
        "attended": int(row.get("attended") or 0),
        "absent": int(row.get("absent") or 0),
        "late": int(row.get("late") or 0),
    }


async def attention_students(db: Database, start: str, end: str, threshold: float, min_lessons: int = 4) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        "SELECT s.id, s.full_name, g.name AS group_name, g.teacher_id, t.name AS teacher_name, "
        "COUNT(a.id) AS total, "
        "SUM(CASE WHEN a.status='excused' THEN 1 ELSE 0 END) AS excused, "
        "SUM(CASE WHEN a.status IN ('present','late') THEN 1 ELSE 0 END) AS attended "
        "FROM students s JOIN groups g ON g.id=s.group_id "
        "LEFT JOIN teachers t ON t.id=g.teacher_id "
        "JOIN attendance a ON a.student_id=s.id "
        "JOIN lessons l ON l.id=a.lesson_id AND l.date BETWEEN ? AND ? "
        "WHERE s.status='active' AND g.status='active' "
        "GROUP BY s.id HAVING total>=?",
        (start, end, min_lessons),
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        denominator = max(0, int(row["total"]) - int(row["excused"] or 0))
        rate = (int(row["attended"] or 0) / denominator * 100) if denominator else None
        if rate is not None and rate < threshold:
            row["rate"] = rate
            result.append(row)
    result.sort(key=lambda r: r["rate"])
    return result


async def add_absence_report(
    db: Database,
    *,
    student_id: int,
    parent_id: int | None,
    date: str,
    reason: str,
) -> int:
    return await db.execute_insert(
        "INSERT INTO absence_reports(student_id, parent_id, date, reason, created_at) VALUES(?,?,?,?,?)",
        (student_id, parent_id, date, reason, utc_now()),
    )


async def reports_for_student(db: Database, student_id: int, limit: int = 10) -> list[dict[str, Any]]:
    return await db.fetchall(
        "SELECT ar.*, p.full_name AS parent_name FROM absence_reports ar "
        "LEFT JOIN parents p ON p.id=ar.parent_id WHERE ar.student_id=? "
        "ORDER BY ar.created_at DESC LIMIT ?",
        (student_id, limit),
    )


async def new_reports(db: Database, limit: int = 20) -> list[dict[str, Any]]:
    return await db.fetchall(
        "SELECT ar.*, s.full_name AS student_name, g.name AS group_name, p.full_name AS parent_name "
        "FROM absence_reports ar JOIN students s ON s.id=ar.student_id "
        "LEFT JOIN groups g ON g.id=s.group_id LEFT JOIN parents p ON p.id=ar.parent_id "
        "WHERE ar.status='new' ORDER BY ar.created_at DESC LIMIT ?",
        (limit,),
    )


async def mark_report_seen(db: Database, report_id: int) -> None:
    await db.execute("UPDATE absence_reports SET status='seen' WHERE id=?", (report_id,))

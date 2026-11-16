"""Hisobotlar uchun ma'lumotlarni yig'ish."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.db import Database
from app.services import attendance, settings as settings_service, students, teachers, tests
from app.utils import today_str


def period_range(period: str, tz: ZoneInfo) -> tuple[str, str, str]:
    """(start, end, label)"""
    today = date.fromisoformat(today_str(tz))
    if period == "month":
        start = today.replace(day=1)
        return start.isoformat(), today.isoformat(), "Shu oy"
    days = 30
    if period in ("7", "30", "90"):
        days = int(period)
    start = today - timedelta(days=days - 1)
    return start.isoformat(), today.isoformat(), f"Oxirgi {days} kun"


async def dashboard(db: Database, tz: ZoneInfo, threshold: float) -> dict[str, Any]:
    today = today_str(tz)
    start = (date.fromisoformat(today) - timedelta(days=29)).isoformat()
    active_students = int(await db.scalar("SELECT COUNT(*) FROM students WHERE status='active'") or 0)
    frozen = int(await db.scalar("SELECT COUNT(*) FROM students WHERE status='frozen'") or 0)
    groups_count = int(await db.scalar("SELECT COUNT(*) FROM groups WHERE status='active'") or 0)
    teachers_count = int(await db.scalar("SELECT COUNT(*) FROM teachers WHERE is_active=1") or 0)
    today_att = await attendance.today_counts(db, today)
    pending = int(await db.scalar("SELECT COUNT(*) FROM outbox WHERE status='pending'") or 0)
    new_reports = int(await db.scalar("SELECT COUNT(*) FROM absence_reports WHERE status='new'") or 0)
    risk = await attendance.attention_students(db, start, today, threshold)
    month_tests = int(await db.scalar(
        "SELECT COUNT(*) FROM tests WHERE date>=?", (today[:8] + "01",)
    ) or 0)
    return {
        "students": active_students,
        "frozen": frozen,
        "groups": groups_count,
        "teachers": teachers_count,
        "today": today_att,
        "pending": pending,
        "new_reports": new_reports,
        "risk_count": len(risk),
        "month_tests": month_tests,
    }


async def teacher_load(db: Database) -> list[dict[str, Any]]:
    rows = await teachers.list_teachers(db)
    start = today_str(ZoneInfo("Asia/Tashkent"))
    return rows


async def group_report(db: Database, group_id: int, start: str, end: str, threshold: float) -> dict[str, Any]:
    group = await db.fetchone(
        "SELECT g.*, t.name AS teacher_name FROM groups g LEFT JOIN teachers t ON t.id=g.teacher_id WHERE g.id=?",
        (group_id,),
    )
    if not group:
        return {}
    rows = await attendance.group_stats(db, group_id, start, end)
    for row in rows:
        total = int(row.get("total") or 0)
        excused = int(row.get("excused") or 0)
        denominator = max(0, total - excused)
        row["rate"] = (
            (int(row.get("present") or 0) + int(row.get("late") or 0)) / denominator * 100
            if denominator else None
        )
    rows.sort(key=lambda r: (r["rate"] is None, r["rate"] or 0))
    return {"group": group, "rows": rows}


async def overall_attendance(db: Database, start: str, end: str) -> dict[str, Any]:
    row = await db.fetchone(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) AS present, "
        "SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) AS absent, "
        "SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) AS late, "
        "SUM(CASE WHEN a.status='excused' THEN 1 ELSE 0 END) AS excused "
        "FROM attendance a JOIN lessons l ON l.id=a.lesson_id WHERE l.date BETWEEN ? AND ?",
        (start, end),
    ) or {}
    data = {k: int(row.get(k) or 0) for k in ("total", "present", "absent", "late", "excused")}
    denominator = max(0, data["total"] - data["excused"])
    data["rate"] = (data["present"] + data["late"]) / denominator * 100 if denominator else None
    return data


async def overall_attendance_for_group(db: Database, group_id: int, start: str, end: str) -> dict[str, Any]:
    row = await db.fetchone(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) AS present, "
        "SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) AS absent, "
        "SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) AS late, "
        "SUM(CASE WHEN a.status='excused' THEN 1 ELSE 0 END) AS excused "
        "FROM attendance a JOIN lessons l ON l.id=a.lesson_id "
        "WHERE l.group_id=? AND l.date BETWEEN ? AND ?",
        (group_id, start, end),
    ) or {}
    data = {k: int(row.get(k) or 0) for k in ("total", "present", "absent", "late", "excused")}
    denominator = max(0, data["total"] - data["excused"])
    data["rate"] = (data["present"] + data["late"]) / denominator * 100 if denominator else None
    return data


async def risk_students(db: Database, tz: ZoneInfo, threshold: float) -> list[dict[str, Any]]:
    """Davomati past + oxirgi testi past o'quvchilar (takrorlanmas)."""
    today = date.fromisoformat(today_str(tz))
    start = (today - timedelta(days=29)).isoformat()
    result: dict[int, dict[str, Any]] = {}
    for row in await attendance.attention_students(db, start, today.isoformat(), threshold):
        result[int(row["id"])] = {
            "id": row["id"],
            "name": row["full_name"],
            "group": row["group_name"],
            "teacher": row["teacher_name"],
            "teacher_id": row.get("teacher_id"),
            "rate": row["rate"],
            "last_percent": None,
            "reasons": [f"davomat {row['rate']:.0f}%"],
        }
    low = await db.fetchall(
        "SELECT s.id, s.full_name, g.name AS group_name, g.teacher_id, t.name AS teacher_name, r.score, te.max_score, te.title "
        "FROM students s JOIN groups g ON g.id=s.group_id LEFT JOIN teachers t ON t.id=g.teacher_id "
        "JOIN test_results r ON r.student_id=s.id JOIN tests te ON te.id=r.test_id "
        "WHERE s.status='active' AND g.status='active' AND r.is_absent=0 AND r.score IS NOT NULL "
        "AND te.id=("
        "  SELECT te2.id FROM test_results r2 JOIN tests te2 ON te2.id=r2.test_id "
        "  WHERE r2.student_id=s.id AND r2.is_absent=0 ORDER BY te2.date DESC, te2.id DESC LIMIT 1"
        ") AND te.date>=?",
        ((today - timedelta(days=45)).isoformat(),),
    )
    for row in low:
        percent = (float(row["score"]) / float(row["max_score"]) * 100) if row["max_score"] else 0
        if percent >= 50:
            continue
        item = result.get(int(row["id"]))
        if item:
            item["last_percent"] = percent
            item["reasons"].append(f"oxirgi test {percent:.0f}%")
        else:
            result[int(row["id"])] = {
                "id": row["id"],
                "name": row["full_name"],
                "group": row["group_name"],
                "teacher": row["teacher_name"],
                "teacher_id": row.get("teacher_id"),
                "rate": None,
                "last_percent": percent,
                "reasons": [f"oxirgi test {percent:.0f}%"],
            }
    items = list(result.values())
    items.sort(key=lambda r: (r["rate"] if r["rate"] is not None else 100))
    return items


async def parent_digest_data(db: Database, parent: dict[str, Any], tz: ZoneInfo) -> list[dict[str, Any]]:
    today = date.fromisoformat(today_str(tz))
    start = (today - timedelta(days=6)).isoformat()
    threshold = float(await settings_service.get_int(db, "attendance_threshold", 75))
    data: list[dict[str, Any]] = []
    for child in await students.children_of_parent(db, int(parent["id"])):
        att = await attendance.summary(db, int(child["id"]), start, today.isoformat())
        latest = await tests.latest_for_student(db, int(child["id"]), published_only=True)
        latest_data = None
        risk = None
        if latest:
            percent = (float(latest["score"]) / float(latest["max_score"]) * 100) if latest["max_score"] else None
            latest_data = {
                "title": latest["title"],
                "score": f"{float(latest['score']):g}/{float(latest['max_score']):g}",
                "percent": percent,
                "band": latest["band"],
            }
            if percent is not None and percent < 50:
                risk = "Oxirgi test natijasi past — qo'shimcha mashg'ulot tavsiya etiladi."
        if att.get("rate") is not None and att["rate"] < threshold:
            risk = f"Davomat {att['rate']:.0f}% — me'yordan past."
        data.append({
            "name": child["full_name"],
            "group": child.get("group_name"),
            "attendance": att,
            "latest_test": latest_data,
            "risk": risk,
        })
    return data

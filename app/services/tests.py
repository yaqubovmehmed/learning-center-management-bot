"""Testlar, mocklar va natijalar xizmati."""
from __future__ import annotations

import statistics
from typing import Any

from app.db import Database, utc_now
from app.utils import estimate_band, score_percent

TEST_SELECT = """
SELECT te.*, g.name AS group_name, t.name AS teacher_name, t.user_id AS teacher_user_id,
       (SELECT COUNT(*) FROM test_results r WHERE r.test_id=te.id) AS entered_count
FROM tests te
JOIN groups g ON g.id=te.group_id
LEFT JOIN teachers t ON t.id=te.teacher_id
"""


async def get_test(db: Database, test_id: int) -> dict[str, Any] | None:
    return await db.fetchone(TEST_SELECT + " WHERE te.id=?", (test_id,))


async def list_tests(
    db: Database,
    *,
    group_id: int | None = None,
    teacher_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if group_id is not None:
        where.append("te.group_id=?")
        params.append(group_id)
    if teacher_id is not None:
        where.append("g.teacher_id=?")
        params.append(teacher_id)
    sql = TEST_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY te.date DESC, te.id DESC LIMIT ?"
    params.append(limit)
    return await db.fetchall(sql, params)


async def create_test(
    db: Database,
    *,
    group_id: int,
    teacher_id: int | None,
    title: str,
    kind: str,
    date: str,
    max_score: float,
    scale: str = "percent",
    notes: str | None = None,
) -> int:
    return await db.execute_insert(
        "INSERT INTO tests(group_id, teacher_id, title, kind, date, max_score, scale, notes, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (group_id, teacher_id, title, kind, date, max_score, scale, notes, utc_now()),
    )


async def students_for_test(db: Database, test_id: int) -> list[dict[str, Any]]:
    test = await db.fetchone("SELECT group_id FROM tests WHERE id=?", (test_id,))
    if not test:
        return []
    return await db.fetchall(
        "SELECT s.id, s.full_name, s.status, r.id AS result_id, r.score, r.band, r.is_absent "
        "FROM students s LEFT JOIN test_results r ON r.student_id=s.id AND r.test_id=? "
        "WHERE s.group_id=? AND (s.status<>'left' OR r.id IS NOT NULL) "
        "ORDER BY s.status='left', s.full_name",
        (test_id, test["group_id"]),
    )


async def results(db: Database, test_id: int) -> list[dict[str, Any]]:
    return await db.fetchall(
        "SELECT r.*, s.full_name AS student_name, s.status AS student_status "
        "FROM test_results r JOIN students s ON s.id=r.student_id "
        "WHERE r.test_id=? ORDER BY r.is_absent, r.score DESC",
        (test_id,),
    )


async def result_for(db: Database, test_id: int, student_id: int) -> dict[str, Any] | None:
    return await db.fetchone(
        "SELECT * FROM test_results WHERE test_id=? AND student_id=?",
        (test_id, student_id),
    )


async def save_result(
    db: Database,
    *,
    test_id: int,
    student_id: int,
    score: float | None,
    is_absent: bool = False,
    note: str | None = None,
    band: float | None = None,
) -> None:
    max_score = float(await db.scalar("SELECT max_score FROM tests WHERE id=?", (test_id,)) or 0)
    if band is None and score is not None and not is_absent:
        band = estimate_band(score, max_score)
    await db.execute(
        "INSERT INTO test_results(test_id, student_id, score, band, is_absent, note, created_at) "
        "VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(test_id, student_id) DO UPDATE SET score=excluded.score, band=excluded.band, "
        "is_absent=excluded.is_absent, note=excluded.note, created_at=excluded.created_at",
        (test_id, student_id, None if is_absent else score, band, 1 if is_absent else 0, note, utc_now()),
    )


async def delete_result(db: Database, test_id: int, student_id: int) -> None:
    await db.execute("DELETE FROM test_results WHERE test_id=? AND student_id=?", (test_id, student_id))


async def publish(db: Database, test_id: int) -> None:
    await db.execute("UPDATE tests SET published_at=? WHERE id=? AND published_at IS NULL", (utc_now(), test_id))


async def previous_result(db: Database, *, student_id: int, test: dict[str, Any]) -> dict[str, Any] | None:
    return await db.fetchone(
        "SELECT r.*, t.date, t.max_score, t.title FROM test_results r JOIN tests t ON t.id=r.test_id "
        "WHERE r.student_id=? AND t.group_id=? AND t.kind=? AND t.id<>? AND t.date<=? AND r.is_absent=0 "
        "ORDER BY t.date DESC, t.id DESC LIMIT 1",
        (student_id, test["group_id"], test["kind"], test["id"], test["date"]),
    )


async def latest_for_student(
    db: Database, student_id: int, *, published_only: bool = False
) -> dict[str, Any] | None:
    sql = (
        "SELECT r.*, t.title, t.kind, t.date, t.max_score, t.scale "
        "FROM test_results r JOIN tests t ON t.id=r.test_id "
        "WHERE r.student_id=? AND r.is_absent=0"
    )
    if published_only:
        sql += " AND t.published_at IS NOT NULL"
    sql += " ORDER BY t.date DESC, t.id DESC LIMIT 1"
    return await db.fetchone(sql, (student_id,))


async def results_for_student(
    db: Database, student_id: int, limit: int = 20, *, published_only: bool = False
) -> list[dict[str, Any]]:
    sql = (
        "SELECT r.*, t.title, t.kind, t.date, t.max_score, t.scale FROM test_results r "
        "JOIN tests t ON t.id=r.test_id WHERE r.student_id=?"
    )
    if published_only:
        sql += " AND t.published_at IS NOT NULL"
    sql += " ORDER BY t.date DESC, t.id DESC LIMIT ?"
    return await db.fetchall(sql, (student_id, limit))


async def stats(db: Database, test_id: int) -> dict[str, Any]:
    test = await get_test(db, test_id)
    if not test:
        return {}
    rows = await results(db, test_id)
    scored = [r for r in rows if not r["is_absent"] and r["score"] is not None]
    scores = [float(r["score"]) for r in scored]
    percents = [score_percent(float(r["score"]), float(test["max_score"])) or 0.0 for r in scored]
    bands = [float(r["band"]) for r in scored if r["band"] is not None]
    total_students = int(await db.scalar(
        "SELECT COUNT(*) FROM students WHERE group_id=? AND status<>'left'", (test["group_id"],)
    ) or 0)
    buckets = [0, 0, 0, 0, 0]
    for p in percents:
        if p <= 20:
            buckets[0] += 1
        elif p <= 40:
            buckets[1] += 1
        elif p <= 60:
            buckets[2] += 1
        elif p <= 80:
            buckets[3] += 1
        else:
            buckets[4] += 1
    ranking = sorted(scored, key=lambda r: float(r["score"]), reverse=True)
    return {
        "test": test,
        "rows": rows,
        "total_students": total_students,
        "entered": len(rows),
        "absent": sum(1 for r in rows if r["is_absent"]),
        "scored": len(scored),
        "average": statistics.fmean(scores) if scores else None,
        "median": statistics.median(scores) if scores else None,
        "highest": max(scores) if scores else None,
        "lowest": min(scores) if scores else None,
        "pass_rate": (sum(1 for p in percents if p >= 60) / len(percents) * 100) if percents else None,
        "average_percent": statistics.fmean(percents) if percents else None,
        "average_band": statistics.fmean(bands) if bands else None,
        "buckets": buckets,
        "ranking": ranking,
    }

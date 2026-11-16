"""CSV eksport (yengil, Excel uchun BOM bilan)."""
from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Sequence

from app.db import Database
from app.utils import csv_safe, fmt_date, status_label


def _csv_bytes(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([csv_safe(value) for value in row])
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


async def test_results_csv(db: Database, test_id: int) -> tuple[bytes, str]:
    test = await db.fetchone(
        "SELECT te.*, g.name AS group_name FROM tests te JOIN groups g ON g.id=te.group_id WHERE te.id=?",
        (test_id,),
    )
    if not test:
        return _csv_bytes(["Xato"], [["Test topilmadi"]]), "xato.csv"
    rows = await db.fetchall(
        "SELECT s.full_name, r.score, r.band, r.is_absent, r.note FROM test_results r "
        "JOIN students s ON s.id=r.student_id WHERE r.test_id=? ORDER BY s.full_name",
        (test_id,),
    )
    data = []
    for row in rows:
        percent = ""
        if not row["is_absent"] and row["score"] is not None and test["max_score"]:
            percent = round(float(row["score"]) / float(test["max_score"]) * 100, 1)
        data.append([
            row["full_name"],
            "qatnashmadi" if row["is_absent"] else "qatnashdi",
            "" if row["is_absent"] else row["score"],
            test["max_score"],
            percent,
            row["band"] or "",
            row["note"] or "",
        ])
    header = ["O'quvchi", "Holat", "Ball", "Maksimal", "Foiz", "Band", "Izoh"]
    filename = f"test-{test_id}-{test['date']}.csv"
    return _csv_bytes(header, data), filename


async def students_csv(db: Database, teacher_id: int | None = None) -> tuple[bytes, str]:
    sql = (
        "SELECT s.id, s.full_name, s.phone, s.status, g.name AS group_name, s.joined_at, "
        "p.full_name AS parent_name, p.phone AS parent_phone, "
        "CASE WHEN u.tg_id IS NULL THEN 'yoq' ELSE 'bor' END AS tg "
        "FROM students s LEFT JOIN groups g ON g.id=s.group_id "
        "LEFT JOIN student_parents sp ON sp.student_id=s.id AND sp.is_primary=1 "
        "LEFT JOIN parents p ON p.id=sp.parent_id LEFT JOIN users u ON u.id=p.user_id "
    )
    params: list[Any] = []
    if teacher_id is not None:
        sql += "WHERE g.teacher_id=? "
        params.append(teacher_id)
    sql += "ORDER BY s.full_name"
    rows = await db.fetchall(sql, params)
    data = [
        [
            row["id"], row["full_name"], row["phone"] or "", status_label(row["status"]),
            row["group_name"] or "", fmt_date(row["joined_at"]), row["parent_name"] or "",
            row["parent_phone"] or "", row["tg"],
        ]
        for row in rows
    ]
    header = ["ID", "O'quvchi", "Telefon", "Holat", "Patok", "Qo'shilgan", "Ota-ona", "Ota-ona tel", "Telegram"]
    return _csv_bytes(header, data), "oquvchilar.csv"


async def attendance_csv(db: Database, group_id: int, start: str, end: str) -> tuple[bytes, str]:
    group = await db.fetchone("SELECT name FROM groups WHERE id=?", (group_id,))
    rows = await db.fetchall(
        "SELECT l.date, s.full_name, a.status, a.check_in, a.check_out, a.minutes_late, a.note "
        "FROM attendance a JOIN lessons l ON l.id=a.lesson_id JOIN students s ON s.id=a.student_id "
        "WHERE l.group_id=? AND l.date BETWEEN ? AND ? ORDER BY l.date, s.full_name",
        (group_id, start, end),
    )
    data = [
        [
            row["date"], row["full_name"], status_label(row["status"]), row["check_in"] or "",
            row["check_out"] or "", row["minutes_late"], row["note"] or "",
        ]
        for row in rows
    ]
    header = ["Sana", "O'quvchi", "Holat", "Keldi", "Ketdi", "Kechikish (daq)", "Izoh"]
    name = f"davomat-{group['name'] if group else group_id}-{start}_{end}.csv".replace(" ", "_")
    return _csv_bytes(header, data), name

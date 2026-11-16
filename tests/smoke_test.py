"""Oflayn smoke test: DB, xizmatlar, hisobotlar va eksport.

Ishlatish: python tests/smoke_test.py
Telegram token talab qilinmaydi.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

tmpdir = tempfile.mkdtemp(prefix="excellence-smoke-")
os.environ.setdefault("DB_PATH", str(Path(tmpdir) / "test.db"))
os.environ.setdefault("BOT_TOKEN", "123456789:" + "A" * 35)
os.environ.setdefault("SECRET_PEPPER", "smoke-test-pepper-value-1234567890")
os.environ.setdefault("SUPERADMIN_IDS", "100000001")

from app.db import Database  # noqa: E402
from app.security import audit, hash_token, make_token  # noqa: E402
from app.services import (  # noqa: E402
    attendance,
    exports,
    groups,
    invites,
    notifications,
    permissions,
    reports,
    settings as settings_service,
    students,
    teachers,
    tests,
    users,
)
from app.utils import estimate_band, normalize_phone, score_percent, today_str  # noqa: E402
from config import settings as cfg  # noqa: E402
from app.handlers import audit as audit_h  # noqa: E402
from app.handlers import common as common_h  # noqa: E402
from app.handlers import notifications as notif_h  # noqa: E402
from app.handlers import parents as parents_h  # noqa: E402
from app.handlers import reports as reports_h  # noqa: E402
from app.handlers import settings as settings_h  # noqa: E402
from app.handlers import students as students_h  # noqa: E402
from app.handlers import tests as tests_h  # noqa: E402

CHECKS = 0


class FakeEvent:
    """Handlerlarni tarmoqsiz chaqirish uchun eng kichik stub."""

    def __init__(self, data: str = "") -> None:
        self.data = data
        self.message = None
        self.calls: list[tuple] = []

    async def answer(self, text=None, **kwargs):
        self.calls.append((text, kwargs))
        return None


def _callback_sizes(markup) -> list[int]:
    sizes = []
    for row in getattr(markup, "inline_keyboard", []) or []:
        for button in row:
            if getattr(button, "callback_data", None):
                sizes.append(len(button.callback_data.encode("utf-8")))
    return sizes


def check(condition, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"FAIL: {label}")
    print(f"  ✓ {label}")


async def run() -> None:
    db = Database(Path(os.environ["DB_PATH"]))
    await db.connect()
    try:
        check(await db.integrity_ok(), "DB integrity")
        await users.ensure_env_superadmins(db, cfg.superadmin_ids)
        admin = await users.by_tg(db, 100000001)
        check(admin and admin["role"] == "superadmin", "env superadmin seeded")

        teacher_user_id = await users.create_user(
            db, tg_id=200000002, role="teacher", full_name="Oqituvchi Test", phone="+998901112233"
        )
        teacher_id = await teachers.create_teacher(
            db, name="Oqituvchi Test", phone="+998901112233", user_id=teacher_user_id
        )
        check(teacher_id > 0, "teacher created")

        group_id = await groups.create_group(db, {
            "name": "IELTS 7.0 A",
            "course": "IELTS",
            "level": "Upper-Intermediate",
            "teacher_id": teacher_id,
            "days": "mon,wed,fri",
            "time": "18:00",
            "duration_min": 90,
            "monthly_fee": 600000,
            "start_date": today_str(cfg.tz),
        })
        check(group_id > 0, "group created")
        check(await groups.group_name_taken(db, "ielts 7.0 a"), "group name uniqueness")

        s1, p1 = await students.create_student(
            db, full_name="Ali Valiyev", phone="+998901234567", group_id=group_id,
            created_by=admin["id"], parent_name="Vali Valiyev", parent_phone="+998907654321",
        )
        s2, _ = await students.create_student(
            db, full_name="Zarina Karimova", phone=None, group_id=group_id, created_by=admin["id"]
        )
        check(s1 > 0 and s2 > 0 and p1, "students + parent created")
        check((await students.get_student(db, s1))["group_name"] == "IELTS 7.0 A", "student join group")

        parent = await students.get_parent(db, p1)
        check(parent is not None, "parent lookup")

        token, invite_id = await invites.create_invite(
            db, role="parent", target_id=p1, created_by=admin["id"], pepper=cfg.pepper
        )
        check(invite_id > 0, "parent invite created")
        found = await invites.find_valid(db, token=token, role="parent", pepper=cfg.pepper)
        check(found is not None, "invite token validates")
        record, error = await invites.bind_parent(
            db, invite=found, tg_id=300000003, tg_name="Vali", username="vali"
        )
        check(record is not None and error is None, "parent bind")
        parent_user = await users.by_tg(db, 300000003)
        check(parent_user and parent_user["role"] == "parent", "parent user role")
        check(not await invites.find_valid(db, token=token, role="parent", pepper=cfg.pepper),
              "invite single-use")
        check(hash_token(token, cfg.pepper) != token, "token stored hashed")

        children = await students.children_of_user(db, parent_user["id"])
        check(len(children) == 1 and children[0]["id"] == s1, "children_of_user")

        today = today_str(cfg.tz)
        lesson = await attendance.ensure_lesson(db, group_id, today, teacher_id)
        counts = await attendance.save_entries(
            db, lesson_id=lesson["id"],
            entries=[
                {"student_id": s1, "status": "present", "check_in": "18:02"},
                {"student_id": s2, "status": "absent"},
            ],
            marked_by=teacher_user_id,
        )
        check(counts["present"] == 1 and counts["absent"] == 1, "attendance saved")
        summary = await attendance.summary(db, s1, today, today)
        check(summary["rate"] == 100.0 and summary["absent"] == 0, "attendance summary")
        await attendance.save_entries(
            db, lesson_id=lesson["id"],
            entries=[{"student_id": s1, "status": "late", "minutes_late": 10}],
            marked_by=teacher_user_id,
        )
        summary = await attendance.summary(db, s1, today, today)
        check(summary["late"] == 1, "attendance status update")

        # Kelmadi/sababli belgilanganda kirish-chiqish vaqtlari tozalanadi.
        await attendance.set_status(
            db, lesson_id=lesson["id"], student_id=s1, status="absent", marked_by=teacher_user_id
        )
        row = await db.fetchone(
            "SELECT status, check_in FROM attendance WHERE lesson_id=? AND student_id=?",
            (lesson["id"], s1),
        )
        check(row["status"] == "absent" and row["check_in"] is None, "absent clears check-in")
        # Keyinchalik kelgan bo'lsa — avtomatik kechikdi va vaqt yoziladi.
        await attendance.set_times(
            db, lesson_id=lesson["id"], student_id=s1, check_in="18:20", marked_by=teacher_user_id
        )
        row = await db.fetchone(
            "SELECT status, check_in FROM attendance WHERE lesson_id=? AND student_id=?",
            (lesson["id"], s1),
        )
        check(row["status"] == "late" and row["check_in"] == "18:20", "arrival after absent becomes late")
        await attendance.save_entries(
            db, lesson_id=lesson["id"],
            entries=[{"student_id": s1, "status": "late", "minutes_late": 10, "check_in": "18:20"}],
            marked_by=teacher_user_id,
        )

        report_id = await attendance.add_absence_report(
            db, student_id=s2, parent_id=None, date=today, reason="Kasal"
        )
        check(report_id > 0 and len(await attendance.new_reports(db)) == 1, "absence report")

        test_id = await tests.create_test(
            db, group_id=group_id, teacher_id=teacher_id, title="Mock 1", kind="mock",
            date=today, max_score=40, scale="ielts",
        )
        await tests.save_result(db, test_id=test_id, student_id=s1, score=32)
        await tests.save_result(db, test_id=test_id, student_id=s2, score=None, is_absent=True)
        stat = await tests.stats(db, test_id)
        check(stat["entered"] == 2 and stat["absent"] == 1, "test stats counts")
        check(stat["highest"] == 32 and stat["average_band"] == round(estimate_band(32, 40), 1)
              or stat["average_band"] == estimate_band(32, 40), "bands and highest")
        await tests.publish(db, test_id)
        check((await tests.get_test(db, test_id))["published_at"] is not None, "test published")

        linked = await notifications.queue_to_parents(
            db, student_id=s1, kind="result", text="Natija", dedupe_base=f"r:{test_id}:{s1}"
        )
        check(linked["queued"] == 1, "parent notification queued")
        again = await notifications.queue_to_parents(
            db, student_id=s1, kind="result", text="Natija", dedupe_base=f"r:{test_id}:{s1}"
        )
        check(again["queued"] == 0, "notification dedupe")
        outbox = await notifications.stats(db)
        check(outbox["pending"] == 1, "outbox stats")

        dash = await reports.dashboard(db, cfg.tz, 75.0)
        check(dash["students"] == 2 and dash["groups"] == 1, "dashboard")
        overall = await reports.overall_attendance(db, today, today)
        check(overall["total"] == 2, "overall attendance")
        group_overall = await reports.overall_attendance_for_group(db, group_id, today, today)
        check(group_overall["total"] == 2, "group attendance")
        digest = await reports.parent_digest_data(db, parent, cfg.tz)
        check(len(digest) == 1, "parent digest data")
        await tests.save_result(db, test_id=test_id, student_id=s2, score=10)
        risk = await reports.risk_students(db, cfg.tz, 75.0)
        check(any(int(r["id"]) == s2 for r in risk), "risk students")

        csv_data, filename = await exports.test_results_csv(db, test_id)
        check(csv_data.startswith(b"\xef\xbb\xbf") and filename.endswith(".csv"), "test CSV")
        csv_data, filename = await exports.students_csv(db)
        check(b"Ali Valiyev" in csv_data, "students CSV")
        csv_data, filename = await exports.attendance_csv(db, group_id, today, today)
        check(b"Ali Valiyev" in csv_data, "attendance CSV")

        await settings_service.set_value(db, "attendance_threshold", 80)
        check(await settings_service.get_int(db, "attendance_threshold") == 80, "settings cache update")

        await audit(db, admin, "smoke_test", "system", 0, {"ok": True})
        check(int(await db.scalar("SELECT COUNT(*) FROM audit_log")) >= 1, "audit write")

        backup = await db.backup(Path(tmpdir) / "backup.db")
        check(backup.exists() and backup.stat().st_size > 0, "database backup")

        check(normalize_phone("90 123 45 67") == "+998901234567", "phone normalize")
        check(score_percent(32, 40) == 80.0, "score percent")
        check(await permissions.can_access_student(db, {"role": "parent", "is_active": 1, "id": parent_user["id"]}, s1),
              "parent RBAC access")
        check(not await permissions.can_access_student(db, {"role": "parent", "is_active": 1, "id": parent_user["id"]}, s2),
              "parent RBAC denies other student")
        check(await permissions.can_manage_test(db, {"role": "teacher", "is_active": 1, "id": teacher_user_id}, test_id),
              "teacher test scope")

        # ---- Ikkinchi o'qituvchi: xavf ro'yxati faqat o'z guruhi bilan cheklanishi ----
        teacher2_user_id = await users.create_user(
            db, tg_id=200000003, role="teacher", full_name="Oqituvchi Ikki", phone="+998901112244"
        )
        teacher2_id = await teachers.create_teacher(
            db, name="Oqituvchi Ikki", phone="+998901112244", user_id=teacher2_user_id
        )
        group2_id = await groups.create_group(db, {
            "name": "General B",
            "course": "General English",
            "teacher_id": teacher2_id,
            "days": "tue,thu",
            "time": "10:00",
            "start_date": today,
        })
        s3, _ = await students.create_student(
            db, full_name="Dilnoza Yusupova", phone=None, group_id=group2_id, created_by=admin["id"]
        )
        test2_id = await tests.create_test(
            db, group_id=group2_id, teacher_id=teacher2_id, title="Quiz 1", kind="quiz",
            date=today, max_score=100, scale="percent",
        )
        await tests.save_result(db, test_id=test2_id, student_id=s3, score=10)
        risk_all = await reports.risk_students(db, cfg.tz, 75.0)
        check(any(int(r["id"]) == s3 for r in risk_all), "risk includes low-score student")
        teacher1 = await users.by_id(db, teacher_user_id)
        teacher2 = await users.by_id(db, teacher2_user_id)
        risk_t1 = [r for r in risk_all if int(r.get("teacher_id") or 0) == teacher_id]
        risk_t2 = [r for r in risk_all if int(r.get("teacher_id") or 0) == teacher2_id]
        check(all(int(r["id"]) != s3 for r in risk_t1), "risk scoped to teacher 1")
        check(any(int(r["id"]) == s3 for r in risk_t2), "risk scoped to teacher 2")

        # ---- Handlerlar renderi (tarmoqsiz) ----
        empty_group_id = await groups.create_group(db, {
            "name": "Bo'sh guruh", "course": "IELTS", "days": "sat", "start_date": today,
        })
        await reports_h.attendance_report(FakeEvent(f"rep:attp:{empty_group_id}:30:1"), db, admin)
        check(True, "attendance report renders with empty group")
        await reports_h.risk_list(FakeEvent("rep:risk:1"), db, teacher1)
        await reports_h.risk_list(FakeEvent("rep:risk:1"), db, teacher2)
        check(True, "risk list renders for both teachers")
        await notif_h.absence_reports(FakeEvent("ntf:reports:1"), db, admin)
        check(True, "absence reports render")
        await settings_h._render(FakeEvent(), db)
        await audit_h._render(FakeEvent(), db, 1)
        check(True, "settings and audit render")
        await parents_h._settings_view(FakeEvent(), db, parent_user)
        await common_h.teacher_help(FakeEvent(), db, teacher1)
        await common_h.dashboard_admin(db, admin, cfg.tz)
        await common_h.dashboard_teacher(db, teacher1, cfg.tz)
        await common_h.dashboard_parent(db, parent_user, cfg.tz)
        check(True, "dashboards render")
        teacher_text, teacher_kb = await students_h.student_card(db, teacher1, s1, bot_username="test_bot")
        check(
            "•••" in teacher_text and "+998 90 765 4321" not in teacher_text,
            "teacher cannot see parent phone",
        )
        check(not any("stu:parent" in b.callback_data for row in teacher_kb.inline_keyboard for b in row if b.callback_data),
              "teacher cannot manage parents")
        card_text, card_kb = await tests_h.test_card(db, test2_id, teacher2)
        check("Quiz 1" in card_text, "test card renders")
        group_text, group_kb = await __import__("app.handlers.groups", fromlist=["group_card"]).group_card(db, group2_id)
        check("General B" in group_text, "group card renders")
        all_sizes = _callback_sizes(card_kb) + _callback_sizes(group_kb)
        check(all(size <= 64 for size in all_sizes), "callback_data within 64 bytes")

        # O'qituvchi kartasi orqali admin akkauntini bloklab bo'lmaydi.
        await users.set_role(db, teacher2_user_id, "admin")
        await teachers.set_active(db, teacher2_id, False)
        check(int((await users.by_id(db, teacher2_user_id))["is_active"]) == 1,
              "teacher deactivation keeps admin account active")
        await users.set_role(db, teacher2_user_id, "teacher")
        await teachers.set_active(db, teacher2_id, False)
        check(int((await users.by_id(db, teacher2_user_id))["is_active"]) == 0,
              "teacher deactivation disables teacher account")
        await teachers.set_active(db, teacher2_id, True)

        # E'lon qilinmagan natijalar ota-onaga ko'rinmasligi kerak.
        draft_id = await tests.create_test(
            db, group_id=group_id, teacher_id=teacher_id, title="Qoralama test", kind="test",
            date=today, max_score=100, scale="percent",
        )
        await tests.save_result(db, test_id=draft_id, student_id=s1, score=5)
        published_latest = await tests.latest_for_student(db, s1, published_only=True)
        check(published_latest and published_latest["title"] == "Mock 1", "parent sees only published latest")
        published_rows = await tests.results_for_student(db, s1, 20, published_only=True)
        check(all(r["title"] != "Qoralama test" for r in published_rows), "parent sees only published results")
        digest_draft = await reports.parent_digest_data(db, parent, cfg.tz)
        check(
            all((c.get("latest_test") or {}).get("title") != "Qoralama test" for c in digest_draft),
            "weekly digest hides unpublished results",
        )
    finally:
        await db.close()
    print(f"\n✅ {CHECKS} tekshiruv muvaffaqiyatli o'tdi.")


if __name__ == "__main__":
    asyncio.run(run())

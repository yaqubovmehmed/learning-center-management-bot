"""Testlar va mocklar: yaratish, ball kiritish, e'lon qilish, tahlil."""
from __future__ import annotations

from datetime import date
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app import keyboards as kb
from app import ui
from app.db import Database
from app.security import audit
from app.services import exports, groups, messages, notifications, permissions, settings as settings_service, students, tests
from app.states import TestAdd, TestEntry
from app.utils import (
    clean_text, esc, fmt_date, fmt_score, kind_label, paginate, parse_date, parse_float,
    safe_int, score_percent, today_str, trend,
)
from config import settings

router = Router(name="tests")


async def _scope_teacher_id(db: Database, user: dict) -> int | None:
    if permissions.is_admin(user):
        return None
    teacher = await permissions.teacher_profile(db, user)
    return teacher["id"] if teacher else -1


async def show_test_list(
    event: Message | CallbackQuery,
    db: Database,
    user: dict,
    *,
    page: int = 1,
    group_id: int | None = None,
) -> None:
    teacher_id = await _scope_teacher_id(db, user)
    if teacher_id == -1:
        await ui.deny(event)
        return
    if group_id is not None and not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(event)
        return
    items = await tests.list_tests(db, group_id=group_id, teacher_id=teacher_id, limit=200)
    chunk, page, pages, total = paginate(items, page, 8)
    text = f"📝 <b>Testlar</b>\n\nJami: <b>{total}</b>"
    if group_id:
        group = await groups.get_group(db, group_id)
        text += f" · 🗂 <b>{esc(group['name'] if group else '—')}</b>"
    rows: list[list[tuple[str, str]]] = []
    for test in chunk:
        published = "📢" if test.get("published_at") else "📝"
        text += (
            f"\n\n{published} <b>{esc(test['title'])}</b>\n"
            f"   {kind_label(test['kind'])} · {esc(fmt_date(test['date']))} · "
            f"kiritilgan: {test['entered_count']}"
        )
        rows.append([(f"{published} {test['title']} · {fmt_date(test['date'])}"[:58], f"tst:v:{test['id']}")])
    if not items:
        text += "\n\nHozircha test yo'q."
    if pages > 1:
        prefix = f"tst:g:{group_id}" if group_id else "tst:l"
        rows.append(kb.pager(prefix, page, pages))
    rows.append([("➕ Yangi test", "tst:add")])
    if group_id:
        rows.append([("🗂 Guruh kartasi", f"grp:v:{group_id}")])
    rows.append(kb.nav_row("home"))
    await ui.send(event, text, kb.ikb(rows))


@router.message(F.text.in_({"📝 Testlar"}))
async def tests_menu_message(message: Message, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin", "teacher"):
        return
    await show_test_list(message, db, user)


@router.callback_query(F.data == "tst:menu")
async def tests_menu(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    await show_test_list(callback, db, user)
    await callback.answer()


@router.callback_query(F.data.startswith("tst:l:"))
async def tests_page(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    page = safe_int(callback.data.split(":")[2], 1, 1, 999)
    await show_test_list(callback, db, user, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith("tst:g:"))
async def tests_group_page(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    parts = callback.data.split(":")
    group_id = safe_int(parts[2])
    page = safe_int(parts[3] if len(parts) > 3 else 1, 1, 1, 999)
    await show_test_list(callback, db, user, page=page, group_id=group_id)
    await callback.answer()


async def test_card(db: Database, test_id: int, user: dict) -> tuple[str, Any]:
    test = await tests.get_test(db, test_id)
    if not test:
        return "❌ Test topilmadi.", kb.ikb([kb.nav_row("tst:menu")])
    stat = await tests.stats(db, test_id)
    total_students = stat.get("total_students", 0)
    entered = stat.get("entered", 0)
    text = (
        f"📝 <b>{esc(test['title'])}</b>\n"
        f"🎯 {kind_label(test['kind'])} · 📅 {esc(fmt_date(test['date']))}\n"
        f"🗂 {esc(test['group_name'])} · 👨‍🏫 {esc(test.get('teacher_name') or '—')}\n"
        f"🎚 Maksimal ball: <b>{test['max_score']:g}</b>\n"
        f"📊 Kiritilgan: <b>{entered}/{total_students}</b>"
        + (f" · ❌ {stat.get('absent', 0)}" if stat.get("absent") else "")
    )
    if test.get("published_at"):
        text += "\n📢 Natijalar ota-onalarga e'lon qilingan"
    else:
        text += "\n🔕 Hali e'lon qilinmagan"
    if stat.get("average") is not None:
        text += f"\n📈 O'rtacha: <b>{stat['average']:.1f}/{test['max_score']:g}</b> ({stat['average_percent']:.0f}%)"
    if stat.get("average_band") is not None and test["kind"] in ("mock", "exam", "test"):
        text += f"\n🎯 O'rtacha band: <b>{stat['average_band']:.1f}</b>"
    if test.get("notes"):
        text += f"\n📝 {esc(test['notes'])}"
    rows: list[list[tuple[str, str]]] = [
        [("📊 Ball kiritish", f"tst:e:{test_id}"), ("📈 Statistika", f"tst:stats:{test_id}")],
        [("📋 Natijalar", f"tst:res:{test_id}:1")],
        [(("📢 Qayta e'lon qilish" if test.get("published_at") else "📢 Natijalarni e'lon qilish"), f"tst:pub:{test_id}")],
        [("📥 CSV", f"tst:csv:{test_id}")],
    ]
    if permissions.is_admin(user):
        rows.append([("🗑 Testni o'chirish", f"tst:del:{test_id}")])
    rows.append(kb.nav_row(f"tst:g:{test['group_id']}:1"))
    return text, kb.ikb(rows)


@router.callback_query(F.data.startswith("tst:v:"))
async def test_view(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    test_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_test(db, user, test_id):
        await ui.deny(callback)
        return
    text, markup = await test_card(db, test_id, user)
    await ui.send(callback, text, markup)
    await callback.answer()


# ---------- Yaratish ----------

@router.callback_query(F.data == "tst:add")
async def test_add_start(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    teacher_id = await _scope_teacher_id(db, user)
    items = await groups.list_groups(db, teacher_id=teacher_id)
    if not items:
        await callback.answer("Avval patok yarating", show_alert=True)
        return
    await state.clear()
    await state.set_state(TestAdd.group)
    rows: list[list[tuple[str, str]]] = [
        [(f"{g['name']} · {g['students_count']} ta"[:55], f"tst:a:group:{g['id']}")] for g in items
    ]
    rows.append(kb.nav_row("tst:menu"))
    await ui.send(callback, "➕ <b>Yangi test</b>\n\n1/5 — Patokni tanlang:", kb.ikb(rows))
    await callback.answer()


@router.callback_query(TestAdd.group, F.data.startswith("tst:a:group:"))
async def test_add_group(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    group_id = safe_int(callback.data.split(":")[3])
    if not await permissions.can_manage_group(db, user, group_id):
        await ui.deny(callback)
        return
    group = await groups.get_group(db, group_id)
    if not group:
        await callback.answer("Topilmadi", show_alert=True)
        return
    await state.update_data(group_id=group_id, teacher_id=group.get("teacher_id"))
    await state.set_state(TestAdd.title)
    await ui.send(
        callback,
        f"2/5 — <b>{esc(group['name'])}</b> uchun test nomini kiriting.\n"
        "Masalan: <code>Mock #4 — Reading</code>",
        kb.ikb([kb.nav_row("tst:menu")]),
    )
    await callback.answer()


@router.message(TestAdd.title)
async def test_add_title(message: Message, state: FSMContext) -> None:
    title = clean_text(message.text or "", 80)
    if len(title) < 2:
        await message.answer("❌ Nom kamida 2 belgi bo'lsin.")
        return
    await state.update_data(title=title)
    await state.set_state(TestAdd.kind)
    await message.answer("3/5 — Test turini tanlang:", reply_markup=kb.test_kinds_kb("tst:a:kind", "tst:menu"))


@router.callback_query(TestAdd.kind, F.data.startswith("tst:a:kind:"))
async def test_add_kind(callback: CallbackQuery, state: FSMContext) -> None:
    kind = callback.data.split(":")[3]
    if kind not in ("test", "mock", "quiz", "exam"):
        await callback.answer("Noto'g'ri", show_alert=True)
        return
    await state.update_data(kind=kind)
    await state.set_state(TestAdd.date)
    await ui.send(
        callback,
        "4/5 — Test sanasi (KK.OO.YYYY).\nBugun bo'lsa o'tkazib yuboring.",
        kb.skip_kb("tst:a:skip:date", "tst:menu"),
    )
    await callback.answer()


@router.message(TestAdd.date)
async def test_add_date(message: Message, state: FSMContext) -> None:
    value = parse_date(message.text or "")
    if not value:
        await message.answer("❌ Sana noto'g'ri. Format: KK.OO.YYYY")
        return
    await state.update_data(date=value)
    await state.set_state(TestAdd.max_score)
    await message.answer(
        "5/5 — Maksimal ballni kiriting (masalan <code>40</code> yoki <code>100</code>).\n"
        "40 ballik mock uchun IELTS band ham hisoblanadi.",
        reply_markup=kb.skip_kb("tst:a:skip:max", "tst:menu"),
    )


@router.callback_query(TestAdd.date, F.data == "tst:a:skip:date")
async def test_add_skip_date(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(date=today_str(settings.tz))
    await state.set_state(TestAdd.max_score)
    await ui.send(
        callback,
        "5/5 — Maksimal ballni kiriting (masalan <code>40</code> yoki <code>100</code>).",
        kb.skip_kb("tst:a:skip:max", "tst:menu"),
    )
    await callback.answer()


@router.message(TestAdd.max_score)
async def test_add_max(message: Message, state: FSMContext, db: Database) -> None:
    value = parse_float(message.text or "", 1, 1000)
    if value is None:
        await message.answer("❌ Ball noto'g'ri. 1-1000 oralig'ida raqam kiriting.")
        return
    await state.update_data(max_score=value)
    await state.set_state(TestAdd.confirm)
    await _test_add_summary(message, state, db)


@router.callback_query(TestAdd.max_score, F.data == "tst:a:skip:max")
async def test_add_skip_max(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.update_data(max_score=100.0)
    await state.set_state(TestAdd.confirm)
    await _test_add_summary(callback, state, db)
    await callback.answer()


async def _test_add_summary(event: Message | CallbackQuery, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    group = await groups.get_group(db, int(data.get("group_id") or 0))
    text = (
        "✅ <b>Tekshiring</b>\n\n"
        f"📝 {esc(data.get('title'))}\n"
        f"🎯 {kind_label(data.get('kind', 'test'))}\n"
        f"🗂 {esc(group['name'] if group else '—')}\n"
        f"📅 {esc(fmt_date(data.get('date')))}\n"
        f"🎚 Maksimal: <b>{float(data.get('max_score') or 0):g}</b>"
    )
    await ui.send(event, text, kb.ikb([
        [("✅ Yaratish va ball kiritish", "tst:a:confirm")],
        kb.nav_row("tst:menu"),
    ]))


@router.callback_query(TestAdd.confirm, F.data == "tst:a:confirm")
async def test_add_confirm(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    data = await state.get_data()
    if not data.get("title") or not data.get("group_id"):
        await callback.answer("Ma'lumot yo'q", show_alert=True)
        return
    test_id = await tests.create_test(
        db,
        group_id=int(data["group_id"]),
        teacher_id=data.get("teacher_id"),
        title=data["title"],
        kind=data.get("kind", "test"),
        date=data.get("date") or today_str(settings.tz),
        max_score=float(data.get("max_score") or 100),
        scale="ielts" if float(data.get("max_score") or 0) == 40 else "percent",
    )
    await audit(db, user, "test_create", "test", test_id, {"title": data["title"], "group_id": data["group_id"]})
    await state.clear()
    text, markup = await test_card(db, test_id, user)
    await ui.send(callback, "✅ Test yaratildi!\n\n" + text, markup)
    await callback.answer("Yaratildi")


# ---------- Ball kiritish ----------

@router.callback_query(F.data.startswith("tst:e:"))
async def test_entry_screen(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    test_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_test(db, user, test_id):
        await ui.deny(callback)
        return
    await _show_entry(callback, db, test_id, 1)
    await callback.answer()


async def _show_entry(event: CallbackQuery | Message, db: Database, test_id: int, page: int = 1) -> None:
    test = await tests.get_test(db, test_id)
    if not test:
        await ui.toast(event, "Test topilmadi", True)
        return
    rows_data = await tests.students_for_test(db, test_id)
    chunk, page, pages, total = paginate(rows_data, page, 8)
    missing = sum(1 for r in rows_data if r.get("result_id") is None)
    text = (
        f"📊 <b>{esc(test['title'])}</b> — ball kiritish\n"
        f"🎚 Maksimal: <b>{test['max_score']:g}</b> · Kiritilgan: <b>{total - missing}/{total}</b>\n\n"
        "O'quvchi ustiga bosing yoki tezkor kiritishdan foydalaning."
    )
    rows: list[list[tuple[str, str]]] = []
    for student in chunk:
        if student.get("result_id") is None:
            label = f"➖ {student['full_name']}"
        elif int(student.get("is_absent") or 0):
            label = f"❌ {student['full_name']} — qatnashmadi"
        else:
            label = f"✅ {student['full_name']} — {float(student['score']):g}"
        rows.append([(label[:55], f"tst:s:{test_id}:{student['id']}:{page}")])
    if pages > 1:
        rows.append(kb.pager(f"tst:e:{test_id}", page, pages))
    if missing:
        rows.append([(f"⚡️ Tezkor kiritish ({missing} ta qoldi)", f"tst:q:{test_id}")])
    rows.append([("📈 Statistika", f"tst:stats:{test_id}"), ("📢 E'lon", f"tst:pub:{test_id}")])
    rows.append(kb.nav_row(f"tst:v:{test_id}"))
    await ui.send(event, text, kb.ikb(rows))


@router.callback_query(F.data.startswith("tst:s:"))
async def test_single_entry(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    _, _, test_id_s, student_id_s, page_s = callback.data.split(":")
    test_id = safe_int(test_id_s)
    if not await permissions.can_manage_test(db, user, test_id):
        await ui.deny(callback)
        return
    test = await tests.get_test(db, test_id)
    student = await students.get_student(db, safe_int(student_id_s))
    if not test or not student:
        await callback.answer("Topilmadi", show_alert=True)
        return
    await state.clear()
    await state.set_state(TestEntry.score)
    await state.update_data(
        mode="single", test_id=test_id, student_id=student["id"],
        max_score=float(test["max_score"]), page=safe_int(page_s, 1, 1, 999),
    )
    await ui.send(
        callback,
        f"✍️ <b>{esc(student['full_name'])}</b>\n"
        f"Ball kiriting: 0 dan {test['max_score']:g} gacha.\n"
        "Qatnashmagan bo'lsa <code>yo'q</code> deb yozing.",
        kb.ikb([
            [("❌ Qatnashmadi", f"tst:abs:{test_id}:{student['id']}:{page_s}")],
            [("⬅️ Orqaga", f"tst:e:{test_id}")],
        ]),
    )
    await callback.answer()


@router.message(TestEntry.score)
async def test_score_message(message: Message, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(message, user, "superadmin", "admin", "teacher"):
        return
    data = await state.get_data()
    test_id = int(data.get("test_id") or 0)
    if not await permissions.can_manage_test(db, user, test_id):
        await ui.deny(message)
        return
    test = await tests.get_test(db, test_id)
    if not test:
        await state.clear()
        await message.answer("Test topilmadi.")
        return
    raw = (message.text or "").strip().lower()
    absent = raw in ("yo'q", "yoq", "absent", "-", "0/0")
    score: float | None = None
    if not absent:
        score = parse_float(raw.split("/")[0], 0, float(test["max_score"]))
        if score is None:
            await message.answer(
                f"❌ Ball noto'g'ri. 0 dan {test['max_score']:g} gacha raqam yoki <code>yo'q</code> kiriting."
            )
            return
    student_id = int(data.get("student_id") or 0)
    if data.get("mode") == "queue":
        await _advance_queue(message, state, db, user, action="absent" if absent else "score", score=score)
        return
    await tests.save_result(db, test_id=test_id, student_id=student_id, score=score, is_absent=absent)
    await audit(db, user, "test_result", "test", test_id, {"student_id": student_id, "absent": absent})
    await state.clear()
    await message.answer("✅ Saqlandi." if not absent else "❌ Qatnashmadi deb belgilandi.")
    await _show_entry(message, db, test_id, int(data.get("page") or 1))


@router.callback_query(F.data.startswith("tst:abs:"))
async def test_single_absent(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    _, _, test_id_s, student_id_s, page_s = callback.data.split(":")
    test_id = safe_int(test_id_s)
    if not await permissions.can_manage_test(db, user, test_id):
        await ui.deny(callback)
        return
    await tests.save_result(db, test_id=test_id, student_id=safe_int(student_id_s), score=None, is_absent=True)
    await audit(db, user, "test_result", "test", test_id, {"student_id": student_id_s, "absent": True})
    await state.clear()
    await callback.answer("Qatnashmadi")
    await _show_entry(callback, db, test_id, safe_int(page_s, 1, 1, 999))


@router.callback_query(F.data.startswith("tst:q:"))
async def test_queue_start(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    test_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_test(db, user, test_id):
        await ui.deny(callback)
        return
    rows_data = await tests.students_for_test(db, test_id)
    queue = [int(r["id"]) for r in rows_data if r.get("result_id") is None]
    if not queue:
        await callback.answer("Barcha ballar kiritilgan", show_alert=True)
        return
    await state.clear()
    await state.set_state(TestEntry.score)
    await state.update_data(mode="queue", test_id=test_id, queue=queue, index=0)
    await _send_queue_prompt(callback, state, db, test_id, queue, 0)
    await callback.answer()


async def _send_queue_prompt(
    event: Message | CallbackQuery,
    state: FSMContext,
    db: Database,
    test_id: int,
    queue: list[int],
    index: int,
) -> None:
    test = await tests.get_test(db, test_id)
    student = await students.get_student(db, queue[index])
    if not test or not student:
        await state.clear()
        await ui.send(event, "❌ Ma'lumot topilmadi.", kb.ikb([kb.nav_row(f"tst:e:{test_id}")]))
        return
    await state.update_data(index=index, student_id=queue[index])
    remaining = len(queue) - index
    await ui.send(
        event,
        f"⚡️ <b>Tezkor kiritish</b> · qoldi: <b>{remaining}</b>\n\n"
        f"👤 <b>{esc(student['full_name'])}</b>\n"
        f"Ball: 0 — {test['max_score']:g}\n"
        f"Qatnashmasa <code>yo'q</code> deb yozing.",
        kb.ikb([
            [("❌ Qatnashmadi", "tst:qabsent"), ("⏭ O'tkazish", "tst:qskip")],
            [("⏹ Tugatish", "tst:qdone")],
        ]),
    )


async def _advance_queue(
    event: Message | CallbackQuery,
    state: FSMContext,
    db: Database,
    user: dict,
    *,
    action: str,
    score: float | None = None,
) -> None:
    data = await state.get_data()
    test_id = int(data.get("test_id") or 0)
    queue = [int(x) for x in (data.get("queue") or [])]
    index = int(data.get("index") or 0)
    if index >= len(queue):
        await state.clear()
        await _show_entry(event, db, test_id)
        return
    student_id = queue[index]
    if action in ("score", "absent"):
        await tests.save_result(
            db, test_id=test_id, student_id=student_id,
            score=score, is_absent=(action == "absent"),
        )
        await audit(db, user, "test_result", "test", test_id, {"student_id": student_id, "absent": action == "absent"})
    index += 1
    if index >= len(queue):
        await state.clear()
        await ui.send(
            event,
            "✅ <b>Barcha ballar kiritildi!</b>\n\nEndi natijalarni tekshirib, ota-onalarga e'lon qilishingiz mumkin.",
            kb.ikb([
                [("📊 Ko'rib chiqish", f"tst:e:{test_id}")],
                [("📢 E'lon qilish", f"tst:pub:{test_id}")],
                [("🏠 Bosh menyu", "home")],
            ]),
        )
        return
    await _send_queue_prompt(event, state, db, test_id, queue, index)


@router.callback_query(TestEntry.score, F.data == "tst:qskip")
async def test_queue_skip(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    await _advance_queue(callback, state, db, user, action="skip")
    await callback.answer("O'tkazildi")


@router.callback_query(TestEntry.score, F.data == "tst:qabsent")
async def test_queue_absent(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    await _advance_queue(callback, state, db, user, action="absent")
    await callback.answer("Qatnashmadi")


@router.callback_query(TestEntry.score, F.data == "tst:qdone")
async def test_queue_done(callback: CallbackQuery, state: FSMContext, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    data = await state.get_data()
    test_id = int(data.get("test_id") or 0)
    await state.clear()
    await callback.answer("Tugatildi")
    await _show_entry(callback, db, test_id)


# ---------- E'lon qilish ----------

@router.callback_query(F.data.startswith("tst:pub:"))
async def test_publish_confirm(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    test_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_test(db, user, test_id):
        await ui.deny(callback)
        return
    test = await tests.get_test(db, test_id)
    if not test:
        await callback.answer("Topilmadi", show_alert=True)
        return
    stat = await tests.stats(db, test_id)
    linked = await db.scalar(
        "SELECT COUNT(DISTINCT p.id) FROM parents p JOIN student_parents sp ON sp.parent_id=p.id "
        "JOIN students s ON s.id=sp.student_id JOIN users u ON u.id=p.user_id "
        "WHERE s.group_id=? AND u.is_active=1 AND p.notif_results=1",
        (test["group_id"],),
    ) or 0
    await ui.send(
        callback,
        f"📢 <b>{esc(test['title'])}</b> natijalari ota-onalarga yuborilsinmi?\n\n"
        f"📊 Kiritilgan: <b>{stat.get('entered', 0)}/{stat.get('total_students', 0)}</b>\n"
        f"👨‍👩‍👧 Xabar oladigan ota-onalar: <b>{int(linked)}</b>\n\n"
        "Har bir ota-onaga faqat o'z farzandining natijasi yuboriladi.",
        kb.confirm_kb(f"tst:pubyes:{test_id}", f"tst:v:{test_id}", "📢 Ha, e'lon qilish"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tst:pubyes:"))
async def test_publish(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    test_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_test(db, user, test_id):
        await ui.deny(callback)
        return
    test = await tests.get_test(db, test_id)
    if not test:
        await callback.answer("Topilmadi", show_alert=True)
        return
    center = await settings_service.get(db, "center_name", "Excellence LC")
    support = await settings_service.get(db, "support_username", "")
    auto_send = await settings_service.get_bool(db, "auto_result_notify", True)
    rows = await tests.results(db, test_id)
    queued = 0
    unlinked = 0
    if auto_send:
        for row in rows:
            percent = score_percent(row["score"], float(test["max_score"]))
            prev = None
            delta_text = ""
            if not row["is_absent"] and row["score"] is not None:
                prev = await tests.previous_result(db, student_id=int(row["student_id"]), test=test)
                if prev and prev.get("score") is not None:
                    if float(prev["max_score"]) == float(test["max_score"]):
                        diff = float(row["score"]) - float(prev["score"])
                        delta_text = trend(diff) + (" ball" if abs(diff) >= 0.01 else "")
                    else:
                        prev_percent = score_percent(prev["score"], float(prev["max_score"])) or 0
                        diff = (percent or 0) - prev_percent
                        delta_text = trend(diff) + ("%" if abs(diff) >= 0.01 else "")
            band = None
            if not row["is_absent"] and float(test["max_score"]) == 40 and test["kind"] in ("mock", "exam"):
                band = row.get("band")
            text = messages.result_message(
                student_name=row["student_name"],
                group_name=test["group_name"],
                test_title=test["title"],
                test_kind=test["kind"],
                date=test["date"],
                score=row["score"],
                max_score=float(test["max_score"]),
                percent=percent,
                band=band,
                delta_text=delta_text,
                note=row.get("note"),
                teacher_name=test.get("teacher_name"),
                center_name=center,
                support=support,
                is_absent=bool(row["is_absent"]),
            )
            result = await notifications.queue_to_parents(
                db,
                student_id=int(row["student_id"]),
                kind="result",
                text=text,
                dedupe_base=f"result:{test_id}:{row['student_id']}",
            )
            queued += result["queued"]
            unlinked += result["unlinked"]
    await tests.publish(db, test_id)
    await audit(db, user, "test_publish", "test", test_id, {"queued": queued, "unlinked": unlinked})
    if auto_send:
        head = "📢 <b>Natijalar navbatga qo'yildi</b>"
        body = (
            f"✅ Yuboriladi: <b>{queued}</b> ta ota-onaga\n"
            + (f"⚠️ Telegram ulanmagan: <b>{unlinked}</b>\n" if unlinked else "")
            + "\nXabarlar bir necha soniya ichida yetib boradi."
        )
    else:
        head = "📢 <b>Natijalar e'lon qilindi</b>"
        body = (
            "ℹ️ Avtomatik xabar yuborish o'chirilgan (⚙️ Sozlamalar).\n"
            "Natijalar ota-onalar panelida ko'rinadi."
        )
    await ui.send(
        callback,
        f"{head}\n\n{body}",
        kb.ikb([
            [("📈 Statistika", f"tst:stats:{test_id}")],
            [("⬅️ Test kartasi", f"tst:v:{test_id}")],
        ]),
    )
    await callback.answer("E'lon qilindi")


# ---------- Statistika / natijalar / CSV / o'chirish ----------

@router.callback_query(F.data.startswith("tst:stats:"))
async def test_stats(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    test_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_test(db, user, test_id):
        await ui.deny(callback)
        return
    stat = await tests.stats(db, test_id)
    if not stat:
        await callback.answer("Topilmadi", show_alert=True)
        return
    test = stat["test"]
    text = (
        f"📈 <b>{esc(test['title'])}</b> — statistika\n"
        f"📅 {esc(fmt_date(test['date']))} · 🎚 {test['max_score']:g}\n\n"
        f"👥 Kiritilgan: <b>{stat['entered']}/{stat['total_students']}</b> · ❌ {stat['absent']}\n"
    )
    if stat["average"] is not None:
        text += (
            f"📊 O'rtacha: <b>{stat['average']:.1f}</b> ({stat['average_percent']:.0f}%)\n"
            f"📌 Mediana: <b>{stat['median']:.1f}</b>\n"
            f"🔺 Eng yuqori: <b>{stat['highest']:g}</b> · 🔻 Eng past: <b>{stat['lowest']:g}</b>\n"
            f"✅ 60%+ natija: <b>{stat['pass_rate']:.0f}%</b>\n"
        )
        if stat["average_band"] is not None and test["kind"] in ("mock", "exam"):
            text += f"🎯 O'rtacha band: <b>{stat['average_band']:.1f}</b>\n"
        labels = ["0-20%", "21-40%", "41-60%", "61-80%", "81-100%"]
        text += "\n<b>Taqsimot:</b>\n"
        for label, count in zip(labels, stat["buckets"]):
            text += f"{label}: {count} {'▰' * count}\n"
        if stat["ranking"]:
            text += "\n🏆 <b>Eng yaxshi natijalar:</b>\n"
            medals = ["🥇", "🥈", "🥉"]
            for i, row in enumerate(stat["ranking"][:5]):
                prefix = medals[i] if i < 3 else f"{i + 1}."
                text += f"{prefix} {esc(row['student_name'])} — {float(row['score']):g}\n"
    else:
        text += "\nHozircha baholangan natija yo'q."
    await ui.send(callback, text, kb.ikb([
        [("📋 Barcha natijalar", f"tst:res:{test_id}:1"), ("📥 CSV", f"tst:csv:{test_id}")],
        [("⬅️ Test kartasi", f"tst:v:{test_id}")],
    ]))
    await callback.answer()


@router.callback_query(F.data.startswith("tst:res:"))
async def test_results(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    parts = callback.data.split(":")
    test_id = safe_int(parts[2])
    page = safe_int(parts[3] if len(parts) > 3 else 1, 1, 1, 999)
    if not await permissions.can_manage_test(db, user, test_id):
        await ui.deny(callback)
        return
    test = await tests.get_test(db, test_id)
    rows_data = await tests.results(db, test_id)
    chunk, page, pages, total = paginate(rows_data, page, 10)
    text = f"📋 <b>{esc(test['title'] if test else '')}</b> — natijalar ({total})\n\n"
    for row in chunk:
        if row["is_absent"]:
            text += f"❌ {esc(row['student_name'])} — qatnashmadi\n"
        else:
            percent = score_percent(row["score"], float(test["max_score"])) if test else 0
            text += f"• {esc(row['student_name'])} — <b>{float(row['score']):g}</b> ({percent:.0f}%)\n"
    rows: list[list[tuple[str, str]]] = []
    if pages > 1:
        rows.append(kb.pager(f"tst:res:{test_id}", page, pages))
    rows.append([("⬅️ Test kartasi", f"tst:v:{test_id}")])
    await ui.send(callback, text, kb.ikb(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("tst:csv:"))
async def test_csv(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin", "teacher"):
        return
    test_id = safe_int(callback.data.split(":")[2])
    if not await permissions.can_manage_test(db, user, test_id):
        await ui.deny(callback)
        return
    data, filename = await exports.test_results_csv(db, test_id)
    if callback.message:
        await callback.message.answer_document(BufferedInputFile(data, filename=filename), caption="📥 Test natijalari (CSV)")
    await callback.answer("Yuborildi")


@router.callback_query(F.data.startswith("tst:del:"))
async def test_delete_prompt(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    test_id = safe_int(callback.data.split(":")[2])
    test = await tests.get_test(db, test_id)
    if not test:
        await callback.answer("Topilmadi", show_alert=True)
        return
    count = int(await db.scalar("SELECT COUNT(*) FROM test_results WHERE test_id=?", (test_id,)) or 0)
    await ui.send(
        callback,
        f"🗑 <b>{esc(test['title'])}</b> butunlay o'chirilsinmi?\n\n"
        f"⚠️ {count} ta natija ham o'chadi. Bu amalni qaytarib bo'lmaydi.",
        kb.confirm_kb(f"tst:delyes:{test_id}", f"tst:v:{test_id}", "🗑 Ha, o'chirish"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tst:delyes:"))
async def test_delete(callback: CallbackQuery, db: Database, user: dict | None) -> None:
    if not await ui.require(callback, user, "superadmin", "admin"):
        return
    test_id = safe_int(callback.data.split(":")[2])
    test = await tests.get_test(db, test_id)
    if test:
        await db.execute("DELETE FROM tests WHERE id=?", (test_id,))
        await audit(db, user, "test_delete", "test", test_id, {"title": test["title"]})
    await callback.answer("O'chirildi")
    await show_test_list(callback, db, user, page=1)

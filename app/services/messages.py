"""Ota-onalar va o'qituvchilar uchun sodda, tushunarli xabar matnlari."""
from __future__ import annotations

from typing import Any

from app.utils import esc, fmt_date_long, fmt_phone, fmt_score, kind_label


def _footer(center_name: str, support: str) -> str:
    lines = []
    if support:
        handle = support if support.startswith("@") else "@" + support
        lines.append(f"☎️ Savollar uchun: {esc(handle)}")
    return ("\n\n" + "\n".join(lines)) if lines else ""


def absence_message(
    *,
    student_name: str,
    group_name: str,
    date: str,
    status: str,
    teacher_name: str | None,
    center_name: str,
    support: str,
    note: str | None = None,
) -> str:
    if status == "late":
        title = "⏰ <b>Kechikish xabari</b>"
        body = "bugungi darsga kechikdi."
    elif status == "excused":
        title = "ℹ️ <b>Davomat xabari</b>"
        body = "bugungi darsga sababli kelmadi."
    else:
        title = "⚠️ <b>Davomat xabari</b>"
        body = "bugungi darsga <b>kelmadi</b>."
    text = (
        f"{title}\n\n"
        f"👤 <b>{esc(student_name)}</b>\n"
        f"🗂 {esc(group_name)}\n"
        f"📅 {esc(fmt_date_long(date))}\n\n"
        f"Farzandingiz {body}"
    )
    if note:
        text += f"\n💬 Izoh: {esc(note)}"
    if teacher_name:
        text += f"\n👨‍🏫 O'qituvchi: {esc(teacher_name)}"
    text += "\n\nIltimos, sababini o'qituvchiga yuboring yoki markaz bilan bog'laning."
    return text + _footer(center_name, support)


def result_message(
    *,
    student_name: str,
    group_name: str,
    test_title: str,
    test_kind: str,
    date: str,
    score: float | None,
    max_score: float,
    percent: float | None,
    band: float | None,
    delta_text: str,
    note: str | None,
    teacher_name: str | None,
    center_name: str,
    support: str,
    is_absent: bool = False,
) -> str:
    head = (
        f"📊 <b>{esc(kind_label(test_kind))} natijasi</b>\n\n"
        f"👤 <b>{esc(student_name)}</b>\n"
        f"🗂 {esc(group_name)}\n"
        f"📝 {esc(test_title)}\n"
        f"📅 {esc(fmt_date_long(date))}\n\n"
    )
    if is_absent:
        body = "❌ Farzandingiz bu testda qatnashmadi.\nSababini o'qituvchi bilan aniqlashtiring."
    else:
        body = f"✅ Natija: <b>{esc(fmt_score(score, max_score))}</b>"
        if percent is not None:
            body += f" — <b>{percent:.0f}%</b>"
        if band is not None:
            body += f"\n🎯 Taxminiy IELTS: <b>{band:.1f}</b>"
        if delta_text:
            body += f"\n{delta_text}"
        if percent is not None and percent < 50:
            body += "\n\n💡 Natijani yaxshilash uchun qo'shimcha mashg'ulot tavsiya etiladi."
    if note:
        body += f"\n💬 O'qituvchi izohi: {esc(note)}"
    if teacher_name:
        body += f"\n👨‍🏫 O'qituvchi: {esc(teacher_name)}"
    return head + body + _footer(center_name, support)


def digest_message(
    *,
    parent_name: str,
    children: list[dict[str, Any]],
    center_name: str,
    support: str,
) -> str:
    text = f"📅 <b>Haftalik hisobot</b>\n\nAssalomu alaykum, {esc(parent_name)}!\n"
    for child in children:
        text += f"\n👤 <b>{esc(child['name'])}</b> — {esc(child.get('group') or 'guruhsiz')}\n"
        att = child.get("attendance")
        if att and att.get("total"):
            rate = att.get("rate") or 0
            text += (
                f"✅ Davomat: {att['attended']}/{att['total']} ({rate:.0f}%)\n"
                f"❌ Kelmagan: {att['absent']} kun"
            )
            if att.get("late"):
                text += f" · ⏰ Kechikkan: {att['late']} marta"
            text += "\n"
        latest = child.get("latest_test")
        if latest:
            line = f"📝 {esc(latest['title'])}: {esc(latest['score'])}"
            if latest.get("percent") is not None:
                line += f" ({latest['percent']:.0f}%)"
            if latest.get("band") is not None:
                line += f" · band {latest['band']:.1f}"
            text += line + "\n"
        if child.get("risk"):
            text += f"⚠️ {esc(child['risk'])}\n"
    text += "\nFarzandingiz taraqqiyoti uchun birgalikda ishlaymiz."
    return text + _footer(center_name, support)


def absence_reason_to_teacher(
    *,
    student_name: str,
    parent_name: str,
    parent_phone: str | None,
    date: str,
    reason: str,
    group_name: str | None,
) -> str:
    return (
        "📩 <b>Ota-onadan xabar</b>\n\n"
        f"👤 O'quvchi: <b>{esc(student_name)}</b>\n"
        f"🗂 {esc(group_name or 'guruhsiz')}\n"
        f"📅 {esc(fmt_date_long(date))}\n"
        f"🙋 Xabar yuboruvchi: {esc(parent_name)}"
        + (f" ({esc(fmt_phone(parent_phone))})" if parent_phone else "")
        + f"\n\n💬 Sabab: {esc(reason)}"
    )


def child_risk_note(att_rate: float | None, last_percent: float | None, threshold: float) -> str | None:
    reasons: list[str] = []
    if att_rate is not None and att_rate < threshold:
        reasons.append(f"davomat {att_rate:.0f}% (me'yor {threshold:.0f}%)")
    if last_percent is not None and last_percent < 50:
        reasons.append(f"oxirgi test {last_percent:.0f}%")
    if not reasons:
        return None
    return "E'tibor bering: " + ", ".join(reasons) + "."

"""Umumiy yordamchi funksiyalar: sana, matn, validatsiya, formatlash."""
from __future__ import annotations

import html
import math
import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Sequence, TypeVar
from zoneinfo import ZoneInfo

MONTHS_UZ = {
    1: "yanvar", 2: "fevral", 3: "mart", 4: "aprel", 5: "may", 6: "iyun",
    7: "iyul", 8: "avgust", 9: "sentabr", 10: "oktabr", 11: "noyabr", 12: "dekabr",
}
WEEKDAYS_UZ = {
    0: "dushanba", 1: "seshanba", 2: "chorshanba", 3: "payshanba",
    4: "juma", 5: "shanba", 6: "yakshanba",
}
WEEKDAYS_SHORT = {
    "mon": "Du", "tue": "Se", "wed": "Cho", "thu": "Pay", "fri": "Ju", "sat": "Sha", "sun": "Yak",
}
ALL_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

STATUS_UZ = {
    "present": "keldi",
    "absent": "kelmadi",
    "late": "kechikdi",
    "excused": "sababli",
    "active": "faol",
    "frozen": "muzlatilgan",
    "left": "chiqib ketgan",
    "open": "ochiq",
    "closed": "yopilgan",
}

KIND_UZ = {
    "test": "Test",
    "mock": "Mock",
    "quiz": "Quiz",
    "exam": "Imtihon",
}


def now_local(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def today_str(tz: ZoneInfo) -> str:
    return now_local(tz).strftime("%Y-%m-%d")


def weekday_uz(d: date) -> str:
    return WEEKDAYS_UZ[d.weekday()]


def fmt_date(value: str | date | None) -> str:
    """YYYY-MM-DD -> 15.11.2026"""
    if not value:
        return "—"
    try:
        d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        return d.strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return "—"


def fmt_date_long(value: str | date | None) -> str:
    if not value:
        return "—"
    try:
        d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        return f"{d.day}-{MONTHS_UZ[d.month]}, {d.year}, {weekday_uz(d)}"
    except (ValueError, TypeError):
        return "—"


def fmt_datetime(value: str | None, tz: ZoneInfo | None = None) -> str:
    """UTC 'YYYY-MM-DD HH:MM:SS' -> mahalliy 'DD.MM.YYYY HH:MM'."""
    if not value:
        return "—"
    try:
        dt = datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
        if tz is not None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return "—"


def parse_date(value: str) -> str | None:
    """DD.MM.YYYY yoki YYYY-MM-DD -> YYYY-MM-DD."""
    value = value.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_time(value: str) -> str | None:
    value = value.strip().replace(".", ":")
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def add_days(value: str, days: int) -> str:
    return (date.fromisoformat(value) + timedelta(days=days)).isoformat()


def days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def iso_week(value: str | date | None = None) -> str:
    if isinstance(value, str):
        d = date.fromisoformat(value[:10])
    elif isinstance(value, date):
        d = value
    else:
        d = date.today()
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def clip(value: str | None, limit: int = 120) -> str:
    text = (value or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def clean_text(value: str, limit: int = 500) -> str:
    """Boshqaruv belgilarini olib tashlaydi va uzunlikni cheklaydi."""
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value or "")
    return value.strip()[:limit]


_NAME_RE = re.compile(r"^[^\W\d_][\w'’ʻ.\- ]{1,79}$", re.UNICODE)


def validate_name(value: str) -> str | None:
    value = re.sub(r"\s+", " ", clean_text(value, 80)).strip()
    if not (2 <= len(value) <= 80):
        return None
    if not _NAME_RE.fullmatch(value):
        return None
    if "http://" in value.lower() or "https://" in value.lower() or "@" in value:
        return None
    return value


def normalize_phone(value: str) -> str | None:
    """+998901234567 formatiga keltiradi. Faqat O'zbekiston raqamlari."""
    value = (value or "").strip()
    digits = re.sub(r"\D", "", value)
    if len(digits) == 9:
        digits = "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        digits = digits[3:]
    if len(digits) != 9 or not digits.startswith(("9", "8", "7", "6", "5", "3")):
        return None
    return "+998" + digits


def fmt_phone(phone: str | None) -> str:
    if not phone:
        return "—"
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 12 and digits.startswith("998"):
        return f"+998 {digits[3:5]} {digits[5:8]} {digits[8:12]}"
    return phone


def parse_float(value: str, lo: float, hi: float) -> float | None:
    try:
        number = float(value.strip().replace(",", "."))
    except (ValueError, AttributeError):
        return None
    if not math.isfinite(number) or number < lo or number > hi:
        return None
    return number


def score_percent(score: float | None, max_score: float) -> float | None:
    if score is None or max_score <= 0:
        return None
    return max(0.0, min(100.0, score / max_score * 100.0))


# IELTS Academic Reading/Listening jadvali (40 ballik)
_IELTS = (
    (39, 9.0), (37, 8.5), (35, 8.0), (33, 7.5), (30, 7.0), (27, 6.5),
    (23, 6.0), (20, 5.5), (16, 5.0), (13, 4.5), (10, 4.0), (7, 3.5),
    (6, 3.0), (5, 2.5), (4, 2.0), (3, 1.5), (2, 1.0), (1, 0.5), (0, 0.0),
)


def estimate_band(score: float | None, max_score: float) -> float | None:
    if score is None or max_score <= 0:
        return None
    normalized = max(0.0, min(40.0, score / max_score * 40.0))
    for threshold, band in _IELTS:
        if normalized >= threshold:
            return band
    return 0.0


def fmt_band(band: float | None) -> str:
    if band is None:
        return "—"
    return f"{band:.1f}"


def fmt_score(score: float | None, max_score: float) -> str:
    if score is None:
        return "—"
    s = f"{score:g}"
    return f"{s}/{max_score:g}"


def trend(delta: float | None) -> str:
    if delta is None:
        return ""
    if abs(delta) < 0.01:
        return "➖ o'zgarishsiz"
    if delta > 0:
        return f"📈 +{delta:g}"
    return f"📉 {delta:g}"


def bar(value: float | None, maximum: float = 100, width: int = 10) -> str:
    if value is None:
        return "—"
    filled = 0 if maximum <= 0 else int(round(max(0.0, min(1.0, value / maximum)) * width))
    return "▰" * filled + "▱" * (width - filled)


def money(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}".replace(",", " ") + " so'm"


T = TypeVar("T")


def paginate(items: Sequence[T], page: int, per_page: int = 8) -> tuple[list[T], int, int, int]:
    total = len(items)
    pages = max(1, math.ceil(total / per_page))
    page = max(1, min(pages, page))
    start = (page - 1) * per_page
    return list(items[start:start + per_page]), page, pages, total


def chunks(seq: Sequence[T], size: int) -> Iterable[Sequence[T]]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def csv_safe(value: Any) -> str:
    """Excel formula injection himoyasi."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        text = "'" + text
    return text


def format_days(days: str | None) -> str:
    if not days:
        return "—"
    parts = [WEEKDAYS_SHORT.get(part.strip()[:3].lower(), part) for part in days.split(",") if part.strip()]
    return ", ".join(parts) if parts else "—"


def status_label(value: str) -> str:
    return STATUS_UZ.get(value, value)


def kind_label(value: str) -> str:
    return KIND_UZ.get(value, value)


def safe_int(value: Any, default: int = 0, lo: int = 0, hi: int = 10**9) -> int:
    try:
        number = int(value)
    except (ValueError, TypeError):
        return default
    return max(lo, min(hi, number))

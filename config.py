"""Konfiguratsiya: .env faylini o'qiydi va tekshiradi.

Faqat standart kutubxona ishlatiladi — bot yengil qolishi uchun.
"""
from __future__ import annotations

import os
import re
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Oddiy .env parser (python-dotenv shart emas)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(lo, min(hi, value))


def _id_list(name: str) -> tuple[int, ...]:
    ids: list[int] = []
    for part in os.getenv(name, "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            tg_id = int(part)
        except ValueError:
            continue
        if tg_id > 0:
            ids.append(tg_id)
    return tuple(dict.fromkeys(ids))


def _pepper() -> bytes:
    """Doimiy sir. Env bo'lmasa faylga yoziladi (gitignore qilingan)."""
    env = os.getenv("SECRET_PEPPER", "").strip()
    if env:
        return env.encode("utf-8")
    path = BASE_DIR / ".secret_pepper"
    if path.is_file():
        data = path.read_text(encoding="utf-8").strip()
        if len(data) >= 24:
            return data.encode("utf-8")
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value.encode("utf-8")


def _db_path() -> Path:
    raw = os.getenv("DB_PATH", "data/excellence.db").strip() or "data/excellence.db"
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", "").strip())
    superadmin_ids: tuple[int, ...] = field(default_factory=lambda: _id_list("SUPERADMIN_IDS"))
    bootstrap_code: str = field(default_factory=lambda: os.getenv("BOOTSTRAP_CODE", "").strip())
    db_path: Path = field(default_factory=_db_path)
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Tashkent").strip())
    pepper: bytes = field(default_factory=_pepper, repr=False)
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    rate_msg_per_min: int = field(default_factory=lambda: _int("RATE_MSG_PER_MIN", 30, 5, 300))
    rate_callback_per_min: int = field(default_factory=lambda: _int("RATE_CALLBACK_PER_MIN", 60, 10, 600))
    digest_weekday: int = field(default_factory=lambda: _int("DIGEST_WEEKDAY", 0, 0, 6))
    digest_hour: int = field(default_factory=lambda: _int("DIGEST_HOUR", 9, 0, 23))
    center_name: str = field(default_factory=lambda: os.getenv("CENTER_NAME", "Excellence LC").strip())

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except Exception:
            return ZoneInfo("Asia/Tashkent")

    @property
    def data_dir(self) -> Path:
        return self.db_path.parent

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    def validate(self) -> None:
        problems: list[str] = []
        if not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,}", self.bot_token or ""):
            problems.append("BOT_TOKEN noto'g'ri yoki bo'sh (.env faylini to'ldiring).")
        if not self.superadmin_ids and not self.bootstrap_code:
            problems.append(
                "SUPERADMIN_IDS yoki BOOTSTRAP_CODE dan kamida bittasi kerak. "
                "Aks holda botga hech kim admin sifatida kira olmaydi."
            )
        if self.bootstrap_code and len(self.bootstrap_code) < 8:
            problems.append("BOOTSTRAP_CODE kamida 8 belgidan iborat bo'lishi kerak.")
        if self.pepper and len(self.pepper) < 24:
            problems.append("SECRET_PEPPER kamida 24 belgi bo'lsin.")
        if problems:
            print("\n".join("❌ " + p for p in problems), file=sys.stderr)
            raise SystemExit(2)

    def prepare_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass


settings = Settings()

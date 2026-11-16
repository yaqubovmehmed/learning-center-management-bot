"""Xavfsizlik yadrosi: rate limit, taklif tokenlari, audit, yordamchilar."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from typing import Any, Deque

from app.db import Database, utc_now

# ---- Rate limiting (xotirada, yengil) ----

class SlidingWindowLimiter:
    """Foydalanuvchi + amal bo'yicha sirpanuvchi oyna."""

    def __init__(self) -> None:
        self._hits: dict[tuple[int, str], Deque[float]] = defaultdict(deque)
        self._last_notice: dict[int, float] = {}

    def allow(self, user_id: int, action: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        q = self._hits[(user_id, action)]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def should_notice(self, user_id: int, cooldown: float = 20.0) -> bool:
        now = time.monotonic()
        last = self._last_notice.get(user_id, 0.0)
        if now - last < cooldown:
            return False
        self._last_notice[user_id] = now
        return True

    def cleanup(self, older_than: float = 600.0) -> None:
        now = time.monotonic()
        for key in list(self._hits):
            q = self._hits[key]
            while q and now - q[0] > older_than:
                q.popleft()
            if not q:
                self._hits.pop(key, None)
        for user_id, ts in list(self._last_notice.items()):
            if now - ts > older_than:
                self._last_notice.pop(user_id, None)


limiter = SlidingWindowLimiter()


# ---- Taklif tokenlari ----

def make_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str, pepper: bytes) -> str:
    return hmac.new(pepper, token.encode("utf-8"), hashlib.sha256).hexdigest()


def invite_url(bot_username: str, token: str) -> str:
    return f"https://t.me/{bot_username}?start=p_{token}"


def teacher_invite_url(bot_username: str, token: str) -> str:
    return f"https://t.me/{bot_username}?start=t_{token}"


def constant_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def mask_phone(phone: str | None) -> str:
    if not phone:
        return "—"
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 7:
        return "•••"
    return f"+{digits[:3]} ••• •• {digits[-2:]}"


# ---- Audit ----

async def audit(
    db: Database,
    actor: dict[str, Any] | None,
    action: str,
    target_type: str | None = None,
    target_id: Any = None,
    details: dict[str, Any] | str | None = None,
) -> None:
    """Muhim amallarni o'zgarmas jurnalga yozadi. Maxfiy ma'lumot yozilmaydi."""
    if isinstance(details, dict):
        details_text = json.dumps(details, ensure_ascii=False, default=str)[:2000]
    else:
        details_text = (details or "")[:2000] or None
    await db.execute(
        "INSERT INTO audit_log(actor_id, actor_tg, action, target_type, target_id, details, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            actor.get("id") if actor else None,
            actor.get("tg_id") if actor else None,
            action,
            target_type,
            str(target_id) if target_id is not None else None,
            details_text,
            utc_now(),
        ),
    )


def redact(text: str, *secrets_: str) -> str:
    for secret in secrets_:
        if secret:
            text = text.replace(secret, "***")
    return text

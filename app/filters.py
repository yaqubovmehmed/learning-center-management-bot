"""Rolga asoslangan filtrlar.

Bir xil matnli tugmalar turli rollarda uchraydi (masalan "✅ Davomat"),
shuning uchun handlerlar rol bo'yicha ajratiladi.
"""
from __future__ import annotations

from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject


class RoleFilter(BaseFilter):
    def __init__(self, *roles: str) -> None:
        self.roles = frozenset(roles)

    async def __call__(self, event: TelegramObject, **data: Any) -> bool:
        user = data.get("user")
        if not user or not int(user.get("is_active") or 0):
            return False
        return user.get("role") in self.roles


class ActiveUserFilter(BaseFilter):
    async def __call__(self, event: TelegramObject, **data: Any) -> bool:
        user = data.get("user")
        return bool(user and int(user.get("is_active") or 0))

"""Callback_data to'qnashuvlarini tekshiradi (CI uchun).

Ishlatish: python tests/check_callbacks.py
Xatolik topilsa 1 kod bilan chiqadi.
"""
from __future__ import annotations

import ast
import collections
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

exact: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
prefix: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)

for p in sorted(pathlib.Path("app/handlers").glob("*.py")):
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                src = ast.unparse(dec)
                if "F.data == " in src:
                    for sub in ast.walk(dec):
                        if (
                            isinstance(sub, ast.Constant)
                            and isinstance(sub.value, str)
                            and ":" in sub.value
                        ):
                            exact[sub.value].append((p.name, node.name))
                if "startswith" in src:
                    for sub in ast.walk(dec):
                        if (
                            isinstance(sub, ast.Constant)
                            and isinstance(sub.value, str)
                            and sub.value.endswith(":")
                        ):
                            prefix[sub.value].append((p.name, node.name))

problems = 0

print("Exact duplicates:")
for key, value in exact.items():
    if len(value) > 1:
        problems += 1
        print(" ", key, "->", value)

print("Prefix collisions:")
keys = sorted(prefix)
for a in keys:
    for b in keys:
        if a != b and b.startswith(a):
            problems += 1
            print(" ", a, "<->", b, prefix[a], prefix[b])

if problems:
    print(f"\n❌ {problems} ta to'qnashuv topildi.")
    raise SystemExit(1)
print("\n✅ Callback to'qnashuvlari yo'q.")

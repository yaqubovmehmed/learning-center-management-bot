#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/3] Virtual muhit yaratilmoqda..."
  python3 -m venv .venv
fi

echo "[2/3] Kutubxonalar tekshirilmoqda..."
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "[!] .env yaratildi. Uni to'ldirib, qayta ishga tushiring."
  exit 1
fi

echo "[3/3] Bot ishga tushmoqda..."
exec .venv/bin/python main.py

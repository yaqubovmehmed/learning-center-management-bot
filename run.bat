@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Virtual muhit yaratilmoqda...
    python -m venv .venv || goto :error
)

echo [2/3] Kutubxonalar tekshirilmoqda...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt || goto :error

if not exist ".env" (
    echo.
    echo [!] .env fayli topilmadi. .env.example dan nusxa olinmoqda.
    copy ".env.example" ".env" >nul
    echo [!] Iltimos, .env faylini to'ldiring va run.bat ni qayta ishga tushiring.
    notepad ".env"
    pause
    exit /b 1
)

echo [3/3] Bot ishga tushmoqda...
".venv\Scripts\python.exe" main.py
goto :eof

:error
echo.
echo [X] Xatolik yuz berdi. Python 3.11+ o'rnatilganini tekshiring.
pause
exit /b 1

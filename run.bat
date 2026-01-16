@echo off
set BOT_USERNAME=admin
set BOT_PASSWORD=secure123
set HOST=0.0.0.0
set PORT=8000
set PYTHONPATH=src

REM 启动（Windows 会自动使用 waitress）
python -m telegram_bot
pause

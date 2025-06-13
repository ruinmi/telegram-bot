@echo off
set BOT_USERNAME=admin
set BOT_PASSWORD=secure123
set HOST=0.0.0.0
set PORT=8000

REM 启动 waitress（仅用于 Windows）
python server.py
pause

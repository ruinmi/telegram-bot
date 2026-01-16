#!/bin/bash
export BOT_USERNAME=admin
export BOT_PASSWORD=secure123
export HOST=0.0.0.0
export PORT=8000

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}/src${PYTHONPATH:+:$PYTHONPATH}"

# 推荐生产环境使用 gunicorn
gunicorn -w 4 -b $HOST:$PORT telegram_bot.web_server:app

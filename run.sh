#!/bin/bash
export BOT_USERNAME=admin
export BOT_PASSWORD=secure123
export HOST=0.0.0.0
export PORT=8000

# 如果是开发阶段使用 Flask 自带服务器
# python server.py

# 推荐生产环境使用 gunicorn
gunicorn -w 4 -b $HOST:$PORT server:app

# Telegram Chat Archiver and Web Viewer

## Overview
This project exports Telegram chats using the [`tdl`](https://github.com/iyear/tdl) command line tool and presents them through a small FastAPI web interface. Messages are saved in SQLite databases, attachments can be downloaded automatically and the viewer fetches Open Graph data for link previews.

## Features
- Export history via `update_messages.py` and `tdl chat export`.
- Optional attachment download with `tdl dl`.
- Parse and store messages in per chat SQLite databases.
- Web server to manage chats and browse them.
- Background workers periodically update chats based on saved settings.
- Searchable HTML viewer with inline media display and link previews.

## Important Files
- Backend source code lives under `src/telegram_bot/`.
- `src/telegram_bot/update_messages.py` – run `tdl` to export messages and files.
- `src/telegram_bot/archiver.py` – coordinates export, parses JSON and saves messages to the database.
- `src/telegram_bot/web_server.py` – FastAPI server providing the management interface and chat pages.
- Frontend: `templates/` + `static/`.
- Example startup scripts: `run.sh` / `run.bat` and `telegrambot.service`.

## Quick Start
1. Install Python 3 and the `tdl` tool.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Log in with `tdl`:
   ```bash
   tdl login -T qr
   ```
4. Start the server:
   ```bash
   BOT_PASSWORD=yourpassword PYTHONPATH=src python -m telegram_bot
   ```
   The server listens on `127.0.0.1:8000`. Visit `http://localhost:8000/` to add a chat and start its worker. Open `/chat/<chat_id>` to browse messages.

## Notes
- Ensure you have permission to archive the desired Telegram chats.

---

# Telegram 聊天记录归档与网页查看器

## 简介
本项目借助 [`tdl`](https://github.com/iyear/tdl) 工具导出 Telegram 聊天记录，将消息保存到 SQLite 数据库，并提供可搜索的 FastAPI 网页界面。可以自动下载附件并抓取链接的 Open Graph 预览信息。

## 功能
- 通过 `update_messages.py` 调用 `tdl chat export` 导出聊天记录。
- 可选地使用 `tdl dl` 下载聊天中的文件。
- 解析 JSON 数据并写入各聊天对应的 SQLite 数据库。
- FastAPI 服务器提供管理界面，可启动后台线程定期更新聊天。
- 浏览聊天时支持搜索、无限滚动、媒体展示以及链接预览。
- 所有数据存放在 `data/` 与 `downloads/` 目录下。

## 重要文件
- 后端源码在 `src/telegram_bot/` 下。
- `src/telegram_bot/update_messages.py`：封装 `tdl` 导出聊天和附件。
- `src/telegram_bot/archiver.py`：协调导出、解析 JSON 并写入数据库。
- `src/telegram_bot/web_server.py`：FastAPI 服务器，提供管理界面及聊天页面。
- 前端资源：`templates/`、`static/`。
- 启动脚本示例：`run.sh`、`run.bat`、`telegrambot.service`。

## 快速开始
1. 安装 Python 3 与 `tdl` 工具。
2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
3. 使用 `tdl` 登录：
   ```bash
   tdl login -T qr
   ```
4. 启动服务器：
   ```bash
   BOT_PASSWORD=你的密码 PYTHONPATH=src python -m telegram_bot
   ```
   服务器默认在 `127.0.0.1:8000` 监听。访问 `http://localhost:8000/` 添加聊天后启动后台线程，再在 `/chat/<chat_id>` 查看聊天记录。

## 注意
- 请确保有权限访问并归档相应的 Telegram 聊天。

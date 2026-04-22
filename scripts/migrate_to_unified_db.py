from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from telegram_bot.db_utils import (  # noqa: E402
    get_connection,
    set_exported_time,
    set_last_export_time,
    set_workers_status,
    upsert_chat,
)


def load_chats_json(chats_file: Path) -> list[dict]:
    if not chats_file.exists():
        return []
    with chats_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def load_old_messages(old_db_path: Path) -> list[dict]:
    conn = sqlite3.connect(str(old_db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM messages ORDER BY timestamp, msg_id").fetchall()
        messages = []
        for row in rows:
            item = dict(row)
            sender_id = item.get("sender_id")
            is_self = item.get("is_self")
            if sender_id is None:
                sender_id = "" if item.get("user") == "我" else str(item.get("user") or "")
            if is_self is None:
                is_self = 1 if item.get("user") == "我" else 0
            item["sender_id"] = sender_id
            item["is_self"] = int(is_self)
            messages.append(item)
        return messages
    finally:
        conn.close()


def load_old_meta(old_db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(str(old_db_path))
    try:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
        return {str(key): str(value) for key, value in rows}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def iter_old_chat_dbs(data_dir: Path):
    for child in sorted(data_dir.iterdir() if data_dir.exists() else []):
        if not child.is_dir():
            continue
        old_db = child / "messages.db"
        if old_db.exists():
            yield child.name, old_db


def main() -> int:
    chats_file = ROOT / "chats.json"
    data_dir = ROOT / "data"

    chats = load_chats_json(chats_file)
    migrated_chats = 0
    migrated_messages = 0

    app_conn = get_connection("__global__")
    app_conn.close()

    for chat in chats:
        conn = get_connection(str(chat.get("id") or chat.get("chat_id") or ""))
        try:
            upsert_chat(conn, chat)
            migrated_chats += 1
        finally:
            conn.close()

    for chat_id, old_db in iter_old_chat_dbs(data_dir):
        messages = load_old_messages(old_db)
        meta = load_old_meta(old_db)
        conn = get_connection(chat_id)
        try:
            if not any(str(chat.get("id")) == str(chat_id) for chat in chats):
                upsert_chat(conn, {"id": chat_id, "remark": chat_id})
                migrated_chats += 1
            if messages:
                from telegram_bot.db_utils import save_messages  # noqa: E402

                save_messages(conn, chat_id, messages)
                migrated_messages += len(messages)
            if "last_export_time" in meta:
                set_last_export_time(conn, meta["last_export_time"])
            if "exported_time" in meta:
                set_exported_time(conn, meta["exported_time"])
            if "workers_status" in meta:
                set_workers_status(conn, meta["workers_status"])
        finally:
            conn.close()

    print(f"迁移完成：聊天 {migrated_chats} 个，消息 {migrated_messages} 条")
    print("目标数据库：data/app.db")
    print("建议保留原 data/<chat_id>/messages.db 与 chats.json 作为备份，确认无误后再手动清理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

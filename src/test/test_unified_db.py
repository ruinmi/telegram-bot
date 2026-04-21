import sqlite3

from telegram_bot import db_utils, message_utils


def test_parse_messages_sets_sender_id_and_is_self(monkeypatch):
    monkeypatch.setattr(message_utils, "filter_messages", lambda items: items)
    monkeypatch.setattr(message_utils, "load_me_id", lambda: "42")

    raw_messages = [
        {
            "id": 1,
            "text": "hello",
            "date": 1710000000,
            "raw": {"FromID": {"UserID": "42"}},
        },
        {
            "id": 2,
            "text": "world",
            "date": 1710000001,
            "raw": {"FromID": {"UserID": "99"}},
        },
    ]

    messages = message_utils.parse_messages("chat-a", raw_messages, tz=None, remark="test")

    assert messages[0]["sender_id"] == "42"
    assert messages[0]["is_self"] == 1
    assert messages[0]["user"] == "我"

    assert messages[1]["sender_id"] == "99"
    assert messages[1]["is_self"] == 0
    assert messages[1]["user"] == "99"


def test_init_app_db_creates_unified_tables(tmp_path, monkeypatch):
    app_db = tmp_path / "app.db"
    monkeypatch.setattr(db_utils, "APP_DB_PATH", app_db)

    conn = db_utils.get_app_connection()
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()

    assert {"chats", "messages", "search_scopes", "search_scope_items", "meta"}.issubset(tables)


def test_unified_chat_scope_and_global_search(tmp_path, monkeypatch):
    app_db = tmp_path / "app.db"
    monkeypatch.setattr(db_utils, "APP_DB_PATH", app_db)

    conn = db_utils.get_app_connection(row_factory=sqlite3.Row)
    try:
        db_utils.upsert_chat(conn, {"id": "chat-1", "remark": "频道一", "username": "chan1"})
        db_utils.upsert_chat(conn, {"id": "chat-2", "remark": "频道二", "username": "chan2"})

        db_utils.save_messages(
            conn,
            "chat-1",
            [
                {
                    "msg_id": 1,
                    "date": "2024-01-01 00:00:00",
                    "timestamp": 1,
                    "msg_file_name": "",
                    "msg_files": [],
                    "user": "我",
                    "sender_id": "42",
                    "is_self": 1,
                    "msg": "alpha keyword",
                    "reply_to_msg_id": 0,
                    "reply_to_top_id": 0,
                    "replies_num": 0,
                    "reactions": {},
                    "ori_height": None,
                    "ori_width": None,
                    "og_info": None,
                }
            ],
        )
        db_utils.save_messages(
            conn,
            "chat-2",
            [
                {
                    "msg_id": 2,
                    "date": "2024-01-01 00:00:01",
                    "timestamp": 2,
                    "msg_file_name": "",
                    "msg_files": [],
                    "user": "对方",
                    "sender_id": "99",
                    "is_self": 0,
                    "msg": "beta keyword",
                    "reply_to_msg_id": 0,
                    "reply_to_top_id": 0,
                    "replies_num": 0,
                    "reactions": {},
                    "ori_height": None,
                    "ori_width": None,
                    "og_info": None,
                }
            ],
        )

        scope = db_utils.upsert_search_scope(conn, name="常用范围", chat_ids=["chat-2"])
        scopes = db_utils.list_search_scopes(conn)
        result = db_utils.search_messages_global(conn, query="keyword", chat_ids=["chat-2"], offset=0, limit=20)
    finally:
        conn.close()

    assert any(item["name"] == "常用范围" for item in scopes)
    assert scope["chat_ids"] == ["chat-2"]
    assert result["total"] == 1
    assert result["messages"][0]["chat_id"] == "chat-2"
    assert result["messages"][0]["chat_remark"] == "频道二"


def test_upsert_search_scope_rejects_missing_scope_id(tmp_path, monkeypatch):
    app_db = tmp_path / "app.db"
    monkeypatch.setattr(db_utils, "APP_DB_PATH", app_db)

    conn = db_utils.get_app_connection(row_factory=sqlite3.Row)
    try:
        try:
            db_utils.upsert_search_scope(conn, name="不存在", chat_ids=["chat-1"], scope_id=999)
            raised = False
        except ValueError:
            raised = True
    finally:
        conn.close()

    assert raised is True

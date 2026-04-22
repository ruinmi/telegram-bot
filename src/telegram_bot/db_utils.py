import json
import re
import sqlite3
import time
from pathlib import Path

from .paths import DATA_DIR

APP_DB_PATH = DATA_DIR / "app.db"


class AppConnection(sqlite3.Connection):
    chat_id: str | None = None


def get_app_db_path() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return str(APP_DB_PATH)


def get_db_path(chat_id=None):
    return get_app_db_path()


def _conn_chat_scope(conn: sqlite3.Connection) -> str:
    return str(getattr(conn, "chat_id", "") or "")


def init_db(conn):
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS messages(
            chat_id TEXT NOT NULL,
            msg_id INTEGER NOT NULL,
            date TEXT,
            timestamp INTEGER,
            msg_file_name TEXT,
            user TEXT,
            sender_id TEXT,
            is_self INTEGER DEFAULT 0,
            msg TEXT,
            ori_height INTEGER,
            ori_width INTEGER,
            og_info TEXT,
            reactions TEXT,
            replies_num INTEGER DEFAULT 0,
            msg_files TEXT,
            reply_to_msg_id INTEGER,
            reply_to_top_id INTEGER DEFAULT 0,
            PRIMARY KEY(chat_id, msg_id)
        )
    '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS meta(
            chat_id TEXT NOT NULL DEFAULT '',
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY(chat_id, key)
        )
    '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS chats(
            id TEXT PRIMARY KEY,
            remark TEXT,
            username TEXT,
            download_files INTEGER NOT NULL DEFAULT 1,
            download_images_only INTEGER NOT NULL DEFAULT 0,
            all_messages INTEGER NOT NULL DEFAULT 1,
            raw_messages INTEGER NOT NULL DEFAULT 1,
            refresh_reactions INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0
        )
    '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS search_scopes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0
        )
    '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS search_scope_items(
            scope_id INTEGER NOT NULL,
            chat_id TEXT NOT NULL,
            PRIMARY KEY(scope_id, chat_id)
        )
    '''
    )

    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
        if "replies_num" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN replies_num INTEGER DEFAULT 0")
            conn.execute("UPDATE messages SET replies_num=0 WHERE replies_num IS NULL")
        if "reply_to_top_id" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN reply_to_top_id INTEGER DEFAULT 0")
            conn.execute("UPDATE messages SET reply_to_top_id=0 WHERE reply_to_top_id IS NULL")
        if "sender_id" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN sender_id TEXT")
        if "is_self" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN is_self INTEGER DEFAULT 0")
            conn.execute("UPDATE messages SET is_self=0 WHERE is_self IS NULL")
    except Exception:
        pass

    conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_chat_ts_id ON messages(chat_id, timestamp, msg_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_chat_reply_to_msg_id ON messages(chat_id, reply_to_msg_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_chat_reply_to_top_id ON messages(chat_id, reply_to_top_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_chat_msg ON messages(chat_id, msg)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_scope_items_chat_id ON search_scope_items(chat_id)')
    conn.commit()


def get_app_connection(row_factory=None, chat_id: str | None = None):
    db_path = get_app_db_path()
    conn = sqlite3.connect(db_path, factory=AppConnection)
    conn.chat_id = str(chat_id or "")
    if row_factory:
        conn.row_factory = row_factory
    init_db(conn)
    return conn


def get_connection(chat_id, row_factory=None):
    return get_app_connection(row_factory=row_factory, chat_id=str(chat_id or ""))


def upsert_chat(conn, chat_item: dict):
    now = int(time.time())
    chat_id = str(chat_item.get("id") or chat_item.get("chat_id") or "").strip()
    if not chat_id:
        raise ValueError("chat id required")

    existing = conn.execute("SELECT created_at FROM chats WHERE id=?", (chat_id,)).fetchone()
    created_at = existing[0] if existing else now
    conn.execute(
        '''
        INSERT INTO chats(
            id, remark, username, download_files, download_images_only,
            all_messages, raw_messages, refresh_reactions, created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            remark=excluded.remark,
            username=excluded.username,
            download_files=excluded.download_files,
            download_images_only=excluded.download_images_only,
            all_messages=excluded.all_messages,
            raw_messages=excluded.raw_messages,
            refresh_reactions=excluded.refresh_reactions,
            updated_at=excluded.updated_at
        ''',
        (
            chat_id,
            chat_item.get("remark"),
            chat_item.get("username"),
            int(bool(chat_item.get("download_files", True))),
            int(bool(chat_item.get("download_images_only", False))),
            int(bool(chat_item.get("all_messages", True))),
            int(bool(chat_item.get("raw_messages", True))),
            int(bool(chat_item.get("refresh_reactions", False))),
            created_at,
            now,
        ),
    )
    conn.commit()
    return get_chat(conn, chat_id)


def get_chat(conn, chat_id: str):
    cursor = conn.execute("SELECT * FROM chats WHERE id=?", (str(chat_id),))
    row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, sqlite3.Row):
        return _normalize_chat(dict(row))
    cols = [d[0] for d in cursor.description or []]
    return _normalize_chat(dict(zip(cols, row)))


def _normalize_chat(item: dict) -> dict:
    item = dict(item)
    for key in ("download_files", "download_images_only", "all_messages", "raw_messages", "refresh_reactions"):
        item[key] = bool(item.get(key))
    return item


def list_chats_db(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM chats ORDER BY COALESCE(remark, id), id").fetchall()
    if rows and isinstance(rows[0], sqlite3.Row):
        return [_normalize_chat(dict(row)) for row in rows]
    return [_normalize_chat({
        "id": row[0], "remark": row[1], "username": row[2], "download_files": row[3],
        "download_images_only": row[4], "all_messages": row[5], "raw_messages": row[6],
        "refresh_reactions": row[7], "created_at": row[8], "updated_at": row[9]
    }) for row in rows]


def delete_chat(conn, chat_id: str) -> bool:
    chat_id = str(chat_id or "").strip()
    if not chat_id:
        return False
    before = conn.total_changes
    conn.execute("DELETE FROM search_scope_items WHERE chat_id=?", (chat_id,))
    conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
    conn.execute("DELETE FROM meta WHERE chat_id=?", (chat_id,))
    conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    conn.commit()
    return (conn.total_changes - before) > 0


def upsert_search_scope(conn, name: str, chat_ids: list[str], scope_id: int | None = None) -> dict:
    name = str(name or "").strip()
    if not name:
        raise ValueError("scope name required")
    chat_ids = [str(chat_id).strip() for chat_id in chat_ids if str(chat_id).strip()]
    now = int(time.time())
    if scope_id is None:
        cur = conn.execute(
            "INSERT INTO search_scopes(name, created_at, updated_at) VALUES(?, ?, ?)",
            (name, now, now),
        )
        scope_id = int(cur.lastrowid)
    else:
        current = conn.execute("SELECT id FROM search_scopes WHERE id=?", (int(scope_id),)).fetchone()
        if not current:
            raise ValueError("scope not found")
        conn.execute(
            "UPDATE search_scopes SET name=?, updated_at=? WHERE id=?",
            (name, now, int(scope_id)),
        )
        conn.execute("DELETE FROM search_scope_items WHERE scope_id=?", (int(scope_id),))

    conn.executemany(
        "INSERT OR IGNORE INTO search_scope_items(scope_id, chat_id) VALUES(?, ?)",
        [(int(scope_id), chat_id) for chat_id in chat_ids],
    )
    conn.commit()
    return get_search_scope(conn, int(scope_id))


def get_search_scope(conn, scope_id: int) -> dict | None:
    row = conn.execute("SELECT id, name, created_at, updated_at FROM search_scopes WHERE id=?", (int(scope_id),)).fetchone()
    if not row:
        return None
    if isinstance(row, sqlite3.Row):
        data = dict(row)
    else:
        data = {"id": row[0], "name": row[1], "created_at": row[2], "updated_at": row[3]}
    items = conn.execute(
        "SELECT chat_id FROM search_scope_items WHERE scope_id=? ORDER BY chat_id",
        (int(scope_id),),
    ).fetchall()
    data["chat_ids"] = [item[0] if not isinstance(item, sqlite3.Row) else item["chat_id"] for item in items]
    return data


def list_search_scopes(conn) -> list[dict]:
    rows = conn.execute("SELECT id FROM search_scopes ORDER BY updated_at DESC, id DESC").fetchall()
    ids = [row[0] if not isinstance(row, sqlite3.Row) else row["id"] for row in rows]
    return [scope for scope in (get_search_scope(conn, int(scope_id)) for scope_id in ids) if scope]


def delete_search_scope(conn, scope_id: int) -> bool:
    before = conn.total_changes
    conn.execute("DELETE FROM search_scope_items WHERE scope_id=?", (int(scope_id),))
    conn.execute("DELETE FROM search_scopes WHERE id=?", (int(scope_id),))
    conn.commit()
    return (conn.total_changes - before) > 0


def search_messages_global(conn, query: str, chat_ids: list[str] | None = None, offset: int = 0, limit: int = 20):
    query = (query or "").strip().lower()
    limit = max(1, min(int(limit), 200))
    offset = max(int(offset), 0)

    params: list = []
    where_parts: list[str] = []
    if chat_ids:
        chat_ids = [str(chat_id).strip() for chat_id in chat_ids if str(chat_id).strip()]
        if chat_ids:
            placeholders = ",".join("?" for _ in chat_ids)
            where_parts.append(f"m.chat_id IN ({placeholders})")
            params.extend(chat_ids)

    if query:
        keywords = [kw for kw in query.split() if kw]
        fields_or = " OR ".join([
            "LOWER(COALESCE(m.date, '')) LIKE ?",
            "LOWER(COALESCE(m.msg, '')) LIKE ?",
            "LOWER(COALESCE(m.msg_file_name, '')) LIKE ?",
            "LOWER(COALESCE(c.remark, '')) LIKE ?",
            "LOWER(COALESCE(c.username, '')) LIKE ?",
        ])
        for kw in keywords:
            neg = kw.startswith("-")
            kw = kw[1:] if neg else kw
            kw = kw.strip().lower()
            if not kw:
                continue
            pattern = f"%{kw}%"
            where_parts.append((f"NOT ({fields_or})" if neg else f"({fields_or})"))
            params.extend([pattern] * 5)

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    count_sql = f"SELECT COUNT(*) FROM messages m LEFT JOIN chats c ON c.id = m.chat_id {where_sql}"
    total = conn.execute(count_sql, tuple(params)).fetchone()[0]

    page_sql = f'''
        SELECT m.*, c.remark AS chat_remark, c.username AS chat_username
        FROM messages m
        LEFT JOIN chats c ON c.id = m.chat_id
        {where_sql}
        ORDER BY m.timestamp DESC, m.msg_id DESC
        LIMIT ? OFFSET ?
    '''
    rows = conn.execute(page_sql, (*params, limit, offset)).fetchall()
    messages = [dict(row) if isinstance(row, sqlite3.Row) else {
        "chat_id": row[0], "msg_id": row[1], "date": row[2], "timestamp": row[3], "msg_file_name": row[4],
        "user": row[5], "sender_id": row[6], "is_self": row[7], "msg": row[8], "ori_height": row[9],
        "ori_width": row[10], "og_info": row[11], "reactions": row[12], "replies_num": row[13],
        "msg_files": row[14], "reply_to_msg_id": row[15], "reply_to_top_id": row[16], "chat_remark": row[17],
        "chat_username": row[18],
    } for row in rows]
    return {"total": total, "offset": offset, "messages": messages}


def save_messages(conn, chat_id, messages):
    insert_sql = '''
        INSERT OR IGNORE INTO messages(
            chat_id, msg_id, date, timestamp,
            msg_file_name, user, sender_id, is_self, msg,
            ori_height, ori_width, og_info, reactions, replies_num, msg_files, reply_to_msg_id, reply_to_top_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''

    data = []
    for m in messages:
        og_info = json.dumps(m.get('og_info'), ensure_ascii=False) if m.get('og_info') else None
        reactions = json.dumps(m.get('reactions'), ensure_ascii=False) if m.get('reactions') else None
        msg_files = json.dumps(m.get('msg_files'), ensure_ascii=False) if m.get('msg_files') else None
        try:
            replies_num = int(m.get("replies_num") or 0)
        except Exception:
            replies_num = 0
        try:
            reply_to_msg_id = int(m.get("reply_to_msg_id") or 0)
        except Exception:
            reply_to_msg_id = 0
        try:
            reply_to_top_id = int(m.get("reply_to_top_id") or 0)
        except Exception:
            reply_to_top_id = 0
        try:
            is_self = int(m.get("is_self") or 0)
        except Exception:
            is_self = 0

        data.append((
            chat_id,
            m["msg_id"],
            m["date"],
            m["timestamp"],
            m["msg_file_name"],
            m["user"],
            m.get("sender_id"),
            is_self,
            m["msg"],
            m["ori_height"],
            m["ori_width"],
            og_info,
            reactions,
            replies_num,
            msg_files,
            reply_to_msg_id,
            reply_to_top_id,
        ))

    before = conn.total_changes
    conn.executemany(insert_sql, data)
    inserted = conn.total_changes - before
    conn.commit()
    return inserted


def _meta_get(conn, key: str):
    chat_scope = _conn_chat_scope(conn)
    row = conn.execute("SELECT value FROM meta WHERE chat_id=? AND key=?", (chat_scope, key)).fetchone()
    return row[0] if row else '0'


def _meta_set(conn, key: str, value):
    chat_scope = _conn_chat_scope(conn)
    conn.execute(
        "INSERT OR REPLACE INTO meta(chat_id, key, value) VALUES(?, ?, ?)",
        (chat_scope, key, str(value)),
    )
    conn.commit()


def get_last_export_time(conn):
    return _meta_get(conn, 'last_export_time')


def set_last_export_time(conn, value):
    _meta_set(conn, 'last_export_time', value)


def get_exported_time(conn):
    return _meta_get(conn, 'exported_time')


def set_exported_time(conn, value):
    _meta_set(conn, 'exported_time', value)


def set_workers_status(conn, status: str):
    _meta_set(conn, 'workers_status', status)


def get_workers_status(conn) -> str:
    return _meta_get(conn, 'workers_status')


def update_og_info(conn, chat_id, og_fetcher):
    cursor = conn.cursor()
    cursor.execute('SELECT msg_id, msg FROM messages WHERE chat_id = ?', (chat_id,))
    rows = cursor.fetchall()
    update_sql = '''
        UPDATE messages
        SET og_info = ?
        WHERE chat_id = ? AND msg_id = ?
    '''
    for msg_id, msg in rows:
        if not msg:
            continue
        links = re.findall(r'(https?://\S+)', msg)
        if not links:
            continue
        try:
            og_info = og_fetcher(links[0])
            og_info_json = json.dumps(og_info, ensure_ascii=False)
            cursor.execute(update_sql, (og_info_json, chat_id, msg_id))
        except Exception:
            continue
    conn.commit()


def update_reactions(conn, chat_id: str, reactions_by_msg_id: list[tuple[int, dict | None]]) -> int:
    if not reactions_by_msg_id:
        return 0

    def _normalize(reactions_obj: dict | None) -> str | None:
        if not isinstance(reactions_obj, dict):
            return None
        results = reactions_obj.get("Results")
        if not isinstance(results, list) or len(results) == 0:
            return None
        return json.dumps(reactions_obj, ensure_ascii=False)

    update_sql = "UPDATE messages SET reactions=? WHERE chat_id=? AND msg_id=?"
    data = [(_normalize(obj), chat_id, int(msg_id)) for msg_id, obj in reactions_by_msg_id if msg_id is not None]
    if not data:
        return 0

    before = conn.total_changes
    conn.executemany(update_sql, data)
    changed = conn.total_changes - before
    conn.commit()
    return changed

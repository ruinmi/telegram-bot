import os
import sqlite3
import json
import re

from .paths import DATA_DIR

def get_db_path(chat_id):
    data_dir = DATA_DIR / str(chat_id)
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / 'messages.db')

def init_db(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages(
            chat_id TEXT,
            msg_id INTEGER,
            date TEXT,
            timestamp INTEGER,
            msg_file_name TEXT,
            user TEXT,
            msg TEXT,
            ori_height INTEGER,
            ori_width INTEGER,
            og_info TEXT,
            reactions TEXT,
            msg_files TEXT,
            reply_to_msg_id INTEGER,
            PRIMARY KEY(chat_id, msg_id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS meta(
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_chat_ts_id ON messages(chat_id, timestamp, msg_id)')
    conn.commit()

def get_connection(chat_id, row_factory=None):
    db_path = get_db_path(chat_id)
    conn = sqlite3.connect(db_path)
    if row_factory:
        conn.row_factory = row_factory
    init_db(conn)
    return conn

def save_messages(conn, chat_id, messages):
    insert_sql = '''
        INSERT OR IGNORE INTO messages(
            chat_id, msg_id, date, timestamp,
            msg_file_name, user, msg,
            ori_height, ori_width, og_info, reactions, msg_files, reply_to_msg_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    data = []
    for m in messages:
        og_info = json.dumps(m.get('og_info'), ensure_ascii=False) if m.get('og_info') else None
        reactions = json.dumps(m.get('reactions'), ensure_ascii=False) if m.get('reactions') else None
        msg_files = json.dumps(m.get('msg_files'), ensure_ascii=False) if m.get('msg_files') else None
        data.append((chat_id, m['msg_id'], m['date'], m['timestamp'],
                     m['msg_file_name'], m['user'], m['msg'],
                     m['ori_height'], m['ori_width'], og_info, reactions, msg_files, m['reply_to_msg_id']))
    before = conn.total_changes
    conn.executemany(insert_sql, data)
    inserted = conn.total_changes - before
    conn.commit()
    return inserted

def get_last_export_time(conn):
    cur = conn.cursor()
    cur.execute("SELECT value FROM meta WHERE key='last_export_time'")
    row = cur.fetchone()
    return row[0] if row else '0'

def set_last_export_time(conn, value):
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('last_export_time', ?)", (str(value),))
    conn.commit()

def get_exported_time(conn):
    cur = conn.cursor()
    cur.execute("SELECT value FROM meta WHERE key='exported_time'")
    row = cur.fetchone()
    return row[0] if row else '0'
 
def set_exported_time(conn, value):
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('exported_time', ?)", (str(value),))
    conn.commit()
    
def set_workers_status(conn, status: str):
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('workers_status', ?)", (str(status),))
    conn.commit()

def get_workers_status(conn) -> str:
    cur = conn.cursor()
    cur.execute("SELECT value FROM meta WHERE key='workers_status'")
    row = cur.fetchone()
    return row[0] if row else '0'

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
    """
    Update reactions for existing messages.

    reactions_by_msg_id items are (msg_id, reactions_obj). When reactions_obj is None / empty,
    reactions is set to NULL.
    """
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

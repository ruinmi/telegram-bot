import os
import sqlite3
import json
import re

script_dir = os.path.dirname(os.path.abspath(__file__))

def get_db_path(chat_id):
    data_dir = os.path.join(script_dir, 'data', chat_id)
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return os.path.join(data_dir, 'messages.db')

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
            display_height INTEGER,
            display_width INTEGER,
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
            display_height, display_width, og_info, reactions, msg_files, reply_to_msg_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    data = []
    for m in messages:
        og_info = json.dumps(m.get('og_info'), ensure_ascii=False) if m.get('og_info') else None
        reactions = json.dumps(m.get('reactions'), ensure_ascii=False) if m.get('reactions') else None
        msg_files = json.dumps(m.get('msg_files'), ensure_ascii=False) if m.get('msg_files') else None
        data.append((chat_id, m['msg_id'], m['date'], m['timestamp'],
                     m['msg_file_name'], m['user'], m['msg'],
                     m['display_height'], m['display_width'], og_info, reactions, msg_files, m['reply_to_msg_id']))
    conn.executemany(insert_sql, data)
    conn.commit()

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

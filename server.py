import os
import json
import logging
from db_utils import get_connection, get_db_path
import sqlite3
import time
from threading import Thread
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, render_template, Response, abort
from werkzeug.utils import safe_join

from main import handle

script_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_url_path='', static_folder=script_dir, template_folder=script_dir)

CHATS_FILE = os.path.join(script_dir, 'chats.json')

def load_chats():
    if os.path.exists(CHATS_FILE):
        try:
            with open(CHATS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f'Error reading {CHATS_FILE}: {e}')
    return []

def save_chats(chats):
    try:
        with open(CHATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(chats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f'Error writing {CHATS_FILE}: {e}')

def start_chat_worker(chat, interval=1800):
    chat_id = chat.get('id')
    remark = chat.get('remark')
    is_download = chat.get('download_files', True)
    is_all = chat.get('all_messages', True)
    is_raw = chat.get('raw_messages', True)

    def worker():
        while True:
            handle(chat_id, is_download, is_all, is_raw, remark)
            time.sleep(interval)

    Thread(target=worker, daemon=True).start()

def start_saved_chat_workers():
    for chat in load_chats():
        if chat.get('id'):
            start_chat_worker(chat)

# Start workers immediately when the server module is imported
start_saved_chat_workers()

USERNAME = os.environ.get('BOT_USERNAME', 'user')
PASSWORD = os.environ.get('BOT_PASSWORD')

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_auth(auth):
    return auth and auth.username == USERNAME and PASSWORD and auth.password == PASSWORD

def authenticate():
    return Response('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if PASSWORD:
            auth = request.authorization
            if not check_auth(auth):
                return authenticate()
        return f(*args, **kwargs)
    return decorated

@app.route('/')
@requires_auth
def index_page():
    return render_template('index.html')

@app.route('/resources/<path:filename>')
@requires_auth
def resources_files(filename):
    full_path = safe_join(script_dir, 'resources', filename)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(os.path.join(script_dir, 'resources'), filename)

@app.route('/fonts/<path:filename>')
@requires_auth
def fonts_files(filename):
    full_path = safe_join(script_dir, 'fonts', filename)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(os.path.join(script_dir, 'fonts'), filename)

@app.route('/downloads/<path:filename>')
@requires_auth
def downloads_files(filename):
    full_path = safe_join(script_dir, 'downloads', filename)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(os.path.join(script_dir, 'downloads'), filename)
def get_db(chat_id):
    db_path = get_db_path(chat_id)
    if not os.path.exists(db_path):
        return None
    conn = get_connection(chat_id, sqlite3.Row)
    return conn
@requires_auth
def chat_page(chat_id):
    return render_template('template.html', chat_id=chat_id)

@app.route('/chats')
@requires_auth
def list_chats():
    return jsonify({'chats': load_chats()})

@app.route('/add_chat', methods=['POST'])
@requires_auth
def add_chat():
    data = request.get_json(force=True)
    chat_id = str(data.get('chat_id', '')).strip()
    remark = data.get('remark')
    download_files = bool(data.get('download_files', True))
    all_messages = bool(data.get('all_messages', True))
    raw_messages = bool(data.get('raw_messages', True))
    if not chat_id:
        return jsonify({'error': 'chat_id required'}), 400

    chats = load_chats()
    existing = next((c for c in chats if c.get('id') == chat_id), None)
    chat_item = {
        'id': chat_id,
        'remark': remark,
        'download_files': download_files,
        'all_messages': all_messages,
        'raw_messages': raw_messages
    }
    if existing:
        existing.update(chat_item)
    else:
        chats.append(chat_item)
    save_chats(chats)

    start_chat_worker(chat_item)
    return jsonify({'message': 'chat export started'})

@app.route('/messages/<chat_id>')
@requires_auth
def get_messages(chat_id):
    conn = get_db(chat_id)
    if not conn:
        return jsonify({'total': 0, 'offset': 0, 'messages': []})

    offset = int(request.args.get('offset', 0))
    limit = int(request.args.get('limit', 20))

    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM messages WHERE chat_id=?', (chat_id,))
    total = cur.fetchone()[0]
    if offset < 0:
        offset = max(total + offset, 0)

    cur.execute('SELECT * FROM messages WHERE chat_id=? ORDER BY timestamp LIMIT ? OFFSET ?',
                (chat_id, limit, offset))
    rows = cur.fetchall()
    messages = []
    for row in rows:
        item = dict(row)
        if item.get('og_info'):
            try:
                item['og_info'] = json.loads(item['og_info'])
            except Exception:
                item['og_info'] = None
        if item.get('msg_files'):
            try:
                item['msg_files'] = json.loads(item['msg_files'])
            except Exception:
                item['msg_files'] = None
        messages.append(item)
    conn.close()
    return jsonify({'total': total, 'offset': offset, 'messages': messages})

@app.route('/search/<chat_id>')
@requires_auth
def search_messages(chat_id):
    query = request.args.get('q', '').strip().lower()
    conn = get_db(chat_id)
    if not conn:
        return jsonify({'total': 0, 'results': []})

    cur = conn.cursor()
    if not query:
        cur.execute('SELECT COUNT(*) FROM messages WHERE chat_id=?', (chat_id,))
        total = cur.fetchone()[0]
        conn.close()
        return jsonify({'total': total, 'results': []})

    keywords = query.split()

    # 动态构建 SQL 条件
    conditions = []
    params = []
    for kw in keywords:
        pattern = f"%{kw}%"
        conditions.append('(' +
                          ' OR '.join([
                              'LOWER(date) LIKE ?',
                              'LOWER(COALESCE(msg, "")) LIKE ?',
                              'LOWER(COALESCE(msg_file_name, "")) LIKE ?'
                          ]) +
                          ')')
        params.extend([pattern, pattern, pattern])

    where_clause = ' AND '.join(conditions)

    # 查询匹配项
    sql = f'''
        SELECT
            m.*,
            (
                SELECT COUNT(*) FROM messages m2
                WHERE m2.chat_id = m.chat_id AND m2.timestamp <= m.timestamp
            ) - 1 AS idx
        FROM messages m
        WHERE m.chat_id=? AND {where_clause}
        ORDER BY m.timestamp
    '''
    cur.execute(sql, (chat_id, *params))
    rows = cur.fetchall()
    
    # 查询总数
    sql_count = f'''
        SELECT COUNT(*) FROM messages
        WHERE chat_id=? AND {where_clause}
    '''
    cur.execute(sql_count, (chat_id, *params))
    total = cur.fetchone()[0]
    
    results = []
    for row in rows:
        item = dict(row)
        if item.get('og_info'):
            try:
                item['og_info'] = json.loads(item['og_info'])
            except Exception:
                item['og_info'] = None
        if 'idx' in item:
            item['index'] = item.pop('idx')
        results.append(item)
    conn.close()
    return jsonify({'total': total, 'results': results})

# 错误处理
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Server error'}), 500

if __name__ == '__main__':
    import platform

    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8000'))

    # 开发环境或兼容性运行
    system = platform.system()
    if system == 'Windows':
        from waitress import serve
        print(f"Running on http://{host}:{port} (Windows via waitress)")
        serve(app, host=host, port=port)
    else:
        # Linux 开发环境（非生产）
        print(f"Running on http://{host}:{port} (Linux dev mode)")
        app.run(host=host, port=port)

# main.py
import os
import json
import logging
import sqlite3
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, render_template, Response, abort
from werkzeug.utils import safe_join

script_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_url_path='', static_folder=script_dir, template_folder=script_dir)

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
    db_path = os.path.join(script_dir, 'data', chat_id, 'messages.db')
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/chat/<chat_id>')
@requires_auth
def chat_page(chat_id):
    return render_template('template.html', chat_id=chat_id)

@app.route('/chats')
@requires_auth
def list_chats():
    data_dir = os.path.join(script_dir, 'data')
    if not os.path.isdir(data_dir):
        return jsonify({'chats': []})
    chats = [
        name for name in os.listdir(data_dir)
        if os.path.isdir(os.path.join(data_dir, name))
    ]
    return jsonify({'chats': chats})

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
        messages.append(item)
    conn.close()
    return jsonify({'total': total, 'offset': offset, 'messages': messages})

@app.route('/search/<chat_id>')
@requires_auth
def search_messages(chat_id):
    query = request.args.get('q', '').lower()
    conn = get_db(chat_id)
    if not conn:
        return jsonify({'total': 0, 'results': []})

    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM messages WHERE chat_id=?', (chat_id,))
    total = cur.fetchone()[0]

    if not query:
        conn.close()
        return jsonify({'total': total, 'results': []})

    cur.execute('SELECT * FROM messages WHERE chat_id=? ORDER BY timestamp', (chat_id,))
    rows = cur.fetchall()
    results = []
    for idx, row in enumerate(rows):
        if (query in row['date'].lower() or
                (row['msg'] or '').lower().find(query) != -1 or
                row['msg_file_name'].lower().find(query) != -1):
            item = dict(row)
            if item.get('og_info'):
                try:
                    item['og_info'] = json.loads(item['og_info'])
                except Exception:
                    item['og_info'] = None
            item['index'] = idx
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

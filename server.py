import os
import json
import subprocess
import atexit
import shutil

from project_logger import get_logger
from db_utils import get_connection, get_db_path
import sqlite3
import time
from threading import Thread, Event
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, render_template, Response, abort
from werkzeug.utils import safe_join

from main import handle
from update_messages import redownload_chat_files

script_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_url_path='', static_folder=script_dir, template_folder=script_dir)

# 配置日志
logger = get_logger('server')
CHATS_FILE = os.path.join(script_dir, 'chats.json')
WORKERS_FLAG = os.path.join(script_dir, 'workers_started.flag')

_workers_started = False
_workers_lock_handle = None
_chat_worker_stop_events = {}

def workers_started():
    if _workers_started:
        return True

    if not os.path.exists(WORKERS_FLAG):
        return False

    try:
        with open(WORKERS_FLAG, 'a+b') as f:
            if _try_acquire_file_lock(f):
                _release_file_lock(f)
                return False
            return True
    except OSError:
        return False


def _try_acquire_file_lock(file_handle) -> bool:
    try:
        if os.name == 'nt':
            import msvcrt
            file_handle.seek(0)
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _release_file_lock(file_handle) -> None:
    try:
        if os.name == 'nt':
            import msvcrt
            file_handle.seek(0)
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _cleanup_stale_workers_flag() -> None:
    if not os.path.exists(WORKERS_FLAG):
        return

    try:
        with open(WORKERS_FLAG, 'a+b') as f:
            if not _try_acquire_file_lock(f):
                return
    except OSError:
        return

    try:
        os.remove(WORKERS_FLAG)
    except OSError:
        pass


_cleanup_stale_workers_flag()

def mark_workers_started():
    global _workers_started
    global _workers_lock_handle

    if _workers_started:
        return True

    try:
        f = open(WORKERS_FLAG, 'a+b')
    except OSError as e:
        logger.error(f'Error opening {WORKERS_FLAG}: {e}')
        return False

    if not _try_acquire_file_lock(f):
        f.close()
        return False

    _workers_lock_handle = f
    _workers_started = True

    try:
        payload = json.dumps(
            {'pid': os.getpid(), 'started_at': int(time.time())},
            ensure_ascii=False,
        ).encode('utf-8')
        f.seek(0)
        f.truncate()
        f.write(payload)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    except Exception as e:
        logger.error(f'Error writing {WORKERS_FLAG}: {e}')

    return True


def _release_workers_lock() -> None:
    global _workers_lock_handle
    if _workers_lock_handle is None:
        return

    try:
        _release_file_lock(_workers_lock_handle)
    finally:
        try:
            _workers_lock_handle.close()
        except OSError:
            pass
        _workers_lock_handle = None

    try:
        os.remove(WORKERS_FLAG)
    except OSError:
        pass


atexit.register(_release_workers_lock)

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
    download_images_only = chat.get('download_images_only', False)
    is_all = chat.get('all_messages', True)
    is_raw = chat.get('raw_messages', True)
    
    if not workers_started():
        logger.info(f'Worker {remark} will not start')
        return

    if chat_id in _chat_worker_stop_events and not _chat_worker_stop_events[chat_id].is_set():
        logger.info(f'Worker {remark} already running')
        return

    stop_event = Event()
    _chat_worker_stop_events[chat_id] = stop_event
    
    def worker():
        while not stop_event.is_set():
            handle(chat_id, is_download, is_all, is_raw, remark, download_images_only=bool(download_images_only))
            stop_event.wait(interval)

    logger.info(f'Worker {remark} will start')
    Thread(target=worker, daemon=True).start()

def start_saved_chat_workers():
    if workers_started():
        return False
    if not mark_workers_started():
        return False
    for chat in load_chats():
        if chat.get('id'):
            start_chat_worker(chat)
    return True


def find_chat(info: str) -> tuple[str, str] | None:
    """
    根据 id（纯数字字符串）或 username（字符串），返回 (id, visibleName)
    """
    try:
        # 判断 info 是否为纯数字
        if info.isdigit():
            # 过滤器用 expr 引擎
            filter_str = f"ID == '{info}'"
        else:
            filter_str = f"Username == '{info}'"

        # 调用 tdl 命令
        cmd = ["tdl", "chat", "ls", "-o", "json", "-f", filter_str]
        output = subprocess.check_output(cmd, encoding="utf-8")
        chats = json.loads(output)

        if not chats:
            return None

        chat = chats[0]
        return str(chat["id"]), chat.get("visible_name", "")

    except subprocess.CalledProcessError as e:
        logger.error(f"命令执行错误: {e}")
        return None
    except Exception as e:
        logger.error(f"解析错误: {e}")
        return None

# Workers are started manually via API

def authenticate():
    return Response('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})

@app.route('/')
def index_page():
    return render_template('index.html')


@app.route('/workers_status')
def workers_status_route():
    return jsonify({'started': workers_started()})


@app.route('/start_workers', methods=['POST'])
def start_workers_route():
    started = start_saved_chat_workers()
    return jsonify({'started': started})

@app.route('/resources/<path:filename>')
def resources_files(filename):
    full_path = safe_join(script_dir, 'resources', filename)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(os.path.join(script_dir, 'resources'), filename)

@app.route('/fonts/<path:filename>')
def fonts_files(filename):
    full_path = safe_join(script_dir, 'fonts', filename)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(os.path.join(script_dir, 'fonts'), filename)

@app.route('/downloads/<path:filename>')
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

def row_to_message(row):
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
    if item.get('reactions'):
        try:
            item['reactions'] = json.loads(item['reactions'])
        except Exception:
            item['reactions'] = None
    return item


def _parse_reactions_blob(blob):
    if not blob:
        return None
    if isinstance(blob, dict):
        return blob
    try:
        return json.loads(blob)
    except Exception:
        return None


def _iter_reaction_emoticon_counts(reactions_obj):
    if not isinstance(reactions_obj, dict):
        return
    results = reactions_obj.get('Results') or []
    if not isinstance(results, list):
        return

    for entry in results:
        if not isinstance(entry, dict):
            continue
        reaction = entry.get('Reaction') or {}
        if not isinstance(reaction, dict):
            continue
        emoticon = reaction.get('Emoticon')
        if not emoticon:
            continue

        count = entry.get('Count', 0)
        try:
            count = int(count)
        except Exception:
            count = 0
        yield emoticon, max(count, 0)


def _get_reaction_count_for_emoticon(reactions_obj, target_emoticon: str) -> int:
    if not target_emoticon:
        return 0
    for emoticon, count in _iter_reaction_emoticon_counts(reactions_obj):
        if emoticon == target_emoticon:
            return count
    return 0

@app.route('/chat/<chat_id>')
def chat_page(chat_id):
    return render_template('template.html', chat_id=chat_id)

@app.route('/chats')
def list_chats():
    return jsonify({'chats': load_chats()})

@app.route('/add_chat', methods=['POST'])
def add_chat():
    data = request.get_json(force=True)
    chat_id = str(data.get('chat_id', '')).strip()
    chat_id, remark = find_chat(chat_id)
    if data.get('remark', ''):
        remark = data.get('remark')
    download_files = bool(data.get('download_files', True))
    download_images_only = bool(data.get('download_images_only', False))
    if download_images_only:
        download_files = True
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
        'download_images_only': download_images_only,
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


@app.route('/redownload_chat', methods=['POST'])
def redownload_chat():
    data = request.get_json(force=True)
    chat_id = str(data.get('chat_id', '')).strip()
    if not chat_id:
        return jsonify({'error': 'chat_id required'}), 400

    chats = load_chats()
    chat = next((c for c in chats if str(c.get('id')) == chat_id), None)
    remark = chat.get('remark') if chat else None

    download_images_only = bool(data.get('download_images_only', False))
    if chat and chat.get('download_images_only'):
        download_images_only = True

    def worker():
        logger.info(f'Redownload worker start: chat_id={chat_id} remark={remark} images_only={download_images_only}')
        try:
            ok = redownload_chat_files(chat_id, download_images_only=download_images_only, remark=remark)
            logger.info(f'Redownload worker finished: chat_id={chat_id} ok={ok}')
        except Exception as e:
            logger.exception(f'Redownload worker crashed: chat_id={chat_id} error={e}')

    Thread(target=worker, daemon=True).start()
    return jsonify({'message': 'redownload started'})


def _safe_remove_tree(base_dir: str, chat_id: str) -> bool:
    if not chat_id:
        return False

    base_real = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base_dir, chat_id))
    if not (target == base_real or target.startswith(base_real + os.sep)):
        return False

    if not os.path.exists(target):
        return True

    try:
        shutil.rmtree(target, ignore_errors=True)
        return True
    except Exception:
        return False


@app.route('/delete_chat', methods=['POST'])
def delete_chat():
    data = request.get_json(force=True)
    chat_id = str(data.get('chat_id', '')).strip()
    if not chat_id:
        return jsonify({'error': 'chat_id required'}), 400

    stop_event = _chat_worker_stop_events.get(chat_id)
    if stop_event:
        stop_event.set()

    chats = load_chats()
    before = len(chats)
    chats = [c for c in chats if str(c.get('id')) != chat_id]
    save_chats(chats)

    data_dir = os.path.join(script_dir, 'data')
    downloads_dir = os.path.join(script_dir, 'downloads')
    removed_data = _safe_remove_tree(data_dir, chat_id)
    removed_downloads = _safe_remove_tree(downloads_dir, chat_id)

    deleted = len(chats) != before
    return jsonify({
        'deleted': deleted,
        'removed_data': removed_data,
        'removed_downloads': removed_downloads,
    })

@app.route('/messages/<chat_id>')
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
        item = row_to_message(row)
        if item.get('reply_to_msg_id'):
            cur2 = conn.cursor()
            cur2.execute('SELECT * FROM messages WHERE chat_id=? AND msg_id=?',
                         (chat_id, item['reply_to_msg_id']))
            r = cur2.fetchone()
            if r:
                item['reply_message'] = row_to_message(r)
        messages.append(item)
    conn.close()
    return jsonify({'total': total, 'offset': offset, 'messages': messages})

@app.route('/messages/<chat_id>/<msg_id>')
def get_message(chat_id, msg_id):
    conn = get_db(chat_id)
    if not conn:
        return jsonify({'error': 'chat_id required'}), 400
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM messages WHERE chat_id=? AND msg_id=?',
                (chat_id, msg_id))
    total = cur.fetchone()[0]
    if total < 1:
        return jsonify({'total': 0, 'offset': 0, 'messages': []})
    
    cur.execute('SELECT * FROM messages WHERE chat_id=? AND msg_id=?', (chat_id, msg_id))
    rows = cur.fetchall()
    message = row_to_message(rows[0])
    if message.get('reply_to_msg_id'):
        cur.execute('SELECT * FROM messages WHERE chat_id=? AND msg_id=?',
                    (chat_id, message['reply_to_msg_id']))
        r = cur.fetchone()
        if r:
            message['reply_message'] = row_to_message(r)
    conn.close()
    return jsonify(message)


@app.route('/reactions_emoticons/<chat_id>')
def get_reactions_emoticons(chat_id):
    conn = get_db(chat_id)
    if not conn:
        return jsonify({'emoticons': []})

    totals = {}
    cur = conn.cursor()
    cur.execute('SELECT reactions FROM messages WHERE chat_id=? AND reactions IS NOT NULL', (chat_id,))
    for row in cur.fetchall():
        reactions_obj = _parse_reactions_blob(row['reactions'])
        for emoticon, count in _iter_reaction_emoticon_counts(reactions_obj):
            totals[emoticon] = totals.get(emoticon, 0) + count

    conn.close()
    emoticons = [
        {'emoticon': e, 'count': totals[e]}
        for e in sorted(totals.keys(), key=lambda k: (-totals[k], k))
    ]
    return jsonify({'emoticons': emoticons})


@app.route('/messages_by_reaction/<chat_id>')
def get_messages_by_reaction(chat_id):
    emoticon = request.args.get('emoticon', '').strip()
    if not emoticon:
        return jsonify({'error': 'emoticon required'}), 400

    conn = get_db(chat_id)
    if not conn:
        return jsonify({'total': 0, 'offset': 0, 'messages': []})

    offset = int(request.args.get('offset', 0))
    limit = int(request.args.get('limit', 20))
    offset = max(offset, 0)
    limit = max(1, min(limit, 100))

    cur = conn.cursor()
    cur.execute(
        'SELECT msg_id, timestamp, reactions FROM messages WHERE chat_id=? AND reactions IS NOT NULL',
        (chat_id,),
    )

    scored = []
    for row in cur.fetchall():
        reactions_obj = _parse_reactions_blob(row['reactions'])
        count = _get_reaction_count_for_emoticon(reactions_obj, emoticon)
        if count > 0:
            scored.append((count, int(row['timestamp'] or 0), int(row['msg_id'])))

    scored.sort(key=lambda t: (-t[0], -t[1], -t[2]))
    total = len(scored)

    page = scored[offset:offset + limit]
    msg_ids = [t[2] for t in page]
    counts_by_msg_id = {t[2]: t[0] for t in page}

    messages = []
    if msg_ids:
        placeholders = ','.join(['?'] * len(msg_ids))
        cur.execute(
            f'SELECT * FROM messages WHERE chat_id=? AND msg_id IN ({placeholders})',
            (chat_id, *msg_ids),
        )
        rows = cur.fetchall()
        rows_by_id = {int(r['msg_id']): r for r in rows}

        for mid in msg_ids:
            row = rows_by_id.get(int(mid))
            if not row:
                continue
            item = row_to_message(row)
            item['reaction_sort_emoticon'] = emoticon
            item['reaction_sort_count'] = counts_by_msg_id.get(int(mid), 0)

            if item.get('reply_to_msg_id'):
                cur2 = conn.cursor()
                cur2.execute(
                    'SELECT * FROM messages WHERE chat_id=? AND msg_id=?',
                    (chat_id, item['reply_to_msg_id']),
                )
                r = cur2.fetchone()
                if r:
                    item['reply_message'] = row_to_message(r)

            messages.append(item)

    conn.close()
    return jsonify({'total': total, 'offset': offset, 'messages': messages})
                
@app.route('/search/<chat_id>')
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
        item = row_to_message(row)
        if 'idx' in item:
            item['index'] = item.pop('idx')
        if item.get('reply_to_msg_id'):
            cur2 = conn.cursor()
            cur2.execute('SELECT * FROM messages WHERE chat_id=? AND msg_id=?',
                         (chat_id, item['reply_to_msg_id']))
            r = cur2.fetchone()
            if r:
                item['reply_message'] = row_to_message(r)
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

@app.route('/execute_sql', methods=['POST'])
def execute_sql():
    data = request.get_json(force=True)
    chat_id = data.get("chat_id", "").strip()
    sql_str = data.get("sql_str", "").strip()

    if not chat_id or not sql_str:
        return jsonify({"error": "chat_id 和 sql_str 必填"}), 400

    # 安全限制，只允许 select
    # if not sql_str.lower().startswith("select"):
    #     return jsonify({"error": "只允许执行 SELECT 查询"}), 403

    conn = get_db(chat_id)
    if not conn:
        return jsonify({"error": f"数据库不存在: {chat_id}"}), 404

    try:
        cur = conn.cursor()
        # 判断是查询还是修改
        is_select = sql_str.strip().lower().startswith("select")

        cur.execute(sql_str)
        if is_select:
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            results = [dict(zip(columns, row)) for row in rows]
            conn.commit()
            return jsonify({"results": results})
        else:
            # 如果是修改、插入、或表结构变更，返回影响行数
            affected = cur.rowcount
            conn.commit()
            return jsonify({"message": "SQL 执行成功", "affected_rows": affected})
    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


if __name__ == '__main__':
    import platform

    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8000'))

    # 开发环境或兼容性运行
    system = platform.system()
    if system == 'Windows':
        from waitress import serve
        logger.info(f"Running on http://{host}:{port} (Windows via waitress)")
        serve(app, host=host, port=port)
    else:
        # Linux 开发环境（非生产）
        logger.info(f"Running on http://{host}:{port} (Linux dev mode)")
        app.run(host=host, port=port)

import os
import json
import subprocess
import atexit
import shutil
import random
import re
import uuid

from .project_logger import get_logger
from .db_utils import get_connection, get_db_path
from .paths import BASE_DIR, DOWNLOADS_DIR, STATIC_DIR, TEMPLATES_DIR, ensure_runtime_dirs
import sqlite3
import time
from threading import Thread, Event, Lock
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, render_template, Response, abort
from werkzeug.utils import safe_join

from .archiver import handle
from .update_messages import redownload_chat_files
from bdpan import BaiduPanClient, BaiduPanConfig

ensure_runtime_dirs()
app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR),
)

# 配置日志
logger = get_logger('server')
CHATS_FILE = str(BASE_DIR / 'chats.json')
WORKERS_FLAG = str(BASE_DIR / 'workers_started.flag')

_workers_started = False
_workers_lock_handle = None
_chat_worker_stop_events = {}

_cleanup_baidu_jobs = {}
_cleanup_baidu_jobs_lock = Lock()
_cleanup_baidu_global_lock = Lock()

_CLEANUP_BAIDU_MIN_INTERVAL_SECONDS = 1.6
_CLEANUP_BAIDU_JITTER_SECONDS = 0.4
_CLEANUP_BAIDU_PROGRESS_FLUSH_EVERY = 25

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

@app.route('/downloads/<path:filename>')
def downloads_files(filename):
    full_path = safe_join(str(DOWNLOADS_DIR), filename)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(str(DOWNLOADS_DIR), filename)


# Backward-compatible static routes (old URLs before static/ + templates/ layout).
@app.route('/chat.css')
def legacy_chat_css():
    return send_from_directory(str(STATIC_DIR), 'chat.css')


@app.route('/chat.js')
def legacy_chat_js():
    return send_from_directory(str(STATIC_DIR), 'chat.js')


@app.route('/resources/<path:filename>')
def legacy_resources_files(filename):
    full_path = safe_join(str(STATIC_DIR / 'resources'), filename)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(str(STATIC_DIR / 'resources'), filename)


@app.route('/fonts/<path:filename>')
def legacy_fonts_files(filename):
    full_path = safe_join(str(STATIC_DIR / 'fonts'), filename)
    if not os.path.isfile(full_path):
        abort(404)
    return send_from_directory(str(STATIC_DIR / 'fonts'), filename)
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


def _cleanup_baidu_extract_links(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r'(https?://\S+)', text)


def _cleanup_baidu_job_snapshot(chat_id: str) -> dict:
    with _cleanup_baidu_jobs_lock:
        job = _cleanup_baidu_jobs.get(chat_id)
        return dict(job) if isinstance(job, dict) else {}


def _cleanup_stale_baidu_links_worker(chat_id: str, remark: str | None, job_id: str, job: dict) -> None:
    logger.info(f'Cleanup stale baidu links worker start: chat_id={chat_id} remark={remark} job_id={job_id}')

    db_path = get_db_path(chat_id)
    if not os.path.exists(db_path):
        with _cleanup_baidu_jobs_lock:
            job['status'] = 'error'
            job['finished_at'] = int(time.time())
            job['last_error'] = 'database not found'
        logger.error(f'Cleanup worker aborted (db missing): chat_id={chat_id} path={db_path}')
        return

    bdpan = BaiduPanClient(config=BaiduPanConfig(cookie_file='auth/cookies.txt'))
    stale_cache: dict[str, bool] = {}
    last_call_monotonic = 0.0

    scanned_messages = 0
    candidate_messages = 0
    deleted_messages = 0
    checked_links = 0
    errors = 0

    def is_link_stale_cached(link: str) -> bool | None:
        nonlocal last_call_monotonic, checked_links, errors
        if link in stale_cache:
            return stale_cache[link]

        now = time.monotonic()
        wait_seconds = _CLEANUP_BAIDU_MIN_INTERVAL_SECONDS - (now - last_call_monotonic)
        if wait_seconds > 0:
            time.sleep(wait_seconds + random.uniform(0, _CLEANUP_BAIDU_JITTER_SECONDS))
        last_call_monotonic = time.monotonic()

        try:
            checked_links += 1
            stale = bool(bdpan.is_link_stale(link))
            stale_cache[link] = stale
            return stale
        except Exception as e:
            errors += 1
            with _cleanup_baidu_jobs_lock:
                job['errors'] = errors
                job['last_error'] = str(e)
            logger.exception(f'Cleanup worker link check failed: chat_id={chat_id} link={link} error={e}')
            return None

    try:
        conn = get_connection(chat_id)
        cur = conn.cursor()
        cur.execute(
            '''
            SELECT msg_id, msg
            FROM messages
            WHERE chat_id=? AND msg IS NOT NULL AND msg LIKE '%baidu.com%'
            ORDER BY timestamp
            ''',
            (chat_id,),
        )
        rows = cur.fetchall()

        delete_sql = 'DELETE FROM messages WHERE chat_id=? AND msg_id=?'
        deletes_since_commit = 0
        cur_delete = conn.cursor()

        for msg_id, msg in rows:
            scanned_messages += 1
            msg_text = msg or ''
            links = _cleanup_baidu_extract_links(msg_text)
            if not links:
                continue

            should_keep = False
            has_share_link = False
            for link in links:
                try:
                    if bdpan.is_share_link(link):
                        has_share_link = True
                        stale = is_link_stale_cached(link)
                        if stale is None:
                            should_keep = True
                            break
                        if not stale:
                            should_keep = True
                            break
                    else:
                        should_keep = True
                        break
                except Exception as e:
                    errors += 1
                    should_keep = True
                    with _cleanup_baidu_jobs_lock:
                        job['errors'] = errors
                        job['last_error'] = str(e)
                    logger.exception(f'Cleanup worker parse failed: chat_id={chat_id} msg_id={msg_id} error={e}')
                    break

            if not has_share_link:
                continue

            candidate_messages += 1
            if should_keep:
                continue

            try:
                cur_delete.execute(delete_sql, (chat_id, int(msg_id)))
                deleted_messages += 1
                deletes_since_commit += 1
                if deletes_since_commit >= 50:
                    conn.commit()
                    deletes_since_commit = 0
            except Exception as e:
                errors += 1
                with _cleanup_baidu_jobs_lock:
                    job['errors'] = errors
                    job['last_error'] = str(e)
                logger.exception(f'Cleanup worker delete failed: chat_id={chat_id} msg_id={msg_id} error={e}')

            if scanned_messages % _CLEANUP_BAIDU_PROGRESS_FLUSH_EVERY == 0:
                with _cleanup_baidu_jobs_lock:
                    job['scanned_messages'] = scanned_messages
                    job['candidate_messages'] = candidate_messages
                    job['deleted_messages'] = deleted_messages
                    job['checked_links'] = checked_links
                    job['cached_links'] = len(stale_cache)
                    job['errors'] = errors

        conn.commit()
        conn.close()

        with _cleanup_baidu_jobs_lock:
            job['status'] = 'done'
            job['finished_at'] = int(time.time())
            job['scanned_messages'] = scanned_messages
            job['candidate_messages'] = candidate_messages
            job['deleted_messages'] = deleted_messages
            job['checked_links'] = checked_links
            job['cached_links'] = len(stale_cache)
            job['errors'] = errors

        logger.info(
            'Cleanup stale baidu links worker finished: '
            f'chat_id={chat_id} job_id={job_id} scanned={scanned_messages} '
            f'candidates={candidate_messages} deleted={deleted_messages} checked_links={checked_links} '
            f'cache={len(stale_cache)} errors={errors}'
        )
    except Exception as e:
        logger.exception(f'Cleanup worker crashed: chat_id={chat_id} job_id={job_id} error={e}')
        with _cleanup_baidu_jobs_lock:
            job['status'] = 'error'
            job['finished_at'] = int(time.time())
            job['last_error'] = str(e)
            job['scanned_messages'] = scanned_messages
            job['candidate_messages'] = candidate_messages
            job['deleted_messages'] = deleted_messages
            job['checked_links'] = checked_links
            job['cached_links'] = len(stale_cache)
            job['errors'] = errors + 1


@app.route('/cleanup_stale_baidu_links', methods=['POST'])
def cleanup_stale_baidu_links():
    data = request.get_json(force=True)
    chat_id = str(data.get('chat_id', '')).strip()
    if not chat_id:
        return jsonify({'error': 'chat_id required'}), 400

    existing = _cleanup_baidu_job_snapshot(chat_id)
    if existing and existing.get('status') == 'running':
        return jsonify(existing), 409

    if not _cleanup_baidu_global_lock.acquire(blocking=False):
        return jsonify({'error': '已有清理任务正在运行，请稍后再试。'}), 409

    chats = load_chats()
    chat = next((c for c in chats if str(c.get('id')) == chat_id), None)
    remark = chat.get('remark') if chat else None

    job_id = f'{int(time.time())}_{uuid.uuid4().hex[:8]}'
    job = {
        'chat_id': chat_id,
        'job_id': job_id,
        'status': 'running',
        'started_at': int(time.time()),
        'finished_at': None,
        'scanned_messages': 0,
        'candidate_messages': 0,
        'deleted_messages': 0,
        'checked_links': 0,
        'cached_links': 0,
        'errors': 0,
        'last_error': None,
        'min_interval_seconds': _CLEANUP_BAIDU_MIN_INTERVAL_SECONDS,
    }
    with _cleanup_baidu_jobs_lock:
        _cleanup_baidu_jobs[chat_id] = job

    def worker():
        try:
            _cleanup_stale_baidu_links_worker(chat_id, remark, job_id, job)
        finally:
            try:
                _cleanup_baidu_global_lock.release()
            except RuntimeError:
                pass

    Thread(target=worker, daemon=True).start()
    return jsonify(_cleanup_baidu_job_snapshot(chat_id))


@app.route('/cleanup_stale_baidu_links_status/<chat_id>')
def cleanup_stale_baidu_links_status(chat_id: str):
    chat_id = str(chat_id or '').strip()
    if not chat_id:
        return jsonify({'error': 'chat_id required'}), 400

    job = _cleanup_baidu_job_snapshot(chat_id)
    if not job:
        return jsonify({'chat_id': chat_id, 'status': 'idle'})
    return jsonify(job)


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


def main() -> None:
    import platform

    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8000'))

    system = platform.system()
    if system == 'Windows':
        from waitress import serve
        logger.info(f"Running on http://{host}:{port} (Windows via waitress)")
        serve(app, host=host, port=port)
    else:
        logger.info(f"Running on http://{host}:{port} (Linux dev mode)")
        app.run(host=host, port=port)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from threading import Event, Lock, Thread

from bdpan import BaiduPanClient, BaiduPanConfig
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .archiver import handle
from .db_utils import get_connection, get_db_path
from .paths import BASE_DIR, DOWNLOADS_DIR, STATIC_DIR, TEMPLATES_DIR, ensure_runtime_dirs
from .project_logger import get_logger
from .update_messages import redownload_chat_files

ensure_runtime_dirs()

logger = get_logger("server")
app = FastAPI()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

CHATS_FILE = str(BASE_DIR / "chats.json")

_workers_started = False
_workers_start_lock = Lock()
_chat_worker_stop_events: dict[str, Event] = {}

_cleanup_baidu_jobs: dict[str, dict] = {}
_cleanup_baidu_jobs_lock = Lock()
_cleanup_baidu_global_lock = Lock()

_CLEANUP_BAIDU_MIN_INTERVAL_SECONDS = 1.6
_CLEANUP_BAIDU_JITTER_SECONDS = 0.4
_CLEANUP_BAIDU_PROGRESS_FLUSH_EVERY = 25


class AddChatRequest(BaseModel):
    chat_id: str
    remark: str | None = None
    download_files: bool = True
    download_images_only: bool = False
    all_messages: bool = True
    raw_messages: bool = True


class ChatIdRequest(BaseModel):
    chat_id: str


class RedownloadChatRequest(BaseModel):
    chat_id: str
    download_images_only: bool = False


class ExecuteSqlRequest(BaseModel):
    chat_id: str
    sql_str: str


def _json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


def workers_started() -> bool:
    return bool(_workers_started)


def load_chats() -> list[dict]:
    if os.path.exists(CHATS_FILE):
        try:
            with open(CHATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"Error reading {CHATS_FILE}: {e}")
    return []


def save_chats(chats: list[dict]) -> None:
    try:
        with open(CHATS_FILE, "w", encoding="utf-8") as f:
            json.dump(chats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error writing {CHATS_FILE}: {e}")


def start_chat_worker(chat: dict, interval: int = 1800) -> None:
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id:
        return

    remark = chat.get("remark")
    is_download = bool(chat.get("download_files", True))
    download_images_only = bool(chat.get("download_images_only", False))
    is_all = bool(chat.get("all_messages", True))
    is_raw = bool(chat.get("raw_messages", True))

    if not workers_started():
        logger.info(f"Worker {remark} will not start (workers not started)")
        return

    existing = _chat_worker_stop_events.get(chat_id)
    if existing and not existing.is_set():
        logger.info(f"Worker {remark} already running")
        return

    stop_event = Event()
    _chat_worker_stop_events[chat_id] = stop_event

    def worker():
        while not stop_event.is_set():
            handle(
                chat_id,
                is_download=is_download,
                is_all=is_all,
                is_raw=is_raw,
                remark=remark,
                download_images_only=download_images_only,
            )
            stop_event.wait(interval)

    logger.info(f"Worker {remark} will start")
    Thread(target=worker, daemon=True).start()


def start_saved_chat_workers() -> bool:
    global _workers_started
    with _workers_start_lock:
        if _workers_started:
            return False
        _workers_started = True
        for chat in load_chats():
            if chat.get("id"):
                start_chat_worker(chat)
        return True


def find_chat(info: str) -> tuple[str, str] | None:
    """
    根据 id（纯数字字符串）或 username（字符串），返回 (id, visibleName)
    """
    info = str(info or "").strip()
    if not info:
        return None

    try:
        if info.isdigit():
            filter_str = f"ID == '{info}'"
        else:
            filter_str = f"Username == '{info}'"

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


def _safe_join(base_dir: Path, relative_path: str) -> Path | None:
    if not relative_path:
        return None
    rel = Path(relative_path)
    if rel.is_absolute() or rel.drive:
        return None
    base_resolved = base_dir.resolve()
    target = (base_dir / rel).resolve()
    if not target.is_relative_to(base_resolved):
        return None
    return target


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


def get_db(chat_id: str):
    db_path = get_db_path(chat_id)
    if not os.path.exists(db_path):
        return None
    return get_connection(chat_id, sqlite3.Row)


def row_to_message(row):
    item = dict(row)
    if item.get("og_info"):
        try:
            item["og_info"] = json.loads(item["og_info"])
        except Exception:
            item["og_info"] = None
    if item.get("msg_files"):
        try:
            item["msg_files"] = json.loads(item["msg_files"])
        except Exception:
            item["msg_files"] = None
    if item.get("reactions"):
        try:
            item["reactions"] = json.loads(item["reactions"])
        except Exception:
            item["reactions"] = None
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
    results = reactions_obj.get("Results") or []
    if not isinstance(results, list):
        return

    for entry in results:
        if not isinstance(entry, dict):
            continue
        reaction = entry.get("Reaction") or {}
        if not isinstance(reaction, dict):
            continue
        emoticon = reaction.get("Emoticon")
        if not emoticon:
            continue

        count = entry.get("Count", 0)
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


def _cleanup_baidu_extract_links(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"(https?://\S+)", text)


def _cleanup_baidu_job_snapshot(chat_id: str) -> dict:
    with _cleanup_baidu_jobs_lock:
        job = _cleanup_baidu_jobs.get(chat_id)
        return dict(job) if isinstance(job, dict) else {}


def _cleanup_stale_baidu_links_worker(chat_id: str, remark: str | None, job_id: str, job: dict) -> None:
    logger.info(f"Cleanup stale baidu links worker start: chat_id={chat_id} remark={remark} job_id={job_id}")

    db_path = get_db_path(chat_id)
    if not os.path.exists(db_path):
        with _cleanup_baidu_jobs_lock:
            job["status"] = "error"
            job["finished_at"] = int(time.time())
            job["last_error"] = "database not found"
        logger.error(f"Cleanup worker aborted (db missing): chat_id={chat_id} path={db_path}")
        return

    bdpan = BaiduPanClient(config=BaiduPanConfig(cookie_file="auth/cookies.txt"))
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
                job["errors"] = errors
                job["last_error"] = str(e)
            logger.exception(f"Cleanup worker link check failed: chat_id={chat_id} link={link} error={e}")
            return None

    try:
        conn = get_connection(chat_id)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT msg_id, msg
            FROM messages
            WHERE chat_id=? AND msg IS NOT NULL AND msg LIKE '%baidu.com%'
            ORDER BY timestamp
            """,
            (chat_id,),
        )
        rows = cur.fetchall()

        delete_sql = "DELETE FROM messages WHERE chat_id=? AND msg_id=?"
        deletes_since_commit = 0
        cur_delete = conn.cursor()

        logger.info(f"Cleanup worker started: chat_id={chat_id} total_messages={len(rows)}")
        for msg_id, msg in rows:
            scanned_messages += 1
            msg_text = msg or ""
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
                        job["errors"] = errors
                        job["last_error"] = str(e)
                    logger.exception(f"Cleanup worker parse failed: chat_id={chat_id} msg_id={msg_id} error={e}")
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
                    job["errors"] = errors
                    job["last_error"] = str(e)
                logger.exception(f"Cleanup worker delete failed: chat_id={chat_id} msg_id={msg_id} error={e}")

            if scanned_messages % _CLEANUP_BAIDU_PROGRESS_FLUSH_EVERY == 0:
                with _cleanup_baidu_jobs_lock:
                    job["scanned_messages"] = scanned_messages
                    job["candidate_messages"] = candidate_messages
                    job["deleted_messages"] = deleted_messages
                    job["checked_links"] = checked_links
                    job["cached_links"] = len(stale_cache)
                    job["errors"] = errors

        conn.commit()
        conn.close()

        with _cleanup_baidu_jobs_lock:
            job["status"] = "done"
            job["finished_at"] = int(time.time())
            job["scanned_messages"] = scanned_messages
            job["candidate_messages"] = candidate_messages
            job["deleted_messages"] = deleted_messages
            job["checked_links"] = checked_links
            job["cached_links"] = len(stale_cache)
            job["errors"] = errors

        logger.info(
            "Cleanup stale baidu links worker finished: "
            f"chat_id={chat_id} job_id={job_id} scanned={scanned_messages} "
            f"candidates={candidate_messages} deleted={deleted_messages} checked_links={checked_links} "
            f"cache={len(stale_cache)} errors={errors}"
        )
    except Exception as e:
        logger.exception(f"Cleanup worker crashed: chat_id={chat_id} job_id={job_id} error={e}")
        with _cleanup_baidu_jobs_lock:
            job["status"] = "error"
            job["finished_at"] = int(time.time())
            job["last_error"] = str(e)
            job["scanned_messages"] = scanned_messages
            job["candidate_messages"] = candidate_messages
            job["deleted_messages"] = deleted_messages
            job["checked_links"] = checked_links
            job["cached_links"] = len(stale_cache)
            job["errors"] = errors + 1


@app.get("/")
def index_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/chat/{chat_id}")
def chat_page(chat_id: str, request: Request):
    return templates.TemplateResponse("template.html", {"request": request, "chat_id": chat_id})


@app.get("/workers_status")
def workers_status_route():
    return {"started": workers_started()}


@app.post("/start_workers")
def start_workers_route():
    started = start_saved_chat_workers()
    return {"started": started}


@app.get("/downloads/{filename:path}")
def downloads_files(filename: str):
    target = _safe_join(Path(DOWNLOADS_DIR), filename)
    if target is None or not target.is_file():
        return _json_error(404, "Not found")
    return FileResponse(str(target))


@app.get("/chat.css")
def legacy_chat_css():
    target = Path(STATIC_DIR) / "chat.css"
    if not target.is_file():
        return _json_error(404, "Not found")
    return FileResponse(str(target))


@app.get("/chat.js")
def legacy_chat_js():
    target = Path(STATIC_DIR) / "chat.js"
    if not target.is_file():
        return _json_error(404, "Not found")
    return FileResponse(str(target))


@app.get("/resources/{filename:path}")
def legacy_resources_files(filename: str):
    target = _safe_join(Path(STATIC_DIR) / "resources", filename)
    if target is None or not target.is_file():
        return _json_error(404, "Not found")
    return FileResponse(str(target))


@app.get("/fonts/{filename:path}")
def legacy_fonts_files(filename: str):
    target = _safe_join(Path(STATIC_DIR) / "fonts", filename)
    if target is None or not target.is_file():
        return _json_error(404, "Not found")
    return FileResponse(str(target))


@app.get("/chats")
def list_chats():
    return {"chats": load_chats()}


@app.post("/add_chat")
def add_chat(payload: AddChatRequest):
    input_chat_id = str(payload.chat_id or "").strip()
    result = find_chat(input_chat_id)
    if result is None:
        return _json_error(400, "Invalid chat_id")

    chat_id, remark = result
    if payload.remark:
        remark = payload.remark

    download_images_only = bool(payload.download_images_only)
    download_files = bool(payload.download_files)
    if download_images_only:
        download_files = True

    chat_item = {
        "id": chat_id,
        "remark": remark,
        "download_files": download_files,
        "download_images_only": download_images_only,
        "all_messages": bool(payload.all_messages),
        "raw_messages": bool(payload.raw_messages),
    }

    chats = load_chats()
    existing = next((c for c in chats if c.get("id") == chat_id), None)
    if existing:
        existing.update(chat_item)
    else:
        chats.append(chat_item)
    save_chats(chats)

    start_chat_worker(chat_item)
    return {"message": "chat export started"}


@app.post("/redownload_chat")
def redownload_chat(payload: RedownloadChatRequest):
    chat_id = str(payload.chat_id or "").strip()
    if not chat_id:
        return _json_error(400, "chat_id required")

    chats = load_chats()
    chat = next((c for c in chats if str(c.get("id")) == chat_id), None)
    remark = chat.get("remark") if chat else None

    download_images_only = bool(payload.download_images_only)
    if chat and chat.get("download_images_only"):
        download_images_only = True

    def worker():
        logger.info(f"Redownload worker start: chat_id={chat_id} remark={remark} images_only={download_images_only}")
        try:
            ok = redownload_chat_files(chat_id, download_images_only=download_images_only, remark=remark)
            logger.info(f"Redownload worker finished: chat_id={chat_id} ok={ok}")
        except Exception as e:
            logger.exception(f"Redownload worker crashed: chat_id={chat_id} error={e}")

    Thread(target=worker, daemon=True).start()
    return {"message": "redownload started"}


@app.post("/cleanup_stale_baidu_links")
def cleanup_stale_baidu_links(payload: ChatIdRequest):
    chat_id = str(payload.chat_id or "").strip()
    if not chat_id:
        return _json_error(400, "chat_id required")

    existing = _cleanup_baidu_job_snapshot(chat_id)
    if existing and existing.get("status") == "running":
        return JSONResponse(status_code=409, content=existing)

    if not _cleanup_baidu_global_lock.acquire(blocking=False):
        return JSONResponse(status_code=409, content={"error": "已有清理任务正在运行，请稍后再试。"})

    chats = load_chats()
    chat = next((c for c in chats if str(c.get("id")) == chat_id), None)
    remark = chat.get("remark") if chat else None

    job_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    job = {
        "chat_id": chat_id,
        "job_id": job_id,
        "status": "running",
        "started_at": int(time.time()),
        "finished_at": None,
        "scanned_messages": 0,
        "candidate_messages": 0,
        "deleted_messages": 0,
        "checked_links": 0,
        "cached_links": 0,
        "errors": 0,
        "last_error": None,
        "min_interval_seconds": _CLEANUP_BAIDU_MIN_INTERVAL_SECONDS,
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
    return _cleanup_baidu_job_snapshot(chat_id)


@app.get("/cleanup_stale_baidu_links_status/{chat_id}")
def cleanup_stale_baidu_links_status(chat_id: str):
    chat_id = str(chat_id or "").strip()
    if not chat_id:
        return _json_error(400, "chat_id required")

    job = _cleanup_baidu_job_snapshot(chat_id)
    if not job:
        return {"chat_id": chat_id, "status": "idle"}
    return job


@app.post("/delete_chat")
def delete_chat(payload: ChatIdRequest):
    chat_id = str(payload.chat_id or "").strip()
    if not chat_id:
        return _json_error(400, "chat_id required")

    stop_event = _chat_worker_stop_events.get(chat_id)
    if stop_event:
        stop_event.set()

    chats = load_chats()
    before = len(chats)
    chats = [c for c in chats if str(c.get("id")) != chat_id]
    save_chats(chats)

    removed_data = _safe_remove_tree(str(BASE_DIR / "data"), chat_id)
    removed_downloads = _safe_remove_tree(str(BASE_DIR / "downloads"), chat_id)

    deleted = len(chats) != before
    return {"deleted": deleted, "removed_data": removed_data, "removed_downloads": removed_downloads}


@app.get("/messages/{chat_id}")
def get_messages(
    chat_id: str,
    offset: int = Query(0),
    limit: int = Query(20),
):
    conn = get_db(chat_id)
    if not conn:
        return {"total": 0, "offset": 0, "messages": []}

    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,))
        total = cur.fetchone()[0]
        if offset < 0:
            offset = max(total + offset, 0)

        cur.execute(
            "SELECT * FROM messages WHERE chat_id=? ORDER BY timestamp LIMIT ? OFFSET ?",
            (chat_id, limit, offset),
        )
        rows = cur.fetchall()
        messages = []
        for row in rows:
            item = row_to_message(row)
            if item.get("reply_to_msg_id"):
                cur2 = conn.cursor()
                cur2.execute(
                    "SELECT * FROM messages WHERE chat_id=? AND msg_id=?",
                    (chat_id, item["reply_to_msg_id"]),
                )
                r = cur2.fetchone()
                if r:
                    item["reply_message"] = row_to_message(r)
            messages.append(item)
        return {"total": total, "offset": offset, "messages": messages}
    finally:
        conn.close()


@app.get("/messages/{chat_id}/{msg_id}")
def get_message(chat_id: str, msg_id: int):
    conn = get_db(chat_id)
    if not conn:
        return _json_error(400, "chat_id required")

    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM messages WHERE chat_id=? AND msg_id=?", (chat_id, msg_id))
        total = cur.fetchone()[0]
        if total < 1:
            return {"total": 0, "offset": 0, "messages": []}

        cur.execute("SELECT * FROM messages WHERE chat_id=? AND msg_id=?", (chat_id, msg_id))
        rows = cur.fetchall()
        message = row_to_message(rows[0])
        if message.get("reply_to_msg_id"):
            cur.execute(
                "SELECT * FROM messages WHERE chat_id=? AND msg_id=?",
                (chat_id, message["reply_to_msg_id"]),
            )
            r = cur.fetchone()
            if r:
                message["reply_message"] = row_to_message(r)
        return message
    finally:
        conn.close()


@app.get("/reactions_emoticons/{chat_id}")
def get_reactions_emoticons(chat_id: str):
    conn = get_db(chat_id)
    if not conn:
        return {"emoticons": []}

    totals: dict[str, int] = {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT reactions FROM messages WHERE chat_id=? AND reactions IS NOT NULL", (chat_id,))
        for row in cur.fetchall():
            reactions_obj = _parse_reactions_blob(row["reactions"])
            for emoticon, count in _iter_reaction_emoticon_counts(reactions_obj):
                totals[emoticon] = totals.get(emoticon, 0) + count
    finally:
        conn.close()

    emoticons = [{"emoticon": e, "count": totals[e]} for e in sorted(totals.keys(), key=lambda k: (-totals[k], k))]
    return {"emoticons": emoticons}


@app.get("/messages_by_reaction/{chat_id}")
def get_messages_by_reaction(
    chat_id: str,
    emoticon: str = Query(""),
    offset: int = Query(0),
    limit: int = Query(20),
):
    emoticon = (emoticon or "").strip()
    if not emoticon:
        return _json_error(400, "emoticon required")

    conn = get_db(chat_id)
    if not conn:
        return {"total": 0, "offset": 0, "messages": []}

    offset = max(int(offset), 0)
    limit = max(1, min(int(limit), 100))

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT msg_id, timestamp, reactions FROM messages WHERE chat_id=? AND reactions IS NOT NULL",
            (chat_id,),
        )

        scored = []
        for row in cur.fetchall():
            reactions_obj = _parse_reactions_blob(row["reactions"])
            count = _get_reaction_count_for_emoticon(reactions_obj, emoticon)
            if count > 0:
                scored.append((count, int(row["timestamp"] or 0), int(row["msg_id"])))

        scored.sort(key=lambda t: (-t[0], -t[1], -t[2]))
        total = len(scored)

        page = scored[offset : offset + limit]
        msg_ids = [t[2] for t in page]
        counts_by_msg_id = {t[2]: t[0] for t in page}

        messages = []
        if msg_ids:
            placeholders = ",".join(["?"] * len(msg_ids))
            cur.execute(
                f"SELECT * FROM messages WHERE chat_id=? AND msg_id IN ({placeholders})",
                (chat_id, *msg_ids),
            )
            rows = cur.fetchall()
            rows_by_id = {int(r["msg_id"]): r for r in rows}

            for mid in msg_ids:
                row = rows_by_id.get(int(mid))
                if not row:
                    continue
                item = row_to_message(row)
                item["reaction_sort_emoticon"] = emoticon
                item["reaction_sort_count"] = counts_by_msg_id.get(int(mid), 0)

                if item.get("reply_to_msg_id"):
                    cur2 = conn.cursor()
                    cur2.execute(
                        "SELECT * FROM messages WHERE chat_id=? AND msg_id=?",
                        (chat_id, item["reply_to_msg_id"]),
                    )
                    r = cur2.fetchone()
                    if r:
                        item["reply_message"] = row_to_message(r)

                messages.append(item)

        return {"total": total, "offset": offset, "messages": messages}
    finally:
        conn.close()


@app.get("/search/{chat_id}")
def search_messages(chat_id: str, q: str = Query("")):
    query = (q or "").strip().lower()
    conn = get_db(chat_id)
    if not conn:
        return {"total": 0, "results": []}

    try:
        cur = conn.cursor()
        if not query:
            cur.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,))
            total = cur.fetchone()[0]
            return {"total": total, "results": []}

        keywords = query.split()
        conditions = []
        params = []
        for kw in keywords:
            pattern = f"%{kw}%"
            conditions.append(
                "("
                + " OR ".join(
                    [
                        "LOWER(date) LIKE ?",
                        'LOWER(COALESCE(msg, "")) LIKE ?',
                        'LOWER(COALESCE(msg_file_name, "")) LIKE ?',
                    ]
                )
                + ")"
            )
            params.extend([pattern, pattern, pattern])

        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT
                m.*,
                (
                    SELECT COUNT(*) FROM messages m2
                    WHERE m2.chat_id = m.chat_id AND m2.timestamp <= m.timestamp
                ) - 1 AS idx
            FROM messages m
            WHERE m.chat_id=? AND {where_clause}
            ORDER BY m.timestamp
        """
        cur.execute(sql, (chat_id, *params))
        rows = cur.fetchall()

        sql_count = f"""
            SELECT COUNT(*) FROM messages
            WHERE chat_id=? AND {where_clause}
        """
        cur.execute(sql_count, (chat_id, *params))
        total = cur.fetchone()[0]

        results = []
        for row in rows:
            item = row_to_message(row)
            if "idx" in item:
                item["index"] = item.pop("idx")
            if item.get("reply_to_msg_id"):
                cur2 = conn.cursor()
                cur2.execute(
                    "SELECT * FROM messages WHERE chat_id=? AND msg_id=?",
                    (chat_id, item["reply_to_msg_id"]),
                )
                r = cur2.fetchone()
                if r:
                    item["reply_message"] = row_to_message(r)
            results.append(item)

        return {"total": total, "results": results}
    finally:
        conn.close()


@app.post("/execute_sql")
def execute_sql(payload: ExecuteSqlRequest):
    chat_id = str(payload.chat_id or "").strip()
    sql_str = str(payload.sql_str or "").strip()

    if not chat_id or not sql_str:
        return _json_error(400, "chat_id 和 sql_str 必填")

    conn = get_db(chat_id)
    if not conn:
        return _json_error(404, f"数据库不存在: {chat_id}")

    try:
        cur = conn.cursor()
        is_select = sql_str.strip().lower().startswith("select")
        cur.execute(sql_str)
        if is_select:
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            results = [dict(zip(columns, row)) for row in rows]
            conn.commit()
            return {"results": results}
        affected = cur.rowcount
        conn.commit()
        return {"message": "SQL 执行成功", "affected_rows": affected}
    except sqlite3.Error as e:
        return _json_error(500, str(e))
    finally:
        conn.close()

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

from telegram_bot.archiver import handle
from telegram_bot.db_utils import get_connection, get_db_path
from telegram_bot.message_utils import is_ali_link_stale, is_quark_link_stale
from telegram_bot.paths import BASE_DIR, DOWNLOADS_DIR, STATIC_DIR, TEMPLATES_DIR, ensure_runtime_dirs
from telegram_bot.project_logger import get_logger
from telegram_bot.update_messages import redownload_chat_files
from telegram_bot.xunlei_cipher import is_xunlei_link_stale

ensure_runtime_dirs()

logger = get_logger("server")
app = FastAPI()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

CHATS_FILE = str(BASE_DIR / "chats.json")

_workers_started = False
_workers_start_lock = Lock()
_chat_worker_stop_events: dict[str, Event] = {}

_cleanup_global_lock = Lock()

_cleanup_links_jobs: dict[str, dict] = {}
_cleanup_links_jobs_lock = Lock()

_CLEANUP_LINKS_MIN_INTERVAL_SECONDS = 0.7
_CLEANUP_LINKS_JITTER_SECONDS = 0.4
_CLEANUP_LINKS_PROGRESS_FLUSH_EVERY = 10

_CLEANUP_SUPPORTED_PROVIDERS = ("baidu", "quark", "ali", "xunlei")


class AddChatRequest(BaseModel):
    chat_id: str
    remark: str | None = None
    download_files: bool = True
    download_images_only: bool = False
    all_messages: bool = True
    raw_messages: bool = True
    refresh_reactions: bool = False


class ChatIdRequest(BaseModel):
    chat_id: str


class UpdateChatSettingsRequest(BaseModel):
    chat_id: str
    refresh_reactions: bool | None = None


class RedownloadChatRequest(BaseModel):
    chat_id: str
    download_images_only: bool = False


class ExecuteSqlRequest(BaseModel):
    chat_id: str
    sql_str: str


class CleanupLinksRequest(BaseModel):
    chat_id: str
    providers: list[str] | None = None


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

    if not workers_started():
        logger.info(f"Worker {remark} will not start (workers not started)")
        return

    existing = _chat_worker_stop_events.get(chat_id)
    if existing and not existing.is_set():
        logger.info(f"Worker {remark} already running")
        return

    stop_event = Event()
    _chat_worker_stop_events[chat_id] = stop_event

    def get_latest_chat_config() -> dict:
        chats = load_chats()
        latest = next((c for c in chats if str(c.get("id")) == chat_id), None)
        return latest if isinstance(latest, dict) else chat

    def worker():
        while not stop_event.is_set():
            latest = get_latest_chat_config()
            latest_remark = latest.get("remark") or remark
            handle(
                chat_id,
                is_download=bool(latest.get("download_files", True)),
                is_all=bool(latest.get("all_messages", True)),
                is_raw=bool(latest.get("raw_messages", True)),
                remark=latest_remark,
                download_images_only=bool(latest.get("download_images_only", False)),
                refresh_reactions=bool(latest.get("refresh_reactions", False)),
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


def find_chat(info: str) -> tuple[str, str, str] | None:
    """
    根据 id（纯数字字符串）或 username（字符串），返回 (id, visibleName, username)
    """
    info = str(info or "").strip()
    if not info:
        return None

    try:
        if info.isdigit():
            filter_str = f"ID == {info}"
        else:
            filter_str = f"Username == '{info}'"

        cmd = ["tdl", "chat", "ls", "-o", "json", "-f", filter_str]
        output = subprocess.check_output(cmd, encoding="utf-8")
        chats = json.loads(output)

        if not chats:
            return None

        chat = chats[0]
        return str(chat["id"]), chat.get("visible_name", ""), chat.get("username", "")
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
    conn = get_connection(chat_id, sqlite3.Row)
    return conn


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


def _cleanup_links_extract_links(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"(https?://\S+)", text)


def _cleanup_links_job_snapshot(chat_id: str) -> dict:
    with _cleanup_links_jobs_lock:
        job = _cleanup_links_jobs.get(chat_id)
        return dict(job) if isinstance(job, dict) else {}


def _normalize_cleanup_providers(providers: list[str] | None) -> list[str]:
    if not providers:
        return list(_CLEANUP_SUPPORTED_PROVIDERS)
    normalized: list[str] = []
    for provider in providers:
        key = str(provider or "").strip().lower()
        if key in _CLEANUP_SUPPORTED_PROVIDERS and key not in normalized:
            normalized.append(key)
    return normalized


def _cleanup_link_provider(link: str, providers: set[str], *, bdpan: BaiduPanClient) -> str | None:
    if not link:
        return None

    if "baidu" in providers:
        try:
            if bdpan.is_share_link(link):
                return "baidu"
        except Exception:
            pass

    if "quark" in providers and link.startswith("https://pan.quark.cn/s/"):
        return "quark"

    if "ali" in providers and (
        link.startswith("https://www.alipan.com/s/") or link.startswith("https://www.aliyundrive.com/s/")
    ):
        return "ali"

    if "xunlei" in providers and link.startswith("https://pan.xunlei.com/s/"):
        return "xunlei"

    return None


def _cleanup_stale_links_worker(
    chat_id: str,
    remark: str | None,
    job_id: str,
    job: dict,
    providers: list[str],
) -> None:
    logger.info(
        "Cleanup stale links worker start: "
        f"chat_id={chat_id} remark={remark} job_id={job_id} providers={providers}"
    )

    db_path = get_db_path(chat_id)
    if not os.path.exists(db_path):
        with _cleanup_links_jobs_lock:
            job["status"] = "error"
            job["finished_at"] = int(time.time())
            job["last_error"] = "database not found"
        logger.error(f"Cleanup worker aborted (db missing): chat_id={chat_id} path={db_path}")
        return

    providers_set = set(providers)
    bdpan = BaiduPanClient(config=BaiduPanConfig(cookie_file="auth/cookies.txt"))

    stale_cache: dict[str, bool] = {}
    checked_links_by_provider = {p: 0 for p in _CLEANUP_SUPPORTED_PROVIDERS}
    last_call_monotonic = 0.0

    scanned_messages = 0
    candidate_messages = 0
    deleted_messages = 0
    checked_links = 0
    errors = 0
    omit_num = 0

    if os.path.exists("last_cleanup.txt"):
        try:
            with open("last_cleanup.txt", "r", encoding="utf-8") as f:
                omit_num = int((f.read() or "").strip() or "0")
        except Exception:
            omit_num = 0

    def is_link_stale_cached(provider: str, link: str) -> bool | None:
        nonlocal last_call_monotonic, checked_links, errors
        cache_key = f"{provider}:{link}"
        if cache_key in stale_cache:
            return stale_cache[cache_key]

        now = time.monotonic()
        wait_seconds = _CLEANUP_LINKS_MIN_INTERVAL_SECONDS - (now - last_call_monotonic)
        if wait_seconds > 0:
            time.sleep(wait_seconds + random.uniform(0, _CLEANUP_LINKS_JITTER_SECONDS))
        last_call_monotonic = time.monotonic()

        try:
            checked_links += 1
            checked_links_by_provider[provider] = checked_links_by_provider.get(provider, 0) + 1

            if provider == "baidu":
                stale = bool(bdpan.is_link_stale(link))
            elif provider == "quark":
                stale = bool(is_quark_link_stale(link))
            elif provider == "ali":
                stale = bool(is_ali_link_stale(link))
            elif provider == "xunlei":
                stale = bool(is_xunlei_link_stale(link))
            else:
                stale = False

            stale_cache[cache_key] = stale
            return stale
        except Exception as e:
            errors += 1
            with _cleanup_links_jobs_lock:
                job["errors"] = errors
                job["last_error"] = str(e)
            logger.exception(
                "Cleanup worker link check failed: "
                f"chat_id={chat_id} provider={provider} link={link} error={e}"
            )
            return None

    try:
        like_patterns: list[str] = []
        if "baidu" in providers_set:
            like_patterns.append("%baidu.com%")
        if "quark" in providers_set:
            like_patterns.append("%pan.quark.cn%")
        if "ali" in providers_set:
            like_patterns.extend(["%alipan.com%", "%aliyundrive.com%"])
        if "xunlei" in providers_set:
            like_patterns.append("%pan.xunlei.com%")

        if not like_patterns:
            with _cleanup_links_jobs_lock:
                job["status"] = "error"
                job["finished_at"] = int(time.time())
                job["last_error"] = "no providers enabled"
            return

        like_where = " OR ".join(["msg LIKE ?"] * len(like_patterns))

        conn = get_connection(chat_id)
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT msg_id, msg
            FROM messages
            WHERE chat_id=? AND msg IS NOT NULL AND ({like_where})
            ORDER BY timestamp
            """,
            (chat_id, *like_patterns),
        )
        rows = cur.fetchall()
        rows = rows[omit_num:]

        delete_sql = "DELETE FROM messages WHERE chat_id=? AND msg_id=?"
        deletes_since_commit = 0
        cur_delete = conn.cursor()

        logger.debug(f"Cleanup worker started: chat_id={chat_id} total_messages={len(rows)}")
        for msg_id, msg in rows:
            scanned_messages += 1
            msg_text = msg or ""
            links = _cleanup_links_extract_links(msg_text)
            if not links:
                continue

            should_keep = False
            has_supported_share_link = False
            
            is_stale = True
            has_share_link = False
            for link in links:
                try:
                    provider = _cleanup_link_provider(link, providers_set, bdpan=bdpan)
                    logger.debug(f"Cleanup worker link provider: msg_id={msg_id} link={link} provider={provider}")
                    if provider is None:
                        logger.debug(f"Cleanup worker link unsupported: msg_id={msg_id} link={link}")
                        continue

                    has_share_link = True
                    has_supported_share_link = True
                    stale = is_link_stale_cached(provider, link)
                    logger.debug(f"Cleanup worker link stale check: msg_id={msg_id} link={link} provider={provider} stale={stale}")
                    if stale is None:
                        is_stale = False
                    if not stale:
                        is_stale = False
                    else:
                        logger.warning(f"stale: msg_id={msg_id} link={link} provider={provider} msg_text={msg_text[:12]}... links={links}")
                except Exception as e:
                    errors += 1
                    should_keep = True
                    with _cleanup_links_jobs_lock:
                        job["errors"] = errors
                        job["last_error"] = str(e)
                    logger.exception(f"Cleanup worker parse failed: msg_id={msg_id} error={e}")
                    break

            if not has_supported_share_link:
                logger.warning(
                    f"Cleanup worker found no supported links: msg_id={msg_id} links={links}"
                )
                continue

            candidate_messages += 1
            
            if not should_keep:
                if has_share_link:
                    if not is_stale:
                        should_keep = True
                else:
                    should_keep = True
                    
            if scanned_messages % _CLEANUP_LINKS_PROGRESS_FLUSH_EVERY == 0:
                with _cleanup_links_jobs_lock:
                    job["scanned_messages"] = scanned_messages
                    job["candidate_messages"] = candidate_messages
                    job["deleted_messages"] = deleted_messages
                    job["checked_links"] = checked_links
                    job["cached_links"] = len(stale_cache)
                    job["errors"] = errors
                    job["checked_links_by_provider"] = dict(checked_links_by_provider)
                    
            if should_keep:
                logger.debug(f"Cleanup worker keep message: chat_id={chat_id} msg_id={msg_id}")
                continue

            try:
                cur_delete.execute(delete_sql, (chat_id, int(msg_id)))
                deleted_messages += 1
                deletes_since_commit += 1
                if deletes_since_commit >= 10:
                    logger.debug(f"Cleanup worker committing deletes: chat_id={chat_id}")
                    conn.commit()
                    with open("_last_cleanup.txt", "w", encoding="utf-8") as f:
                        f.write(str(omit_num + scanned_messages - deleted_messages))
                    deletes_since_commit = 0
            except Exception as e:
                errors += 1
                with _cleanup_links_jobs_lock:
                    job["errors"] = errors
                    job["last_error"] = str(e)
                logger.exception(f"Cleanup worker delete failed: chat_id={chat_id} msg_id={msg_id} error={e}")

            logger.debug(f"Cleanup worker progress: chat_id={chat_id} scanned={scanned_messages} "
                        f"candidates={candidate_messages} deleted={deleted_messages} checked_links={checked_links} "
                        f"cache={len(stale_cache)} errors={errors}")

        conn.commit()
        conn.close()

        if os.path.exists("last_cleanup.txt"):
            try:
                os.remove("last_cleanup.txt")
            except Exception:
                pass

        with _cleanup_links_jobs_lock:
            job["status"] = "done"
            job["finished_at"] = int(time.time())
            job["scanned_messages"] = scanned_messages
            job["candidate_messages"] = candidate_messages
            job["deleted_messages"] = deleted_messages
            job["checked_links"] = checked_links
            job["cached_links"] = len(stale_cache)
            job["errors"] = errors
            job["checked_links_by_provider"] = dict(checked_links_by_provider)

        logger.info(
            "Cleanup stale links worker finished: "
            f"chat_id={chat_id} job_id={job_id} scanned={scanned_messages} "
            f"candidates={candidate_messages} deleted={deleted_messages} checked_links={checked_links} "
            f"cache={len(stale_cache)} errors={errors} providers={providers}"
        )
    except Exception as e:
        logger.exception(f"Cleanup worker crashed: chat_id={chat_id} job_id={job_id} error={e}")
        with _cleanup_links_jobs_lock:
            job["status"] = "error"
            job["finished_at"] = int(time.time())
            job["last_error"] = str(e)
            job["scanned_messages"] = scanned_messages
            job["candidate_messages"] = candidate_messages
            job["deleted_messages"] = deleted_messages
            job["checked_links"] = checked_links
            job["cached_links"] = len(stale_cache)
            job["errors"] = errors + 1
            job["checked_links_by_provider"] = dict(checked_links_by_provider)


@app.get("/")
def index_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/chat/{chat_id}")
def chat_page(chat_id: str, request: Request):
    chats = load_chats()
    chat_username = next((c.get('username') for c in chats if c.get('id') == chat_id), '')
    return templates.TemplateResponse("template.html", {"request": request, "chat_id": chat_id, 'chat_username': chat_username})


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


@app.post("/update_chat_settings")
def update_chat_settings(payload: UpdateChatSettingsRequest):
    chat_id = str(payload.chat_id or "").strip()
    if not chat_id:
        return _json_error(400, "chat_id required")

    chats = load_chats()
    chat = next((c for c in chats if str(c.get("id")) == chat_id), None)
    if not chat:
        return _json_error(404, "chat not found")

    updated = False
    if payload.refresh_reactions is not None:
        chat["refresh_reactions"] = bool(payload.refresh_reactions)
        updated = True

    if updated:
        save_chats(chats)

    return {"updated": updated, "chat": chat}


@app.post("/add_chat")
def add_chat(payload: AddChatRequest):
    input_chat_id = str(payload.chat_id or "").strip()
    result = find_chat(input_chat_id)
    if result is None:
        return _json_error(400, "Invalid chat_id")

    chat_id, remark, username = result
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
        "refresh_reactions": bool(payload.refresh_reactions),
        "username": username,
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
    # Backward-compatible alias (old UI / clients).
    return cleanup_stale_links(CleanupLinksRequest(chat_id=payload.chat_id, providers=["baidu"]))


@app.get("/cleanup_stale_baidu_links_status/{chat_id}")
def cleanup_stale_baidu_links_status(chat_id: str):
    # Backward-compatible alias (old UI / clients).
    return cleanup_stale_links_status(chat_id)


@app.post("/cleanup_stale_links")
def cleanup_stale_links(payload: CleanupLinksRequest):
    chat_id = str(payload.chat_id or "").strip()
    if not chat_id:
        return _json_error(400, "chat_id required")

    providers = _normalize_cleanup_providers(payload.providers)
    if not providers:
        return _json_error(400, f"providers must be one of: {', '.join(_CLEANUP_SUPPORTED_PROVIDERS)}")

    existing = _cleanup_links_job_snapshot(chat_id)
    if existing and existing.get("status") == "running":
        return JSONResponse(status_code=409, content=existing)

    if not _cleanup_global_lock.acquire(blocking=False):
        return JSONResponse(status_code=409, content={"error": "已有清理任务正在运行，请稍后再试。"})

    chats = load_chats()
    chat = next((c for c in chats if str(c.get("id")) == chat_id), None)
    remark = chat.get("remark") if chat else None

    job_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    job = {
        "chat_id": chat_id,
        "job_id": job_id,
        "status": "running",
        "providers": providers,
        "started_at": int(time.time()),
        "finished_at": None,
        "scanned_messages": 0,
        "candidate_messages": 0,
        "deleted_messages": 0,
        "checked_links": 0,
        "cached_links": 0,
        "checked_links_by_provider": {p: 0 for p in _CLEANUP_SUPPORTED_PROVIDERS},
        "errors": 0,
        "last_error": None,
        "min_interval_seconds": _CLEANUP_LINKS_MIN_INTERVAL_SECONDS,
    }
    with _cleanup_links_jobs_lock:
        _cleanup_links_jobs[chat_id] = job

    def worker():
        try:
            _cleanup_stale_links_worker(chat_id, remark, job_id, job, providers)
        finally:
            try:
                _cleanup_global_lock.release()
            except RuntimeError:
                pass

    Thread(target=worker, daemon=True).start()
    return _cleanup_links_job_snapshot(chat_id)


@app.get("/cleanup_stale_links_status/{chat_id}")
def cleanup_stale_links_status(chat_id: str):
    chat_id = str(chat_id or "").strip()
    if not chat_id:
        return _json_error(400, "chat_id required")

    job = _cleanup_links_job_snapshot(chat_id)
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

        limit = max(1, min(int(limit), 200))
        cur.execute(
            """
            SELECT
                m.chat_id,
                m.msg_id,
                m.date,
                m.timestamp,
                m.msg_file_name,
                m.user,
                m.msg,
                m.ori_height,
                m.ori_width,
                m.og_info,
                m.reactions,
                m.msg_files,
                m.reply_to_msg_id,
                r.chat_id AS r_chat_id,
                r.msg_id AS r_msg_id,
                r.date AS r_date,
                r.timestamp AS r_timestamp,
                r.msg_file_name AS r_msg_file_name,
                r.user AS r_user,
                r.msg AS r_msg,
                r.ori_height AS r_ori_height,
                r.ori_width AS r_ori_width,
                r.og_info AS r_og_info,
                r.reactions AS r_reactions,
                r.msg_files AS r_msg_files,
                r.reply_to_msg_id AS r_reply_to_msg_id
            FROM messages m
            LEFT JOIN messages r
                ON r.chat_id = m.chat_id AND r.msg_id = m.reply_to_msg_id
            WHERE m.chat_id=?
            ORDER BY m.msg_id
            LIMIT ? OFFSET ?
            """,
            (chat_id, limit, offset),
        )
        rows = cur.fetchall()
        messages = []
        for row in rows:
            raw = dict(row)
            item = row_to_message({k: v for k, v in raw.items() if not k.startswith("r_")})

            if raw.get("r_msg_id") is not None:
                reply_raw = {k[2:]: v for k, v in raw.items() if k.startswith("r_")}
                item["reply_message"] = row_to_message(reply_raw)
            messages.append(item)
        return {"total": total, "offset": offset, "messages": messages}
    finally:
        conn.close()


@app.get("/messages_between/{chat_id}")
def get_messages_between(
    chat_id: str,
    start_msg_id: int = Query(...),
    end_msg_id: int = Query(...),
    direction: str = Query("down"),
    limit: int = Query(20),
):
    """
    Fetch context messages between (start_msg_id, end_msg_id), exclusive.

    direction=down: returns messages near start_msg_id (ascending msg_id).
    direction=up:   returns messages near end_msg_id (ascending msg_id, but taken from the end).

    This is used by the search UI to expand context between two search hits without
    needing expensive row-number/offset calculations.
    """
    conn = get_db(chat_id)
    if not conn:
        return {"messages": [], "has_more": False}

    start_msg_id = int(start_msg_id)
    end_msg_id = int(end_msg_id)
    if start_msg_id >= end_msg_id:
        return {"messages": [], "has_more": False}

    direction = (direction or "down").strip().lower()
    if direction not in {"down", "up"}:
        return _json_error(400, "direction must be 'down' or 'up'")

    limit = max(1, min(int(limit), 200))
    fetch_limit = min(limit + 1, 201)

    try:
        cur = conn.cursor()
        order_sql = "ORDER BY m.msg_id" if direction == "down" else "ORDER BY m.msg_id DESC"
        cur.execute(
            f"""
            SELECT
                m.chat_id,
                m.msg_id,
                m.date,
                m.timestamp,
                m.msg_file_name,
                m.user,
                m.msg,
                m.ori_height,
                m.ori_width,
                m.og_info,
                m.reactions,
                m.msg_files,
                m.reply_to_msg_id,
                r.chat_id AS r_chat_id,
                r.msg_id AS r_msg_id,
                r.date AS r_date,
                r.timestamp AS r_timestamp,
                r.msg_file_name AS r_msg_file_name,
                r.user AS r_user,
                r.msg AS r_msg,
                r.ori_height AS r_ori_height,
                r.ori_width AS r_ori_width,
                r.og_info AS r_og_info,
                r.reactions AS r_reactions,
                r.msg_files AS r_msg_files,
                r.reply_to_msg_id AS r_reply_to_msg_id
            FROM messages m
            LEFT JOIN messages r
                ON r.chat_id = m.chat_id AND r.msg_id = m.reply_to_msg_id
            WHERE m.chat_id=? AND m.msg_id > ? AND m.msg_id < ?
            {order_sql}
            LIMIT ?
            """,
            (chat_id, start_msg_id, end_msg_id, fetch_limit),
        )
        rows = cur.fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        if direction == "up":
            rows = list(reversed(rows))

        messages = []
        for row in rows:
            raw = dict(row)
            item = row_to_message({k: v for k, v in raw.items() if not k.startswith("r_")})
            if raw.get("r_msg_id") is not None:
                reply_raw = {k[2:]: v for k, v in raw.items() if k.startswith("r_")}
                item["reply_message"] = row_to_message(reply_raw)
            messages.append(item)

        return {"messages": messages, "has_more": has_more}
    finally:
        conn.close()


@app.get("/messages/{chat_id}/{msg_id}")
def get_message(chat_id: str, msg_id: int):
    conn = get_db(chat_id)
    if not conn:
        return _json_error(400, "chat_id required")

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                m.chat_id,
                m.msg_id,
                m.date,
                m.timestamp,
                m.msg_file_name,
                m.user,
                m.msg,
                m.ori_height,
                m.ori_width,
                m.og_info,
                m.reactions,
                m.msg_files,
                m.reply_to_msg_id,
                r.chat_id AS r_chat_id,
                r.msg_id AS r_msg_id,
                r.date AS r_date,
                r.timestamp AS r_timestamp,
                r.msg_file_name AS r_msg_file_name,
                r.user AS r_user,
                r.msg AS r_msg,
                r.ori_height AS r_ori_height,
                r.ori_width AS r_ori_width,
                r.og_info AS r_og_info,
                r.reactions AS r_reactions,
                r.msg_files AS r_msg_files,
                r.reply_to_msg_id AS r_reply_to_msg_id
            FROM messages m
            LEFT JOIN messages r
                ON r.chat_id = m.chat_id AND r.msg_id = m.reply_to_msg_id
            WHERE m.chat_id=? AND m.msg_id=?
            """,
            (chat_id, msg_id),
        )
        row = cur.fetchone()
        if not row:
            return {"total": 0, "offset": 0, "messages": []}

        raw = dict(row)
        message = row_to_message({k: v for k, v in raw.items() if not k.startswith("r_")})
        if raw.get("r_msg_id") is not None:
            reply_raw = {k[2:]: v for k, v in raw.items() if k.startswith("r_")}
            message["reply_message"] = row_to_message(reply_raw)
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
                f"""
                SELECT
                    m.chat_id,
                    m.msg_id,
                    m.date,
                    m.timestamp,
                    m.msg_file_name,
                    m.user,
                    m.msg,
                    m.ori_height,
                    m.ori_width,
                    m.og_info,
                    m.reactions,
                    m.msg_files,
                    m.reply_to_msg_id,
                    r.chat_id AS r_chat_id,
                    r.msg_id AS r_msg_id,
                    r.date AS r_date,
                    r.timestamp AS r_timestamp,
                    r.msg_file_name AS r_msg_file_name,
                    r.user AS r_user,
                    r.msg AS r_msg,
                    r.ori_height AS r_ori_height,
                    r.ori_width AS r_ori_width,
                    r.og_info AS r_og_info,
                    r.reactions AS r_reactions,
                    r.msg_files AS r_msg_files,
                    r.reply_to_msg_id AS r_reply_to_msg_id
                FROM messages m
                LEFT JOIN messages r
                    ON r.chat_id = m.chat_id AND r.msg_id = m.reply_to_msg_id
                WHERE m.chat_id=? AND m.msg_id IN ({placeholders})
                """,
                (chat_id, *msg_ids),
            )
            rows = cur.fetchall()
            rows_by_id = {int(r["msg_id"]): r for r in rows}

            for mid in msg_ids:
                row = rows_by_id.get(int(mid))
                if not row:
                    continue

                raw = dict(row)
                item = row_to_message({k: v for k, v in raw.items() if not k.startswith("r_")})
                item["reaction_sort_emoticon"] = emoticon
                item["reaction_sort_count"] = counts_by_msg_id.get(int(mid), 0)
                if raw.get("r_msg_id") is not None:
                    reply_raw = {k[2:]: v for k, v in raw.items() if k.startswith("r_")}
                    item["reply_message"] = row_to_message(reply_raw)

                messages.append(item)

        return {"total": total, "offset": offset, "messages": messages}
    finally:
        conn.close()


@app.get("/search/{chat_id}")
def search_messages(
    chat_id: str,
    q: str = Query(""),
    offset: int = Query(0),
    limit: int = Query(20),
):
    query = (q or "").strip().lower()
    conn = get_db(chat_id)
    if not conn:
        return {"total": 0, "offset": 0, "messages": []}

    try:
        cur = conn.cursor()
        if not query:
            cur.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,))
            total = cur.fetchone()[0]
            if offset < 0:
                offset = max(total + offset, 0)
            return {"total": total, "offset": offset, "messages": []}

        keywords = query.split()
        conditions = []
        params = []
        fields_or = " OR ".join([
            "LOWER(m.date) LIKE ?",
            'LOWER(COALESCE(m.msg, "")) LIKE ?',
            'LOWER(COALESCE(m.msg_file_name, "")) LIKE ?',
        ])
                
        for kw in keywords:
            neg = kw.startswith("-")
            kw = kw[1:] if neg else kw
            kw = kw.strip().lower()
            if not kw:
                continue
            
            pattern = f"%{kw}%"
            if neg:
                conditions.append(f"NOT ({fields_or})")
            else:
                conditions.append(f"({fields_or})")
            params.extend([pattern, pattern, pattern])

        where_sql = ""
        if conditions:
            where_sql = " AND " + " AND ".join(conditions)

        sql_count = f"""
            SELECT COUNT(*) FROM messages m
            WHERE m.chat_id=?{where_sql}
        """
        cur.execute(sql_count, (chat_id, *params))
        total = cur.fetchone()[0]

        if offset < 0:
            offset = max(total + offset, 0)
        offset = max(int(offset), 0)
        limit = max(1, min(int(limit), 200))

        sql_page = f"""
            SELECT
                m.chat_id,
                m.msg_id,
                m.date,
                m.timestamp,
                m.msg_file_name,
                m.user,
                m.msg,
                m.ori_height,
                m.ori_width,
                m.og_info,
                m.reactions,
                m.msg_files,
                m.reply_to_msg_id,
                r.chat_id AS r_chat_id,
                r.msg_id AS r_msg_id,
                r.date AS r_date,
                r.timestamp AS r_timestamp,
                r.msg_file_name AS r_msg_file_name,
                r.user AS r_user,
                r.msg AS r_msg,
                r.ori_height AS r_ori_height,
                r.ori_width AS r_ori_width,
                r.og_info AS r_og_info,
                r.reactions AS r_reactions,
                r.msg_files AS r_msg_files,
                r.reply_to_msg_id AS r_reply_to_msg_id
            FROM messages m
            LEFT JOIN messages r
                ON r.chat_id = m.chat_id AND r.msg_id = m.reply_to_msg_id
            WHERE m.chat_id=?{where_sql}
            ORDER BY m.msg_id
            LIMIT ? OFFSET ?
        """
        cur.execute(sql_page, (chat_id, *params, limit, offset))
        rows = cur.fetchall()

        messages = []
        for row in rows:
            raw = dict(row)
            item = row_to_message({k: v for k, v in raw.items() if not k.startswith("r_")})

            if raw.get("r_msg_id") is not None:
                reply_raw = {k[2:]: v for k, v in raw.items() if k.startswith("r_")}
                item["reply_message"] = row_to_message(reply_raw)
            messages.append(item)

        return {"total": total, "offset": offset, "messages": messages}
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

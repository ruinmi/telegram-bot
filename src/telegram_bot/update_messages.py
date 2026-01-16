import os
import subprocess
from .project_logger import get_logger
import time
import json
import uuid
import requests
import urllib.parse
import threading
from .db_utils import get_last_export_time, set_exported_time
from .paths import BASE_DIR, ensure_runtime_dirs

tdl_lock = threading.Lock()
ensure_runtime_dirs()

IMAGE_EXTENSIONS = "jpg,jpeg,png,webp,gif"

def _tail_lines(text: str | None, max_lines: int = 80) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text.strip()
    return ("\n".join(lines[-max_lines:])).strip()


def _run_tdl_command(command: list[str], logger, label: str):
    logger.info(f"{label}: Running command: {' '.join(command)}")
    with tdl_lock:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as e:
            logger.error(f"{label}: tdl not found: {e}")
            raise
        except Exception as e:
            logger.exception(f"{label}: Failed to run command: {e}")
            raise

    stdout_tail = _tail_lines(result.stdout)
    stderr_tail = _tail_lines(result.stderr)

    logger.info(f"{label}: returncode={result.returncode}")
    if stdout_tail:
        logger.info(f"{label}: stdout (tail):\n{stdout_tail}")
    if stderr_tail:
        # Many CLIs write progress / warnings to stderr even on success.
        if result.returncode == 0:
            logger.info(f"{label}: stderr (tail):\n{stderr_tail}")
        else:
            logger.error(f"{label}: stderr (tail):\n{stderr_tail}")

    return result


def export_chat(their_id, msg_json_path, msg_json_temp_path, conn, is_download=True, is_all=True, is_raw=True, download_images_only=False, remark=None):
    logger = get_logger(remark or their_id)
    logger.info("Starting chat export...")
    last_export_time = get_last_export_time(conn)
    current_time = str(int(time.time()))
    command = [
        'tdl', 'chat', 'export',
        '-c', str(their_id),
        '--with-content',
        '-o', msg_json_temp_path,
        '-i', f'{last_export_time},{current_time}'
    ]
    if is_raw:
        command.append('--raw')
    if is_all:
        command.append('--all')


    result = _run_tdl_command(command, logger, label="tdl chat export")
    
    if result.returncode == 0:
        logger.info("Chat export successful.")

        # Download chat files using tdl dl command
        if is_download:
            logger.info("Downloading files...")
            download_path = str(BASE_DIR / 'downloads' / str(their_id))
            os.makedirs(download_path, exist_ok=True)
            download_command = [
                'tdl',
                'dl',
                '-f',
                msg_json_temp_path,
                '-d',
                download_path,
                '--skip-same',
                '--continue',
                '-t',
                '8',
                '-l',
                '4',
            ]
            if download_images_only:
                download_command.extend(['-i', IMAGE_EXTENSIONS])
            download_result = _run_tdl_command(download_command, logger, label="tdl dl")
            if download_result.returncode != 0:
                logger.error("Error downloading files (see tdl dl stdout/stderr above).")
            else:
                logger.info("Download finished (see tdl dl stdout/stderr above).")

        # Load existing messages if the file exists
        if os.path.exists(msg_json_path):
            with open(msg_json_path, 'r', encoding='utf-8') as file:
                existing_data = json.load(file)
        else:
            existing_data = {"id": their_id, "messages": []}

        # Load new messages from the temporary exported file
        with open(msg_json_temp_path, 'r', encoding='utf-8') as file:
            new_data = json.load(file)

        # Append new messages to the existing messages
        existing_data['messages'].extend(new_data['messages'])

        # Save the combined messages back to the file
        with open(msg_json_path, 'w', encoding='utf-8') as file:
            json.dump(existing_data, file, ensure_ascii=False, indent=4)

        # Save the current time as the last export time
        set_exported_time(conn, current_time)
    else:
        logger.error("Error exporting chat (see tdl chat export stdout/stderr above).")

def download(url, their_id, remark=None):
    logger = get_logger(remark or their_id)
    download_path = str(BASE_DIR / 'downloads' / str(their_id))
    os.makedirs(download_path, exist_ok=True)
    

    file_name, file_extension = os.path.splitext(os.path.basename(urllib.parse.urlparse(url).path))
    unique_name = str(uuid.uuid4()) + file_extension
    full_save_path = os.path.join(download_path, unique_name)

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        with open(full_save_path, 'wb') as f:
            f.write(response.content)
        return full_save_path
    except Exception as e:
        logger.exception(f"下载失败: {e}")
        return None


def redownload_chat_files(their_id, download_images_only=False, remark=None):
    """
    Manually re-download chat files by exporting a full file list (0..now) and running tdl dl.
    This does NOT touch the DB export cursor.
    """
    logger = get_logger(remark or their_id)
    current_time = str(int(time.time()))
    data_dir = str(BASE_DIR / 'data' / str(their_id))
    os.makedirs(data_dir, exist_ok=True)
    msg_json_temp_path = os.path.join(data_dir, f'{their_id}_redownload_temp.json')

    export_command = [
        'tdl',
        'chat',
        'export',
        '-c',
        str(their_id),
        '--with-content',
        '-o',
        msg_json_temp_path,
        '-i',
        f'0,{current_time}',
        '--raw',
        '--all',
    ]
    export_result = _run_tdl_command(export_command, logger, label="tdl chat export (redownload)")
    if export_result.returncode != 0:
        logger.error("Redownload export failed (see stdout/stderr above).")
        return False

    download_path = str(BASE_DIR / 'downloads' / str(their_id))
    os.makedirs(download_path, exist_ok=True)
    download_command = [
        'tdl',
        'dl',
        '-f',
        msg_json_temp_path,
        '-d',
        download_path,
        '--skip-same',
        '--continue',
        '-t',
        '8',
        '-l',
        '4',
    ]
    if download_images_only:
        download_command.extend(['-i', IMAGE_EXTENSIONS])

    download_result = _run_tdl_command(download_command, logger, label="tdl dl (redownload)")
    try:
        if os.path.exists(msg_json_temp_path):
            os.remove(msg_json_temp_path)
    except Exception:
        pass

    if download_result.returncode != 0:
        logger.error("Redownload failed (see stdout/stderr above).")
        return False

    logger.info("Redownload finished (see stdout/stderr above).")
    return True

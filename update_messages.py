import os
import subprocess
from project_logger import get_logger
import time
import json
import uuid
import requests
import urllib
import threading
from db_utils import get_last_export_time, set_last_export_time

tdl_lock = threading.Lock()
script_dir = os.path.dirname(os.path.abspath(__file__))

def export_chat(their_id, msg_json_path, msg_json_temp_path, conn, is_download=True, is_all=True, is_raw=True, remark=None):
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


    logger.info(f"Running command: {' '.join(command)}")

    with tdl_lock:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
    
    if result.returncode == 0:
        logger.info("Chat export successful.")
        
        # New: Download chat files using tdl dl command
        if is_download:
            logger.info("Downloading files...")
            download_path = os.path.join(script_dir, 'downloads', their_id)
            if not os.path.exists(download_path):
                os.makedirs(download_path)
            download_command = ['tdl', 'dl', '-f', msg_json_temp_path, '-d', download_path, '--skip-same', '--restart', '-t', '8', '-l', '4']
            logger.info(f"Running download command: {' '.join(download_command)}")
            with tdl_lock:
                download_result = subprocess.run(download_command, capture_output=True, text=True, encoding='utf-8')
            if download_result.returncode != 0:
                logger.error(f"Error downloading files: {download_result.stderr}")
            else:
                logger.info("Download successful.")
        
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
        set_last_export_time(conn, current_time)
    else:
        logger.error(f"Error exporting chat: {result.stdout}")

def download(url, their_id, remark=None):
    logger = get_logger(remark or their_id)
    download_path = os.path.join(script_dir, 'downloads', their_id)
    if not os.path.exists(download_path):
        os.makedirs(download_path)
    

    file_name, file_extension = os.path.splitext(os.path.basename(urllib.parse.urlparse(url).path))
    unique_name = str(uuid.uuid4()) + file_extension
    full_save_path = os.path.join(download_path, unique_name)

    response = requests.get(url)
    if response.status_code == 200:
        with open(full_save_path, 'wb') as f:
            f.write(response.content)
        return full_save_path
    else:
        logger.error(f"下载失败，状态码: {response.status_code}")
        return None

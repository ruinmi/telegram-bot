"""Utilities for handling Open Graph data and image sizing."""

from __future__ import annotations

import json
import os
from hashlib import md5
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from PIL import Image

from telegram_bot.http_client import get as http_get
from telegram_bot.project_logger import get_logger
from telegram_bot.update_messages import download
from telegram_bot.paths import BASE_DIR, ensure_runtime_dirs
from telegram_bot.db_utils import get_app_connection, get_og_cache, set_og_cache

ensure_runtime_dirs()


def load_og_data() -> dict:
    conn = get_app_connection()
    try:
        rows = conn.execute("SELECT url, value FROM og_cache").fetchall()
        data: dict = {}
        for url, raw in rows:
            try:
                data[url] = json.loads(raw) if raw else {}
            except Exception:
                data[url] = {}
        return data
    finally:
        conn.close()


def save_og_data(og_data: dict) -> None:
    conn = get_app_connection()
    try:
        for url, value in (og_data or {}).items():
            set_og_cache(conn, str(url), value if isinstance(value, dict) else {})
    finally:
        conn.close()


def generate_url_key(url: str) -> str:
    return md5(url.encode('utf-8')).hexdigest()


def get_image_size(image_path: str) -> tuple[int, int]:
    with Image.open(image_path) as img:
        return img.size


def calculate_size(file_path: str, og_width: int | None, og_height: int | None) -> tuple[int | None, int | None]:
    original_width = original_height = 0
    if os.path.exists(file_path):
        if file_path.lower().endswith(('.mp4', '.mov', '.avi')):
            return 500, 280
        if not file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
            return None, None
        original_width, original_height = get_image_size(file_path)
    elif og_width and og_height:
        original_width = int(og_width)
        original_height = int(og_height)
    return original_width, original_height

def get_open_graph_info(url: str, chat_id: str | None = None) -> dict | None:
    conn = get_app_connection()
    try:
        cached = get_og_cache(conn, url)
        if cached:
            return cached
        if cached == {}:
            return None
        try:
            headers = {
                'User-Agent': r"Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2272.96 Mobile Safari/537.36 TelegramBot (like TwitterBot)"
            }
            response = http_get(url, timeout=5, headers=headers)
            if response.status_code != 200:
                set_og_cache(conn, url, {})
                return None

            parsed_url = urlparse(url)
            domain_parts = parsed_url.netloc.split(':')[0].split('.')
            domain = domain_parts[-2] if len(domain_parts) >= 2 else domain_parts[0]
            if domain.lower() == 'b23':
                domain = 'bilibili'
            soup = BeautifulSoup(response.text, 'html.parser')
            if domain.lower() == 'tiktok':
                data_script = soup.find('script', {'id': '__UNIVERSAL_DATA_FOR_REHYDRATION__'})
                if data_script:
                    json_data = json.loads(data_script.get_text()) if data_script and data_script.get_text() else {}
                    json_data = json_data.get('__DEFAULT_SCOPE__', {})
                    video_detail = json_data.get('webapp.video-detail', {})
                    cover = video_detail.get('itemInfo', {}).get('itemStruct', {}).get('video', {}).get('cover')
                    share_meta = video_detail.get('shareMeta', {})
                    og_info = {
                        'title': share_meta.get('title'),
                        'image': cover,
                        'description': share_meta.get('desc'),
                        'site_name': domain.capitalize(),
                        'width': None,
                        'height': None,
                        'url': url,
                    }
                    set_og_cache(conn, url, og_info)
                    return og_info
            og_title = soup.find('meta', property='og:title')
            og_image = soup.find('meta', property='og:image')
            og_description = soup.find('meta', property='og:description')
            og_site_name = soup.find('meta', property='og:site_name')
            og_width = soup.find('meta', property='og:image:width') or soup.find('meta', property='og:width')
            og_height = soup.find('meta', property='og:image:height') or soup.find('meta', property='og:height')
            og_url = soup.find('meta', property='og:url')

            og_info = {
                'title': og_title['content'] if isinstance(og_title, Tag) and 'content' in og_title.attrs else None,
                'image': og_image['content'] if isinstance(og_image, Tag) and 'content' in og_image.attrs else None,
                'description': og_description.get('content') if isinstance(og_description, Tag) else None,
                'site_name': og_site_name['content'] if isinstance(og_site_name, Tag) and 'content' in og_site_name.attrs else domain.capitalize(),
                'width': og_width['content'] if isinstance(og_width, Tag) and 'content' in og_width.attrs else None,
                'height': og_height['content'] if isinstance(og_height, Tag) and 'content' in og_height.attrs else None,
                'url': og_url['content'] if isinstance(og_url, Tag) and 'content' in og_url.attrs else None,
            }
            set_og_cache(conn, url, og_info)
            return og_info
        except httpx.HTTPError as e:
            logger = get_logger()
            logger.exception(f'error og:{e}')
            set_og_cache(conn, url, {})
            return None
    finally:
        conn.close()


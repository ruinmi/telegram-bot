"""Utilities for handling Open Graph data and image sizing."""

from __future__ import annotations

import json
import os
from hashlib import md5
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

from project_logger import get_logger
from update_messages import download

script_dir = os.path.dirname(os.path.abspath(__file__))
OG_DATA_FILE = 'data/og_data.json'


def load_og_data() -> dict:
    file_path = os.path.join(script_dir, OG_DATA_FILE)
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    return {}


def save_og_data(og_data: dict) -> None:
    with open(os.path.join(script_dir, OG_DATA_FILE), 'w', encoding='utf-8') as file:
        json.dump(og_data, file, ensure_ascii=False, indent=4)


def generate_url_key(url: str) -> str:
    return md5(url.encode('utf-8')).hexdigest()


def get_image_size(image_path: str) -> tuple[int, int]:
    with Image.open(image_path) as img:
        return img.size


def calculate_display_size(file_path: str, og_width: int | None, og_height: int | None) -> tuple[int | None, int | None]:
    original_width = original_height = None
    if os.path.exists(file_path):
        if file_path.lower().endswith(('.mp4', '.mov', '.avi')):
            return 500, 280
        if not file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
            return None, None
        original_width, original_height = get_image_size(file_path)
    elif og_width and og_height:
        original_width = int(og_width)
        original_height = int(og_height)
    else:
        return None, None

    max_width_ratio = 0.7
    max_height_ratio = 0.7
    max_display_width = 1000 * max_width_ratio
    max_display_height = 800 * max_height_ratio
    aspect_ratio = original_width / original_height
    if original_width > max_display_width:
        display_width = max_display_width
        display_height = display_width / aspect_ratio
    else:
        display_width = original_width
        display_height = original_height
    if display_height > max_display_height:
        display_height = max_display_height
        display_width = display_height * aspect_ratio
    return int(display_width), int(display_height)


def get_open_graph_info(url: str, chat_id: str | None = None) -> dict | None:
    og_data = load_og_data()
    if url in og_data and og_data[url]:
        return og_data[url]
    try:
        headers = {
            'User-Agent': r"Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2272.96 Mobile Safari/537.36 TelegramBot (like TwitterBot)"
        }
        response = requests.get(url, timeout=5, headers=headers)
        if response.status_code != 200:
            og_data[url] = {}
            save_og_data(og_data)
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
                json_data = json.loads(data_script.string).get('__DEFAULT_SCOPE__', {})
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
                og_data[url] = og_info
                save_og_data(og_data)
                return og_info
        og_title = soup.find('meta', property='og:title')
        og_image = soup.find('meta', property='og:image')
        og_description = soup.find('meta', property='og:description')
        og_site_name = soup.find('meta', property='og:site_name')
        og_width = soup.find('meta', property='og:image:width') or soup.find('meta', property='og:width')
        og_height = soup.find('meta', property='og:image:height') or soup.find('meta', property='og:height')
        og_url = soup.find('meta', property='og:url')
        if og_image and og_image['content'].startswith('//'):
            img_url = f'{parsed_url.scheme}:{og_image["content"]}'
            path = download(img_url, chat_id) if chat_id else None
            if path and os.path.exists(path):
                og_image['content'] = path.replace('/telegram-bot/', '')

        og_info = {
            'title': og_title['content'] if og_title else None,
            'image': og_image['content'] if og_image else None,
            'description': og_description['content'] if og_description else None,
            'site_name': og_site_name['content'] if og_site_name else domain.capitalize(),
            'width': og_width['content'] if og_width else None,
            'height': og_height['content'] if og_height else None,
            'url': og_url['content'] if og_url else None,
        }
        og_data[url] = og_info
        save_og_data(og_data)
        return og_info
    except requests.RequestException as e:
        logger = get_logger()
        logger.exception(f'error og:{e}')
        og_data[url] = {}
        save_og_data(og_data)
        return None

import json
from datetime import datetime, timezone, timedelta

import db_utils
from update_messages import export_chat, download
from project_logger import get_logger
from PIL import Image
import os
import re
import requests
from bs4 import BeautifulSoup
from hashlib import md5
from urllib.parse import urlparse
from db_utils import get_connection, save_messages, update_og_info

script_dir = os.path.dirname(os.path.abspath(__file__))

OG_DATA_FILE = 'data/og_data.json'


# 加载已有的Open Graph数据
def load_og_data():
    f = os.path.join(script_dir, OG_DATA_FILE)
    if os.path.exists(f):
        with open(f, 'r', encoding='utf-8') as file:
            return json.load(file)
    return {}


# 保存Open Graph数据到本地
def save_og_data(og_data):
    with open(os.path.join(script_dir, OG_DATA_FILE), 'w', encoding='utf-8') as file:
        json.dump(og_data, file, ensure_ascii=False, indent=4)


# 根据URL生成唯一的键值
def generate_url_key(url):
    return md5(url.encode('utf-8')).hexdigest()


def get_image_size(image_path):
    with Image.open(image_path) as img:
        width, height = img.size
    return width, height


def calculate_telegram_image_display(file_path, og_width, og_height):
    original_width, original_height = None, None
    if os.path.exists(file_path):
        # 处理视频文件，返回默认尺寸
        if file_path.lower().endswith(('.mp4', '.mov', '.avi')):
            return 500, 280
        # 非图片文件返回None
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


def load_json(file_path):
    with open(file_path, "r", encoding="utf-8") as infile:
        return json.load(infile)


def convert_timestamp_to_date(timestamp, tz):
    return datetime.fromtimestamp(timestamp, tz).strftime('%Y-%m-%d %H:%M:%S')


def get_open_graph_info(url):
    og_data = load_og_data()  # 加载本地存储的Open Graph数据
    # 如果数据已经缓存，直接返回缓存的数据
    if url in og_data and og_data[url]:
        return og_data[url]
    try:
        headers = {
            'User-Agent': r"Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2272.96 Mobile Safari/537.36 TelegramBot (like TwitterBot)"
        }
        response = requests.get(url, timeout=5, headers=headers)
        if response.status_code == 200:
            parsed_url = urlparse(url)
            domain_parts = parsed_url.netloc.split(':')[0].split('.')
            if len(domain_parts) >= 2:
                domain = domain_parts[-2]
            else:
                domain = domain_parts[0]
            if domain.lower() == 'b23':
                domain = 'bilibili'
            soup = BeautifulSoup(response.text, 'html.parser')
            if domain.lower() == 'tiktok':
                data_script = soup.find('script', {'id': '__UNIVERSAL_DATA_FOR_REHYDRATION__'})
                if data_script:
                    json_data = json.loads(data_script.string).get('__DEFAULT_SCOPE__', {})
                    video_detail = json_data.get('webapp.video-detail', {})
                    cover = video_detail.get('itemInfo', {}).get('itemStruct', {}).get('video', {}).get('cover', None)
                    share_meta = video_detail.get('shareMeta', {})
                    og_info = {
                        'title': share_meta.get('title', None),
                        'image': cover,
                        'description': share_meta.get('desc', None),
                        'site_name': domain.capitalize(),
                        'width': None,
                        'height': None,
                        'url': url
                    }
                    og_data[url] = og_info
                    save_og_data(og_data)
                    return og_info
            og_title = soup.find('meta', property='og:title')
            og_image = soup.find('meta', property='og:image')
            og_description = soup.find('meta', property='og:description')
            og_site_name = soup.find('meta', property='og:site_name')
            og_width = soup.find('meta', property='og:image:width')
            og_width = og_width if og_width else soup.find('meta', property='og:width')
            og_height = soup.find('meta', property='og:image:height')
            og_height = og_height if og_height else soup.find('meta', property='og:height')
            og_url = soup.find('meta', property='og:url')
            if og_image and og_image['content'].startswith('//'):
                img_url = f'{parsed_url.scheme}:{og_image["content"]}'
                path = download(img_url, id)
                if path and os.path.exists(path):
                    # remove telegram-bot folder prefix
                    og_image['content'] = path.replace('/telegram-bot/', '')

            og_info = {
                'title': og_title['content'] if og_title else None,
                'image': og_image['content'] if og_image else None,
                'description': og_description['content'] if og_description else None,
                'site_name': og_site_name['content'] if og_site_name else domain.capitalize(),
                'width': og_width['content'] if og_width else None,
                'height': og_height['content'] if og_height else None,
                'url': og_url['content'] if og_url else None
            }
            og_data[url] = og_info
            save_og_data(og_data)
            return og_info
        else:
            og_data[url] = {}
            save_og_data(og_data)
            return None
    except requests.RequestException as e:
        logger = get_logger()
        logger.exception(f'error og:{e}')
        og_data[url] = {}
        save_og_data(og_data)
        return None


def parse_messages(id, raw_messages, tz, remark=None):
    logger = get_logger(remark or id)
    messages = []
    group_messages = []
    last_group_id = None
    for raw_message in raw_messages:
        msg_text = raw_message.get("text", "")
        links = re.findall(r'(https?://\S+)', msg_text)
        msg_id = raw_message.get("id", None)
        msg_file = raw_message.get("file", "")
        msg_file_name = f'downloads/{id}/{id}_{msg_id}_{msg_file}' if msg_file != "" else ""
        # 获取链接的Open Graph信息
        og_info = None
        og_width, og_height = None, None
        if links and not msg_file:  # 如果有链接且没有文件
            og_info = get_open_graph_info(links[0])  # 获取第一个链接的Open Graph信息
            if og_info:
                og_width, og_height = og_info.get('width', None), og_info.get('height', None)
        display_width, display_height = calculate_telegram_image_display(msg_file_name, og_width, og_height)
        timestamp = raw_message.get("date", 0)
        date = convert_timestamp_to_date(timestamp, tz)
        raw_data = raw_message.get("raw", {}) or {}
        from_id = raw_data.get("FromID") or {}
        user_id = from_id.get('UserID', '') if isinstance(from_id, dict) else ''
        reply_to_msg_id = (raw_data.get('ReplyTo') or {}).get('ReplyToMsgID', 0)
        reactions = raw_data.get('Reactions') or {}
        user = '我' if user_id else ''

        message = {
            'date': date,
            'timestamp': timestamp,
            'msg_id': msg_id,
            'msg_file_name': msg_file_name,
            'msg_files': [],
            'user': user,
            'msg': msg_text,
            'reply_to_msg_id': reply_to_msg_id,
            'reactions': reactions,
            'display_height': display_height,
            'display_width': display_width,
            'og_info': og_info
        }
        group_id = raw_data.get('GroupedID', '')
        
        if group_id and (group_id == last_group_id or last_group_id is None):
            group_messages.append(message)
            last_group_id = group_id
        else:
            if group_messages:
                # 找主消息（有文字的）
                main_msg = next((m for m in group_messages if m.get('msg')), group_messages[0])
                # 收集文件
                for msg in group_messages:
                    if msg['msg_id'] != main_msg['msg_id'] and msg['msg_file_name']:
                        main_msg['msg_files'].append(msg['msg_file_name'])

                # 如果主消息本身有 msg_file_name，也放进去
                if main_msg['msg_file_name']:
                    main_msg['msg_files'].append(main_msg['msg_file_name'])
                    main_msg['msg_file_name'] = ''

                if len(group_messages) > 0:
                    w, h = compute_msg_files_size(len(group_messages))
                    for msg in group_messages:
                        msg['display_width'] = w
                        msg['display_height'] = h
                    
                messages.append(main_msg)

            # 新的 group
            group_messages = [message]
            last_group_id = group_id
    # 循环结束后处理最后一个 group
    if group_messages:
        main_msg = next((m for m in group_messages if m.get('msg')), group_messages[0])
        for msg in group_messages:
            if msg['msg_id'] != main_msg['msg_id'] and msg['msg_file_name']:
                main_msg['msg_files'].append(msg['msg_file_name'])
        if main_msg['msg_file_name']:
            main_msg['msg_files'].append(main_msg['msg_file_name'])
            main_msg['msg_file_name'] = ''

        if len(group_messages) > 0:
            w, h = compute_msg_files_size(len(group_messages))
            for msg in group_messages:
                msg['display_width'] = w
                msg['display_height'] = h        
        messages.append(main_msg)

    # 排序
    return sorted(messages, key=lambda x: x['date'])


def compute_msg_files_size(num_files, container_width=500, max_per_row=3, gap=5):
    """
    根据图片数量，计算 msg_files 中每张图片的宽高。
    默认每行最多 3 张，容器宽度 500px，间距 5px
    返回: (width, height)
    """
    if num_files == 0:
        return 0, 0

    # 当前行的列数（如果图片少于 max_per_row，就只用 num_files）
    cols = min(num_files, max_per_row)

    # 所有间距总宽度
    total_gap_width = gap * (cols - 1)

    # 每张图片宽度
    width = (container_width - total_gap_width) // cols

    # 如果是正方形，高度等于宽度
    height = width

    return width, height


def handle(chat_id, is_download, is_all, is_raw, remark):
    logger = get_logger(remark or chat_id)
    # 获取脚本所在的目录
    data_dir = str(os.path.join(script_dir, 'data', chat_id))
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    msg_json_path = os.path.join(data_dir, f'{chat_id}_chat.json')
    msg_json_temp_path = os.path.join(data_dir, f'{chat_id}_chat_temp.json')
    db_path = os.path.join(data_dir, 'messages.db')

    with get_connection(chat_id) as conn:
        try:
            export_chat(
                chat_id,
                msg_json_path,
                msg_json_temp_path,
                conn,
                is_download=is_download,
                is_all=is_all,
                is_raw=is_raw,
                remark=remark
            )
        except Exception as e:
            logger.exception(f'Error writing {msg_json_path}: {e}')
    
        if os.path.exists(msg_json_path):
            try:
                data = load_json(msg_json_path)
                china_timezone = timezone(timedelta(hours=8))
                messages_data = data.get("messages", [])
                messages = parse_messages(chat_id, messages_data, china_timezone, remark)
                save_messages(conn, chat_id, messages)
                db_utils.set_last_export_time(conn, db_utils.get_exported_time(conn))
            except Exception as e:
                logger.exception(f'Error parsing {msg_json_path}: {e}')
            finally:
                os.remove(msg_json_path)
    
        if os.path.exists(msg_json_temp_path):
            os.remove(msg_json_temp_path)

    logger.info(f"Messages data saved to {db_path}")

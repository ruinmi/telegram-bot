import json
from datetime import datetime, timezone, timedelta
import sys
from update_messages import export_chat, download
from PIL import Image
import os
import re
from jinja2 import Environment, FileSystemLoader
import requests
from bs4 import BeautifulSoup
from hashlib import md5
from urllib.parse import urlparse
import sqlite3

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


def get_open_graph_info(id, url, script_dir):
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
            og_height = soup.find('meta', property='og:image:height')
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
        print(f'error og:{e}')
        og_data[url] = {}
        save_og_data(og_data)
        return None


def parse_messages(id, raw_messages, tz, script_dir):
    messages = []
    for raw_message in raw_messages:
        msg_text = raw_message.get("text", "")
        links = re.findall(r'(https?://\S+)', msg_text)
        msg_id = raw_message.get("id", None)
        msg_file = raw_message.get("file", "")
        msg_file_name = f'downloads/{id}/{id}_{msg_id}_{msg_file}' if msg_file != "" else ""
        if msg_file_name != "" and not os.path.exists(os.path.join(script_dir, msg_file_name)):
            msg_file_name = ""
        # 获取链接的Open Graph信息
        og_info = None
        og_width, og_height = None, None
        if links and not msg_file:  # 如果有链接且没有文件
            og_info = get_open_graph_info(id, links[0], script_dir)  # 获取第一个链接的Open Graph信息
            if og_info:
                og_width, og_height = og_info.get('width', None), og_info.get('height', None)
        display_width, display_height = calculate_telegram_image_display(msg_file_name, og_width, og_height)
        timestamp = raw_message.get("date", 0)
        date = convert_timestamp_to_date(timestamp, tz)
        raw_data = raw_message.get("raw", None)
        FROM_ID = raw_data.get("FromID", None) if raw_data is not None else None
        user_id = FROM_ID.get('UserID', None) if FROM_ID is not None else None
        user = '' if user_id is None else '我'

        messages.append({
            'date': date,
            'timestamp': timestamp,
            'msg_id': msg_id,
            'msg_file_name': msg_file_name,
            'user': user,
            'msg': msg_text,
            'display_height': display_height,
            'display_width': display_width,
            'og_info': og_info
        })
    # 按时间正序排列（旧的在前，新消息在后）
    return sorted(messages, key=lambda x: x['date'])


def save_messages_to_db(db_path, chat_id, messages):
    conn = sqlite3.connect(db_path)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages(
            chat_id TEXT,
            msg_id INTEGER,
            date TEXT,
            timestamp INTEGER,
            msg_file_name TEXT,
            user TEXT,
            msg TEXT,
            display_height INTEGER,
            display_width INTEGER,
            og_info TEXT,
            PRIMARY KEY(chat_id, msg_id)
        )
    ''')

    insert_sql = '''
        INSERT OR IGNORE INTO messages(
            chat_id, msg_id, date, timestamp,
            msg_file_name, user, msg,
            display_height, display_width, og_info
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''

    data = []
    for m in messages:
        og_info = json.dumps(m['og_info'], ensure_ascii=False) if m.get('og_info') else None
        data.append((chat_id, m['msg_id'], m['date'], m['timestamp'],
                     m['msg_file_name'], m['user'], m['msg'],
                     m['display_height'], m['display_width'], og_info))

    conn.executemany(insert_sql, data)
    conn.commit()
    conn.close()


def update_og_info(db_path, chat_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 获取该 chat_id 的所有消息
    cursor.execute('SELECT msg_id, msg FROM messages WHERE chat_id = ?', (chat_id,))
    rows = cursor.fetchall()
    update_sql = '''
        UPDATE messages
        SET og_info = ?
        WHERE chat_id = ? AND msg_id = ?
    '''
    for msg_id, msg in rows:
        if not msg:
            continue
        links = re.findall(r'(https?://\S+)', msg)
        if not links:
            continue

        try:
            og_info = get_open_graph_info(chat_id, links[0], script_dir)
            og_info_json = json.dumps(og_info, ensure_ascii=False)
            cursor.execute(update_sql, (og_info_json, chat_id, msg_id))
        except Exception as e:
            print(f"处理 msg_id={msg_id} 出错: {e}")

    conn.commit()
    conn.close()


def main():
    # 检测是否需要显示帮助信息
    if "--help" in sys.argv or "-h" in sys.argv:
        print_help()
        return

    if len(sys.argv) < 2 or len(sys.argv) > 9:
        print("参数数量错误，请使用 '--help' 查看用法说明。")
        return

    chat_id = sys.argv[1]

    remark = None
    if '--remark' in sys.argv:
        idx = sys.argv.index('--remark')
        if idx + 1 < len(sys.argv):
            remark = sys.argv[idx + 1]
    elif '-r' in sys.argv:
        idx = sys.argv.index('-r')
        if idx + 1 < len(sys.argv):
            remark = sys.argv[idx + 1]

    # 参数标志解析
    download_files = "--ndf" not in sys.argv
    all_messages = "--nam" not in sys.argv
    raw_messages = "--nrm" not in sys.argv

    # 获取脚本所在的目录
    data_dir = os.path.join(script_dir, 'data', chat_id)
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    messages_file = os.path.join(data_dir, f'{chat_id}_chat.json')
    messages_file_temp = os.path.join(data_dir, f'{chat_id}_chat_temp.json')
    db_path = os.path.join(data_dir, 'messages.db')

    if '--og-update' in sys.argv:
        update_og_info(db_path, chat_id)
        return

    # 迁移旧的 messages.json 数据
    old_json = os.path.join(data_dir, 'messages.json')
    if os.path.exists(old_json) and not os.path.exists(db_path):
        try:
            with open(old_json, 'r', encoding='utf-8') as f:
                old_msgs = json.load(f)
            if isinstance(old_msgs, dict):
                old_msgs = old_msgs.get('messages', [])
            save_messages_to_db(db_path, chat_id, old_msgs)
            os.remove(old_json)
        except Exception as e:
            print(f"Failed to migrate old JSON data: {e}")

    if remark:
        info_file = os.path.join(data_dir, 'info.json')
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump({'remark': remark}, f, ensure_ascii=False, indent=2)

    export_chat(
        chat_id,
        messages_file,
        messages_file_temp,
        download_files=download_files,
        all_messages=all_messages,
        raw_messages=raw_messages
    )

    data = load_json(messages_file_temp)
    china_timezone = timezone(timedelta(hours=8))
    raw_messages = data.get("messages", [])
    messages = parse_messages(chat_id, raw_messages, china_timezone, script_dir)

    save_messages_to_db(db_path, chat_id, messages)

    # 删除临时文件
    if os.path.exists(messages_file_temp):
        os.remove(messages_file_temp)
    if os.path.exists(messages_file):
        os.remove(messages_file)

    print(f"Messages data saved to {db_path}")


def print_help():
    """显示脚本使用帮助信息"""
    help_text = """
使用方法:
    python main.py <user_id> [选项]

参数说明:
    <user_id>           必填，用户ID，用于查找聊天记录数据。
    [--ndf]             可选，禁止下载附件文件（默认会下载）。
    [--nam]             可选，禁止导出全部消息，仅导出带包含文件的消息。
    [--nrm]             可选，禁止导出原始消息数据，使用解析后的数据。
    [--remark NAME]     可选，为该聊天设置备注名，也可使用 -r NAME。
    [--og-update]       可选，更新空的og信息。

通用选项:
    -h, --help          显示此帮助信息并退出。

示例:
    python main.py 12345 --ne output.html
    python main.py 12345 --nam --nrm
    python main.py 12345 --help

说明:
    1. 本程序会在当前目录下创建 'data/<user_id>/' 文件夹保存中间数据。
    2. 多个选项可以同时使用，顺序不限。
"""
    print(help_text)


if __name__ == "__main__":
    main()

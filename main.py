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

OG_DATA_FILE = 'og_data.json'
# 加载已有的Open Graph数据
def load_og_data():
    if os.path.exists(OG_DATA_FILE):
        with open(OG_DATA_FILE, 'r', encoding='utf-8') as file:
            return json.load(file)
    return {}

# 保存Open Graph数据到本地
def save_og_data(og_data):
    with open(OG_DATA_FILE, 'w', encoding='utf-8') as file:
        json.dump(og_data, file, ensure_ascii=False, indent=4)

# 根据URL生成唯一的键值
def generate_url_key(url):
    return md5(url.encode('utf-8')).hexdigest()

script_dir = os.path.dirname(os.path.abspath(__file__))
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
    if url in og_data:
        return og_data[url]
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)'
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
    except requests.RequestException:
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

def generate_html(chat_id):
    env = Environment(loader=FileSystemLoader(script_dir))  # 加载当前目录下的模板
    template = env.get_template('template.html')  # 加载模板文件
    html_content = template.render(chat_id=chat_id)  # 渲染模板
    return html_content.strip()

def save_html(html_content, filename='chat_log.html'):
    with open(filename, 'w', encoding='utf-8') as file:
        file.write(html_content)

def main():
    # 检测是否需要显示帮助信息
    if "--help" in sys.argv or "-h" in sys.argv:
        print_help()
        return

    if len(sys.argv) < 2 or len(sys.argv) > 7:
        print("参数数量错误，请使用 '--help' 查看用法说明。")
        return

    chat_id = sys.argv[1]

    # 参数标志解析
    no_export = "--ne" in sys.argv
    download_files = "--ndf" not in sys.argv
    all_messages = "--nam" not in sys.argv
    raw_messages = "--nrm" not in sys.argv

    # 查找是否有指定输出文件名
    output_filename = None
    for arg in sys.argv[2:]:
        if arg.endswith(".html"):
            output_filename = arg
            break

    if output_filename is None:
        output_filename = "chat_log.html"

    # 获取脚本所在的目录
    data_dir = os.path.join(script_dir, 'data', chat_id)
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    messages_file = os.path.join(data_dir, f'{chat_id}_chat.json')
    messages_file_temp = os.path.join(data_dir, f'{chat_id}_chat_temp.json')

    if not no_export:
        export_chat(
            chat_id, 
            messages_file, 
            messages_file_temp, 
            download_files=download_files, 
            all_messages=all_messages, 
            raw_messages=raw_messages
        )

    data = load_json(messages_file)
    china_timezone = timezone(timedelta(hours=8))
    raw_messages = data["messages"]
    messages = parse_messages(chat_id, raw_messages, china_timezone, script_dir)

     # 保存 messages 到 messages.json 文件
    messages_json_path = os.path.join(data_dir, 'messages.json')
    with open(messages_json_path, 'w', encoding='utf-8') as json_file:
        json.dump(messages, json_file, ensure_ascii=False, indent=4)

    # 生成 HTML 文件
    html_content = generate_html(chat_id)
    output_path = os.path.join(script_dir, output_filename)
    save_html(html_content, output_path)

    print(f"Chat log saved to {output_path}")
    print(f"Messages data saved to {messages_json_path}")


def print_help():
    """显示脚本使用帮助信息"""
    help_text = """
使用方法:
    python main.py <user_id> [选项] [输出文件.html]

参数说明:
    <user_id>           必填，用户ID，用于查找聊天记录数据。
    [--ne]              可选，禁用聊天记录导出功能，仅生成 HTML。
    [--ndf]             可选，禁止下载附件文件（默认会下载）。
    [--nam]             可选，禁止导出全部消息，仅导出带包含文件的消息。
    [--nrm]             可选，禁止导出原始消息数据，使用解析后的数据。
    [输出文件.html]      可选，指定导出的 HTML 文件名称，默认为 chat_log.html。

通用选项:
    -h, --help          显示此帮助信息并退出。

示例:
    python main.py 12345 --ne output.html
    python main.py 12345 --nam --nrm
    python main.py 12345 --help

说明:
    1. 本程序会在当前目录下创建 'data/<user_id>/' 文件夹保存中间数据。
    2. 默认导出为 'chat_log.html'，可通过指定参数修改。
    3. 多个选项可以同时使用，顺序不限。
"""
    print(help_text)

if __name__ == "__main__":
    main()

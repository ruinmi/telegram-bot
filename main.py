import json
from datetime import datetime, timezone, timedelta
import sys
from update_messages import export_chat
from PIL import Image
import os
import re
from jinja2 import Environment, FileSystemLoader

script_dir = os.path.dirname(os.path.abspath(__file__))
def get_image_size(image_path):
    with Image.open(image_path) as img:
        width, height = img.size
    return width, height

def calculate_telegram_image_display(file_path):
    if not os.path.exists(file_path):
        return None, None
    # 处理视频文件，返回默认尺寸
    if file_path.lower().endswith(('.mp4', '.mov', '.avi')):
        return 500, 280
    # 非图片文件返回None
    if not file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
        return None, None
    original_width, original_height = get_image_size(file_path)
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

def parse_messages(id, raw_messages, tz, script_dir):
    messages = []
    for raw_message in raw_messages:
        msg_text = raw_message.get("text", "")
        msg_text = re.sub(r'(https?://\S+)', r'<a href="\1" target="_blank">\1</a>', msg_text)
        msg_text = msg_text.replace("\n", "<br/>")
        msg_id = raw_message.get("id", None)
        msg_file = raw_message.get("file", "")
        msg_file_name = f'downloads/{id}/{id}_{msg_id}_{msg_file}' if msg_file != "" else ""
        if msg_file_name != "" and not os.path.exists(os.path.join(script_dir, msg_file_name)):
            msg_file_name = ""
        display_width, display_height = calculate_telegram_image_display(msg_file_name)
        timestamp = raw_message.get("date", 0)
        date = convert_timestamp_to_date(timestamp, tz)
        raw_data = raw_message.get("raw", None)
        FROM_ID = raw_data.get("FromID", None) if raw_data is not None else None
        user_id = FROM_ID.get('UserID', None) if FROM_ID is not None else None
        user = '' if user_id is None else '我'
        messages.append({'date': date, 'timestamp': timestamp, 'msg_id': msg_id, 
                         'msg_file_name': msg_file_name, 'user': user, 'msg': msg_text, 
                         'display_height': display_height, 'display_width': display_width})
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

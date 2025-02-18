import json
from datetime import datetime, timezone, timedelta
import sys
from update_messages import export_chat
from PIL import Image
import os
import re

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

def generate_html(messages):
    # 将消息数据转换为 JSON 字符串，嵌入页面供 JS 使用
    messages_json = json.dumps(messages, ensure_ascii=False)
    html_content = f"""
<html>
    <head>
        <meta charset="utf-8">
        <link rel="icon" href="resources/favicon.svg" type="image/svg+xml">
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
        <title>聊天记录</title>
        <style>
            @font-face {{
                font-family: 'Roboto';
                src: url('fonts/Roboto-Regular.ttf') format('truetype');
                font-weight: normal;
                font-style: normal;
            }}
            body {{  
                font-size: 16px;
                font-family: "Roboto", "Apple Color Emoji", sans-serif;
                background-color: #000;
                color: #333; margin: 0;
                display: flex;
                justify-content: center;
                background-image: url('resources/bg.png');
                overscroll-behavior: contain;
            }}
            @media screen and (max-width: 768px) {{
                body {{ font-size: 20px; }}
                body #header {{ justify-content: center; }}
                body #searchBox {{ font-size: 14px; width: 250px }}
                body #confirmSearch {{ 
                    height: 38px;
                    width: 68px;
                    font-size: 14px;
                    line-height: 38px; 
                }}
                body .date {{
                    font-size: 14px;
                    bottom: -23px;
                }}

            }}

            .container {{ max-width: 1000px; width: 100%; }}
            #header {{ position: fixed; display: flex; align-items: center; background: #000; z-index: 1; width: 100%; padding: 10px 0 7px; }}
            #searchBox {{ padding: 10px; width: 300px; outline: none; background: #000; border: 1px solid #ffffff38; color: white; border-radius: .9375rem; }}
            #confirmSearch {{ margin-left: 10px; background: #212121; color: white; border: none; border-radius: .575rem; cursor: pointer; line-height: 16px; width: 65px; height: 37px; }}
            #messages {{ padding: 50px 0 60px 0; }}
            .message {{ max-width: 60%; margin: 16px; border-radius: .9375rem; clear: both; word-wrap: break-word; position: relative; }}
            .message.left {{ background-color: #212121; color: white; float: left; text-align: left; }}
            .message.right {{ background-color: rgb(118,106,200); color: white; float: right; text-align: left; }}
            .date {{ font-size: 0.75rem; color: #fff8; margin-bottom: 5px; position: absolute; bottom: -21px; right: 0; width: max-content; }}
            .date.left {{ left: 0; }}
            .user {{ display: none; font-weight: bold; margin-bottom: 5px; }}
            .msg {{ padding: .3125rem .5rem .375rem; }}
            .msg a {{ color: #8774e1; text-decoration: none; }}
            .msg a:hover {{ text-decoration: underline; }}
            .msg .highlight {{ 
                background-color: #cae3f7;
                border-radius: 5px;
                padding: 2px;
                color: #000;
            }}
            .message.right .msg a {{ color: #fff; }}
            .hidden {{ display: none !important; }}
            .message.left.context {{ background-color: #21212199; color: #9b9b9b; }}
            .message.right.context {{ background-color: rgb(118,106,200,0.6); color: #9b9b9b; }}
            .clearfix::after {{ content: ""; clear: both; display: table; }}
            .scroll-button {{ position: fixed; right: 20px; background-color: #212121; color: white; border: none; padding: 10px; border-radius: 50%; cursor: pointer; }}
            #scrollTop {{ bottom: 80px; }}
            #scrollBottom {{ bottom: 20px; }}
            .image {{ width: 100%; display: flex; justify-content: center; }}
            .video video {{ max-width: 100%; border-radius: .9375rem; }}
            .image img {{ border-radius: .9375rem; }}
            .download {{
                padding: .3125rem .5rem .375rem;
            }}
            .download a {{
                overflow: hidden;
                width: 100%;
                white-space: nowrap;
                text-overflow: ellipsis;
                display: inline-block;
                color: #fff;
            }}
            .separator {{
                clear: both;
                width: 100%;
                text-align: center;
                cursor: pointer;
            }}
            .separator.down {{
                margin-bottom: 70px;
            }}
            .separator:hover {{
                background-color: rgba(255, 255, 255, 0.1);
            }}

            .separator span {{
                color: #aaa;
                font-size: 0.9rem;
            }}

        </style>
    </head>
    <body>
        <div class="container">
            <div id="header">
                <input type="text" id="searchBox" placeholder="请输入日期或聊天内容进行搜索...">
                <button id="confirmSearch" onclick="searchMessages()">搜索</button>
            </div>
            <div id="messages"></div>
        </div>
        <button id="scrollTop" class="scroll-button" onclick="window.scrollTo(0, 0)">⬆️</button>
        <button id="scrollBottom" class="scroll-button" onclick="window.scrollTo(0, document.body.scrollHeight)">⬇️</button>
        <script>
            // 全部聊天记录数据，由 Python 端生成
            let allMessages = {messages_json};
            let currentStartIndex;
            let isSearching = false;
            const messagesContainer = document.getElementById('messages');
            function highlightText(text, searchValue) {{
                if (!searchValue) return text;
                // 创建正则表达式，'gi' 表示全局、不区分大小写
                const regex = new RegExp(`(${{searchValue}})`, 'gi');
                return text.replace(regex, '<span class="highlight">$1</span>');
            }}
            // 根据单个消息数据生成 HTML 结构
            function createMessageHtml(message, index, searchValue) {{
                let position = message.user === '我' ? 'right' : 'left';
                let mediaHtml = "";
                if (message.msg_file_name) {{
                    let lowerName = message.msg_file_name.toLowerCase();
                    if (lowerName.endsWith('.png') || lowerName.endsWith('.jpg') || lowerName.endsWith('.jpeg') || lowerName.endsWith('.gif') || lowerName.endsWith('.webp')) {{
                        mediaHtml = `<div class="image"><img style="max-width: 100%; max-height: ${{message.display_height}}px" src="${{message.msg_file_name}}" alt="图片" /></div>`;
                    }} else if (lowerName.endsWith('.mp4') || lowerName.endsWith('.mov') || lowerName.endsWith('.avi')) {{
                        mediaHtml = `<div class="video"><video controls><source src="${{message.msg_file_name}}" type="video/mp4">Your browser does not support the video tag.</video></div>`;
                    }} else {{
                        let parts = message.msg_file_name.split('/');
                        let fileName = parts[parts.length - 1];
                        mediaHtml = `
                            <div class="download">
                                <a href="${{message.msg_file_name}}" download>
                                    <svg style="vertical-align: bottom;" t="1739785072303" class="icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="1483" width="24" height="24"><path d="M928 448c-17.7 0-32 14.3-32 32v319.5c0 17.9-14.6 32.5-32.5 32.5h-703c-17.9 0-32.5-14.6-32.5-32.5V480c0-17.7-14.3-32-32-32s-32 14.3-32 32v319.5c0 53.2 43.3 96.5 96.5 96.5h703c53.2 0 96.5-43.3 96.5-96.5V480c0-17.7-14.3-32-32-32z" fill="#fff" p-id="1484"></path><path d="M489.4 726.6c0.4 0.4 0.8 0.7 1.2 1.1l0.4 0.4c0.2 0.2 0.5 0.4 0.7 0.6 0.2 0.2 0.4 0.3 0.6 0.4 0.2 0.2 0.5 0.4 0.7 0.5 0.2 0.1 0.4 0.3 0.6 0.4 0.2 0.2 0.5 0.3 0.7 0.5 0.2 0.1 0.4 0.2 0.6 0.4 0.3 0.2 0.5 0.3 0.8 0.5 0.2 0.1 0.3 0.2 0.5 0.3 0.3 0.2 0.6 0.3 0.9 0.5 0.1 0.1 0.3 0.1 0.4 0.2 0.3 0.2 0.7 0.3 1 0.5 0.1 0.1 0.2 0.1 0.3 0.2 0.4 0.2 0.7 0.3 1.1 0.5 0.1 0 0.2 0.1 0.2 0.1 0.4 0.2 0.8 0.3 1.2 0.5 0.1 0 0.1 0 0.2 0.1 0.4 0.2 0.9 0.3 1.3 0.4h0.1c0.5 0.1 0.9 0.3 1.4 0.4h0.1c0.5 0.1 0.9 0.2 1.4 0.3h0.2c0.4 0.1 0.9 0.2 1.3 0.2h0.4c0.4 0.1 0.8 0.1 1.2 0.1 0.3 0 0.5 0 0.8 0.1 0.3 0 0.5 0 0.8 0.1H512.2c0.7 0 1.3 0 1.9-0.1h0.6c0.6 0 1.2-0.1 1.8-0.2h0.3c0.7-0.1 1.4-0.2 2.1-0.4 0.1 0 0.2 0 0.3-0.1 0.7-0.2 1.3-0.3 2-0.5h0.1c0.7-0.2 1.4-0.5 2.1-0.7h0.1l2.1-0.9h0.1c0.7-0.3 1.4-0.7 2-1.1 0.1 0 0.1-0.1 0.2-0.1 1.6-0.9 3.2-2 4.6-3.2 0.2-0.2 0.4-0.4 0.6-0.5 0.2-0.2 0.4-0.3 0.6-0.5 0.2-0.2 0.5-0.4 0.7-0.7l0.4-0.4c0.1-0.1 0.2-0.1 0.2-0.2l191.7-191.7c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L544 626.7V96c0-17.7-14.3-32-32-32s-32 14.3-32 32v530.7L342.6 489.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3l192.1 191.9z" fill="#fff" p-id="1485"></path></svg>
                                    ${{fileName}}
                                </a>
                            </div>`;
                    }}
                }}
                let messageContent = message.msg ? highlightText(message.msg, searchValue) : "";
                return `<div class="message ${{
                    position
                }} clearfix">
                            <div class="date ${{
                                position
                            }}">${{message.date}}</div>
                            <div class="user ${{
                                position
                            }}">${{message.user}}</div>
                            ${{
                                mediaHtml
                            }}
                            ${{ message.msg ? `<div class="msg">${{messageContent}}</div>` : "" }}
                        </div>`;
            }}


            // 创建可点击的分隔符元素，点击后仅展示 gap 内 2 条上下文消息，且新展示的消息在分隔符上方展示，新的分隔符在下方（如果还有剩余）
            function createSeparatorElement(startIndex, endIndex, direction) {{ 
                let separator = document.createElement('div');
                separator.className = 'separator ' + direction;
                if (direction === "up") {{
                    separator.innerHTML = ' <div style="color: white">.</div><div style="color: white">.</div><div style="color: white">.</div> <span style="color: #aaa; font-size: 0.9rem;">向上加载</span>';
                }} else {{
                    separator.innerHTML = '<span style="color: #aaa; font-size: 0.9rem;">向下加载</span> <div style="color: white">.</div><div style="color: white">.</div><div style="color: white">.</div>';
                }}
                separator.dataset.start = startIndex;
                separator.dataset.end = endIndex;
                separator.dataset.direction = direction;
                separator.addEventListener('click', function() {{
                    if (separator.dataset.direction === "down") {{
                        let s = parseInt(separator.dataset.start);
                        let e = parseInt(separator.dataset.end);
                        let count = Math.min(2, e - s - 1);
                        let html = "";
                        for (let i = s + 1; i <= s + count; i++) {{
                            let messageHtml = createMessageHtml(allMessages[i], i);
                            messageHtml = messageHtml.replace('class="message', 'class="message context');
                            html += messageHtml;
                        }}
                        let parent = separator.parentNode;
                        let nextSibling = separator.nextSibling;
                        parent.removeChild(separator);
                        let container = document.createElement('div');
                        container.innerHTML = html;
                        while (container.firstChild) {{
                            parent.insertBefore(container.firstChild, nextSibling);
                        }}
                        if (s + count < e - 1) {{
                            let newSeparator = createSeparatorElement(s + count, e, "down");
                            parent.insertBefore(newSeparator, nextSibling);
                        }} else {{
                            parent.removeChild(nextSibling);
                        }}
                    }} else if (separator.dataset.direction === "up") {{
                        let s = parseInt(separator.dataset.start);
                        let e = parseInt(separator.dataset.end);
                        let count = Math.min(2, e - s - 1);
                        let html = "";
                        for (let i = e - count; i < e; i++) {{
                            let messageHtml = createMessageHtml(allMessages[i], i);
                            messageHtml = messageHtml.replace('class="message', 'class="message context');
                            html += messageHtml;
                        }}
                        let parent = separator.parentNode;
                        let nextSibling = separator.nextSibling;
                        var downSeparator = separator.previousElementSibling;

                        parent.removeChild(separator);
                        let container = document.createElement('div');
                        container.innerHTML = html;
                        const topChild = container.firstChild
                        while (container.firstChild) {{
                            parent.insertBefore(container.firstChild, nextSibling);
                        }}
                        if (s + count < e - 1) {{
                            let newSeparator = createSeparatorElement(s, e - count, "up");
                            parent.insertBefore(newSeparator, topChild);
                        }} else {{
                            parent.removeChild(downSeparator);
                        }}
                    }}
                }});
                return separator;
            }}


            // 渲染指定区间内的消息，prepend=true 时将消息插入到最前面
            function renderMessagesRange(start, end, prepend=false) {{
                return new Promise((resolve) => {{
                    let html = "";
                    for (let i = start; i < end; i++) {{
                        html += createMessageHtml(allMessages[i], i);
                    }}
                    if (prepend) {{
                        messagesContainer.insertAdjacentHTML('afterbegin', html);
                    }} else {{
                        messagesContainer.innerHTML += html;
                    }}
                    resolve();
                }});
            }}

            // 初始加载最新的20条消息
            function loadInitialMessages() {{
                let total = allMessages.length;
                currentStartIndex = Math.max(0, total - 20);
                renderMessagesRange(currentStartIndex, total).then(() => {{
                    waitForMediaToLoad().then(() => {{
                        window.scrollTo(0, document.body.scrollHeight);
                    }});
                }});
            }}

            function waitForMediaToLoad() {{
                // 获取所有图片和视频
                const images = Array.from(document.images).map(img => {{
                    if (img.complete) return Promise.resolve();
                    return new Promise(resolve => {{
                        img.addEventListener('load', resolve, {{ once: true }});
                        img.addEventListener('error', resolve, {{ once: true }});
                    }});
                }});

                const videos = Array.from(document.querySelectorAll('video')).map(video => {{
                    // readyState >= 3 表示可以播放（已加载足够数据）
                    if (video.readyState >= 3) return Promise.resolve();
                    return new Promise(resolve => {{
                        video.addEventListener('loadeddata', resolve, {{ once: true }});
                        video.addEventListener('error', resolve, {{ once: true }});
                    }});
                }});
                return Promise.all([...images, ...videos]);
            }}

            // 向上加载更多消息（每次加载20条）
            async function loadOlderMessages() {{
                if (currentStartIndex <= 0) return;
                let newStart = Math.max(0, currentStartIndex - 20);
                await renderMessagesRange(newStart, currentStartIndex, true)
                currentStartIndex = newStart;
            }}

            function loadOlderMessagesWithScrollAdjustment() {{
                // 记录加载前页面的高度和滚动位置
                const prevHeight = document.body.scrollHeight;
                const prevScrollY = window.scrollY;
                loadOlderMessages().then(() => {{
                    // 加载完新内容后，计算新增内容的高度
                    const newHeight = document.body.scrollHeight;
                    const deltaHeight = newHeight - prevHeight;
                    // 调整滚动位置，让用户看到原本的位置
                    window.scrollTo(0, prevScrollY + deltaHeight);
                }});
            }}

            // 当非搜索模式下，滚动到页面顶部时触发加载更多
            let debounceTimer;
            function checkScroll() {{
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(function() {{
                    if (!isSearching && window.scrollY < 50 && currentStartIndex > 0) {{
                        loadOlderMessagesWithScrollAdjustment();
                    }}
                }}, 200);
            }}
            window.addEventListener('scroll', checkScroll);

            // 搜索函数，利用 DocumentFragment 组装 DOM，非连续组之间插入分隔符
            function searchMessages() {{ 
                const searchValue = document.getElementById('searchBox').value.toLowerCase();
                if (!searchValue) {{
                    isSearching = false;
                    messagesContainer.innerHTML = "";
                    loadInitialMessages();
                    return;
                }}
                isSearching = true;
                let matchedIndices = new Set();
                for (let i = 0; i < allMessages.length; i++) {{
                    let dateText = allMessages[i].date.toLowerCase();
                    let msgText = allMessages[i].msg.toLowerCase();
                    let fileName = allMessages[i].msg_file_name.toLowerCase();
                    if (dateText.includes(searchValue) || msgText.includes(searchValue) || fileName.includes(searchValue)) {{
                        matchedIndices.add(i);
                    }}
                }}
                let sortedIndices = Array.from(matchedIndices).sort((a, b) => a - b);
                messagesContainer.innerHTML = "";
                let fragment = document.createDocumentFragment();
                
                if (sortedIndices.length > 0 && sortedIndices[0] > 0) {{
                    let upSeparator = createSeparatorElement(0, sortedIndices[0], "up");
                    fragment.appendChild(upSeparator);
                }}
                
                let lastIndex = null;
                for (let i = 0; i < sortedIndices.length; i++) {{
                    let idx = sortedIndices[i];
                    if (lastIndex !== null && idx !== lastIndex + 1) {{
                        let downSeparator = createSeparatorElement(lastIndex, idx, "down");
                        fragment.appendChild(downSeparator);
                        let upSeparator = createSeparatorElement(lastIndex, idx, "up");
                        fragment.appendChild(upSeparator);
                    }}
                    let tempDiv = document.createElement('div');
                    tempDiv.innerHTML = createMessageHtml(allMessages[idx], idx, searchValue);
                    let messageElement = tempDiv.firstElementChild;
                    fragment.appendChild(messageElement);
                    lastIndex = idx;
                }}
                
                if (lastIndex !== null && lastIndex < allMessages.length - 1) {{
                    let downSeparator = createSeparatorElement(lastIndex, allMessages.length - 1, "down");
                    fragment.appendChild(downSeparator);
                }}
                messagesContainer.appendChild(fragment);
            }}

            document.addEventListener('DOMContentLoaded', loadInitialMessages);

            const confirmSearchBtn = document.getElementById('confirmSearch');
            document.addEventListener('keydown', function(event) {{
                if (event.key === 'Enter') {{
                    confirmSearchBtn.click();
                }}
            }});
        </script>
    </body>
</html>
    """
    return html_content

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

    id = sys.argv[1]

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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, 'data', id)
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    messages_file = os.path.join(data_dir, f'{id}_chat.json')
    messages_file_temp = os.path.join(data_dir, f'{id}_chat_temp.json')

    if not no_export:
        export_chat(
            id, 
            messages_file, 
            messages_file_temp, 
            download_files=download_files, 
            all_messages=all_messages, 
            raw_messages=raw_messages
        )

    data = load_json(messages_file)
    china_timezone = timezone(timedelta(hours=8))
    raw_messages = data["messages"]
    messages = parse_messages(id, raw_messages, china_timezone, script_dir)
    html_content = generate_html(messages)
    
    output_path = os.path.join(script_dir, output_filename)
    save_html(html_content, output_path)
    print(f"Chat log saved to {output_path}")


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

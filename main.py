"""High level chat export handler."""

from datetime import timezone, timedelta
import os

import re
import db_utils
from db_utils import get_connection, save_messages
from update_messages import export_chat
from project_logger import get_logger
from message_utils import load_json, parse_messages
from og_utils import calculate_display_size, get_open_graph_info

script_dir = os.path.dirname(os.path.abspath(__file__))


def handle(chat_id: str, is_download: bool, is_all: bool, is_raw: bool, remark: str | None):
    """Export messages and store them in the database."""
    logger = get_logger(remark or chat_id)
    data_dir = os.path.join(script_dir, 'data', chat_id)
    os.makedirs(data_dir, exist_ok=True)
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
                remark=remark,
            )
        except Exception as e:
            logger.exception(f'Error writing {msg_json_path}: {e}')

        if os.path.exists(msg_json_path):
            try:
                data = load_json(msg_json_path)
                tz = timezone(timedelta(hours=8))
                messages_data = data.get("messages", [])
                # fetch og info and display sizes
                for m in messages_data:
                    links = []
                    if isinstance(m.get("text"), str):
                        links = re.findall(r'(https?://\S+)', m["text"])
                    msg_file = m.get("file", "")
                    msg_file_name = f'downloads/{chat_id}/{chat_id}_{m.get("id")}_{msg_file}' if msg_file else ""
                    og_info = None
                    og_width = og_height = None
                    if links and not msg_file:
                        og_info = get_open_graph_info(links[0], chat_id)
                        if og_info:
                            og_width = og_info.get('width')
                            og_height = og_info.get('height')
                    display_width, display_height = calculate_display_size(msg_file_name, og_width, og_height)
                    m['display_width'] = display_width
                    m['display_height'] = display_height
                    m['og_info'] = og_info
                messages = parse_messages(chat_id, messages_data, tz, remark)
                save_messages(conn, chat_id, messages)
                db_utils.set_last_export_time(conn, db_utils.get_exported_time(conn))
            except Exception as e:
                logger.exception(f'Error parsing {msg_json_path}: {e}')
            finally:
                os.remove(msg_json_path)

        if os.path.exists(msg_json_temp_path):
            os.remove(msg_json_temp_path)

    logger.info(f"Messages data saved to {db_path}")


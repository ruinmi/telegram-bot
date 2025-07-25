"""Utility functions for parsing message data."""

import json
from datetime import datetime
from typing import List, Dict, Any


def load_json(file_path: str) -> dict:
    """Load JSON data from a file."""
    with open(file_path, "r", encoding="utf-8") as infile:
        return json.load(infile)


def convert_timestamp_to_date(timestamp: int, tz) -> str:
    """Convert unix timestamp to formatted date string."""
    return datetime.fromtimestamp(timestamp, tz).strftime('%Y-%m-%d %H:%M:%S')


def compute_msg_files_size(num_files: int, container_width: int = 500, max_per_row: int = 3, gap: int = 5) -> tuple[int, int]:
    """Calculate image width and height for grouped message files."""
    if num_files == 0:
        return 0, 0
    cols = min(num_files, max_per_row)
    total_gap_width = gap * (cols - 1)
    width = (container_width - total_gap_width) // cols
    height = width
    return width, height


def parse_messages(chat_id: str, raw_messages: List[dict], tz, remark: str | None = None) -> List[Dict[str, Any]]:
    from project_logger import get_logger
    logger = get_logger(remark or chat_id)

    messages = []
    group_messages = []
    last_group_id = None

    for raw_message in raw_messages:
        msg_text = raw_message.get("text", "")
        msg_id = raw_message.get("id", None)
        msg_file = raw_message.get("file", "")
        msg_file_name = f'downloads/{chat_id}/{chat_id}_{msg_id}_{msg_file}' if msg_file else ""
        og_info = raw_message.get("og_info")  # may be injected later
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
            'display_height': raw_message.get('display_height'),
            'display_width': raw_message.get('display_width'),
            'og_info': og_info
        }
        group_id = raw_data.get('GroupedID', '')

        if group_id and (group_id == last_group_id or last_group_id is None):
            group_messages.append(message)
            last_group_id = group_id
        else:
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
            group_messages = [message]
            last_group_id = group_id

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

    return sorted(messages, key=lambda x: x['date'])


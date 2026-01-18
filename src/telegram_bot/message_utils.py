"""Utility functions for parsing message data."""

import json
from datetime import datetime
from typing import List, Dict, Any
from bdpan import BaiduPanClient, BaiduPanConfig
import re

from .xunlei_cipher import is_xunlei_link_stale
from .http_client import post as http_post

def load_json(file_path: str) -> dict:
    """Load JSON data from a file."""
    with open(file_path, "r", encoding="utf-8") as infile:
        return json.load(infile)


def convert_timestamp_to_date(timestamp: int, tz) -> str:
    """Convert unix timestamp to formatted date string."""
    return datetime.fromtimestamp(timestamp, tz).strftime('%Y-%m-%d %H:%M:%S')

def is_quark_link_stale(link: str) -> bool:
    """Check if a Quark link is stale."""
    pwd_id = link.split('/s/')[1].split('?')[0]
    
    url = 'https://drive-h.quark.cn/1/clouddrive/share/sharepage/token'
    params = {
        'pr': 'ucpro',
        'fr': 'pc',
        'uc_param_str': '',
        '__dt': 445,
        '__t': int(datetime.now().timestamp() * 1000)
    }
    request_payload = {
        'pwd_id': pwd_id,
        'passcode': '',
        'support_visit_limit_private_share': "true"
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Referer': 'https://pan.quark.cn/',
        'Content-Type': 'application/json'
    }
    resp = http_post(url, params=params, json=request_payload, headers=headers)
    try:
        data = resp.json()
        if int(data.get('code', 0)) == 41011 or int(data.get('code', 0)) == 41012:
            return True
    except Exception as e:
        print(f"Error checking quark link: {e}")
    return False

def is_ali_link_stale(link: str) -> bool:
    """Check if an Ali link is stale."""
    share_id = link.split('/s/')[1].split('?')[0]
    
    url = f'https://api.aliyundrive.com/adrive/v3/share_link/get_share_by_anonymous?share_id={share_id}'
    request_payload = {
        'share_id': share_id,
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Referer': 'https://www.alipan.com/',
        'Content-Type': 'application/json'
    }
    resp = http_post(url, headers=headers, json=request_payload)
    try:
        data = resp.json()
        if 'share_name' not in data:
            return True
    except Exception as e:
        print(f"Error checking ali link: {e}")
    return False

def parse_messages(chat_id: str, raw_messages: List[dict], tz, remark: str | None = None) -> List[Dict[str, Any]]:
    from .project_logger import get_logger
    logger = get_logger(remark or chat_id)

    messages = []
    group_messages = []
    last_group_id = None
    filtered_messages = filter_messages(raw_messages)
    logger.info(f'{len(raw_messages)} messages before filtering, {len(filtered_messages)} after filtering')

    for raw_message in filtered_messages:
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
            'ori_height': raw_message.get('ori_height'),
            'ori_width': raw_message.get('ori_width'),
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
        messages.append(main_msg)

    return sorted(messages, key=lambda x: x['date'])

def filter_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter messages"""
    filtered_messages = []
    
    bdpan = BaiduPanClient(
        config=BaiduPanConfig(
            cookie_file='auth/cookies.txt',
        )
    )
    
    for msg in messages:
        msg_text = msg.get('text', '') or ''
        links = re.findall(r'(https?://\S+)', msg_text)
        if not links:
            filtered_messages.append(msg)
            continue
        
        has_share_link = False
        has_others_link = False
        is_stale = True
        
        for link in links:
            # filter stale pan baidu link messages
            if bdpan.is_share_link(link):
                has_share_link = True
                if not bdpan.is_link_stale(link):
                    is_stale = False
                    break
                
            # filter stale quark links
            elif link.startswith('https://pan.quark.cn'):
                has_share_link = True
                if not is_quark_link_stale(link):
                    is_stale = False
                    break
            
            # filter stale ali links
            elif link.startswith('https://www.alipan.com'):
                has_share_link = True
                if not is_ali_link_stale(link):
                    is_stale = False
                    break
            
            # filter stale xunlei links
            elif link.startswith('https://pan.xunlei.com'):
                has_share_link = True
                if not is_xunlei_link_stale(link):
                    is_stale = False
                    break
            
            else:
                has_others_link = True
        
        if has_share_link:
            if not is_stale:
                filtered_messages.append(msg)
        
        elif has_others_link:
            filtered_messages.append(msg)
                  
            
    return filtered_messages
    

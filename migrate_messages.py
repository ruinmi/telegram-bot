import os
import json
import sys
from main import save_messages_to_db

script_dir = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) != 2:
    print('Usage: python migrate_messages.py <chat_id>')
    sys.exit(1)

chat_id = sys.argv[1]
data_dir = os.path.join(script_dir, 'data', chat_id)
json_path = os.path.join(data_dir, 'messages.json')
db_path = os.path.join(data_dir, 'messages.db')

if not os.path.exists(json_path):
    print(f'No messages.json found for {chat_id}')
    sys.exit(0)

with open(json_path, 'r', encoding='utf-8') as f:
    messages = json.load(f)

if isinstance(messages, dict):
    # in case file was stored as {"messages": [...]} like export output
    messages = messages.get('messages', [])

save_messages_to_db(db_path, chat_id, messages)
os.remove(json_path)
print(f'Migrated {len(messages)} messages to {db_path}')

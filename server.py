import os
import json
from flask import Flask, request, jsonify, send_from_directory, render_template

script_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_url_path='', static_folder=script_dir, template_folder=script_dir)


def load_messages(chat_id):
    path = os.path.join(script_dir, 'data', chat_id, 'messages.json')
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


@app.route('/chat/<chat_id>')
def chat_page(chat_id):
    return render_template('template.html', chat_id=chat_id)


@app.route('/messages/<chat_id>')
def get_messages(chat_id):
    messages = load_messages(chat_id)
    total = len(messages)
    offset = int(request.args.get('offset', 0))
    limit = int(request.args.get('limit', 20))
    if offset < 0:
        offset = max(total + offset, 0)
    end = min(offset + limit, total)
    return jsonify({'total': total, 'offset': offset, 'messages': messages[offset:end]})


@app.route('/search/<chat_id>')
def search_messages(chat_id):
    query = request.args.get('q', '').lower()
    if not query:
        return jsonify([])
    messages = load_messages(chat_id)
    result = []
    for m in messages:
        if (query in m.get('date', '').lower() or
                query in (m.get('msg') or '').lower() or
                query in m.get('msg_file_name', '').lower()):
            result.append(m)
    return jsonify(result)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

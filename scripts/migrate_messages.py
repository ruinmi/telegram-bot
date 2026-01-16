from __future__ import annotations

import json
import sys
from datetime import timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from telegram_bot.db_utils import get_connection, save_messages  # noqa: E402
from telegram_bot.message_utils import parse_messages  # noqa: E402


def _load_messages(json_path: Path) -> list[dict]:
    with json_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, dict):
        payload = payload.get("messages", [])
    if not isinstance(payload, list):
        return []
    return [m for m in payload if isinstance(m, dict)]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python scripts/migrate_messages.py <chat_id>")
        return 1

    chat_id = argv[1]
    data_dir = ROOT / "data" / chat_id
    json_path = data_dir / "messages.json"
    db_path = data_dir / "messages.db"

    if not json_path.exists():
        print(f"No messages.json found for {chat_id}")
        return 0

    raw_messages = _load_messages(json_path)
    tz = timezone(timedelta(hours=8))

    # Try best-effort parsing when input is in tdl export-like format.
    should_parse = bool(raw_messages) and ("raw" in raw_messages[0] or "id" in raw_messages[0])
    messages = parse_messages(chat_id, raw_messages, tz) if should_parse else raw_messages

    with get_connection(chat_id) as conn:
        save_messages(conn, chat_id, messages)

    json_path.unlink(missing_ok=True)
    print(f"Migrated {len(messages)} messages to {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))


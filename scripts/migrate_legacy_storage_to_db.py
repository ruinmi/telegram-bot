from __future__ import annotations

import json
from pathlib import Path

from telegram_bot.db_utils import get_app_connection, set_me_id, set_og_cache, upsert_chat


ROOT = Path(__file__).resolve().parents[1]


def _load_json_file(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as infile:
        return json.load(infile)


def migrate_legacy_storage(
    *,
    app_db_path: Path | str | None = None,
    chats_file: Path | str | None = None,
    me_id_file: Path | str | None = None,
    og_data_file: Path | str | None = None,
) -> dict:
    app_db_path = Path(app_db_path) if app_db_path else ROOT / "data" / "app.db"
    chats_file = Path(chats_file) if chats_file else ROOT / "chats.json"
    me_id_file = Path(me_id_file) if me_id_file else ROOT / "me_id.txt"
    og_data_file = Path(og_data_file) if og_data_file else ROOT / "data" / "og_data.json"

    from telegram_bot import db_utils

    db_utils.APP_DB_PATH = app_db_path

    summary = {
        "app_db_path": str(app_db_path),
        "migrated_chats": 0,
        "migrated_me_id": False,
        "migrated_og_entries": 0,
    }

    conn = get_app_connection()
    try:
        chats_data = _load_json_file(chats_file)
        if isinstance(chats_data, list):
            for item in chats_data:
                if isinstance(item, dict) and (item.get("id") or item.get("chat_id")):
                    upsert_chat(conn, item)
                    summary["migrated_chats"] += 1

        if me_id_file.exists():
            me_id = me_id_file.read_text(encoding="utf-8").strip()
            if me_id:
                set_me_id(conn, me_id)
                summary["migrated_me_id"] = True

        og_data = _load_json_file(og_data_file)
        if isinstance(og_data, dict):
            for url, value in og_data.items():
                set_og_cache(conn, str(url), value if isinstance(value, dict) else {})
                summary["migrated_og_entries"] += 1
    finally:
        conn.close()

    return summary


def main() -> int:
    summary = migrate_legacy_storage()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

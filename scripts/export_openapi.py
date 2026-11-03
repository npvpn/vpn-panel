"""Выгрузить актуальную OpenAPI-схему панели.

Импорт приложения не запускает планировщик: он стартует только на событии startup.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Схеме база не нужна. Фиксируем пустую sqlite до импорта config, чтобы не
# открыть боевой URL из .env и не создать db.sqlite3 в каталоге репозитория.
os.environ["SQLALCHEMY_DATABASE_URL"] = "sqlite://"


def main() -> None:
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    from app import app

    schema = app.openapi()
    destination.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {destination} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()

"""Write the API contract to docs/architecture/openapi.json.

Run from backend/:  uv run python -m scripts.export_openapi
No database connection is made; the engine is created lazily.
"""

import json
from pathlib import Path

from app.config import Settings
from app.main import create_app

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "openapi.json"


def main() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        environment="dev",
    )
    schema = create_app(settings).openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()

"""Exports the FastAPI app's OpenAPI schema to /shared/openapi.json — the source `web`
generates its TS types from (specs/02-architecture.md: "OpenAPI schema is the contract").
No running server needed; imports the app object directly.

Usage: `python -m scripts.export_openapi` (run from /api with the venv active).
"""

import json
from pathlib import Path

from app.main import app

OUTPUT_PATH = Path(__file__).resolve().parents[2] / "shared" / "openapi.json"


def export_openapi() -> None:
    schema = app.openapi()
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"Wrote OpenAPI schema to {OUTPUT_PATH}")


if __name__ == "__main__":
    export_openapi()

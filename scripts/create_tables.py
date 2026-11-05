"""Create the Component 5 DynamoDB table (idempotent).

Run:  AWS_PROFILE=breaking-barriers-ny .venv/Scripts/python.exe scripts/create_tables.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable regardless of where the script is run from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from external_data import access  # noqa: E402


def main() -> None:
    access.ensure_table()


if __name__ == "__main__":
    main()

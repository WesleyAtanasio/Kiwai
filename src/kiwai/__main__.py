"""Small stdlib-only CLI for inspecting Kiwai databases."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from .store import SQLiteStore


def _format_time(value: float | None) -> str | None:
    return None if value is None else datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")


def _record_dict(record: Any) -> dict[str, Any]:
    data = asdict(record)
    data["status"] = record.status.value
    for field in ("created_at", "updated_at", "completed_at", "expires_at", "lease_expires_at"):
        data[field] = _format_time(data[field])
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kiwai", description="Inspect and maintain a Kiwai SQLite database.")
    parser.add_argument("--db", default=".kiwai.db", help="Path to the SQLite database.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List recent operations.")
    list_parser.add_argument("--status", choices=("running", "succeeded", "failed"))
    list_parser.add_argument("--limit", type=int, default=50)

    show_parser = subparsers.add_parser("show", help="Show one operation.")
    show_parser.add_argument("key")

    delete_parser = subparsers.add_parser("delete", help="Delete one operation key.")
    delete_parser.add_argument("key")

    subparsers.add_parser("purge", help="Delete expired and failed operations.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    store = SQLiteStore(args.db)

    if args.command == "list":
        records = store.list(status=args.status, limit=args.limit)
        print(json.dumps([_record_dict(record) for record in records], indent=2, ensure_ascii=False))
        return 0
    if args.command == "show":
        record = store.get(args.key)
        if record is None:
            print(f"No operation found for key: {args.key}")
            return 1
        print(json.dumps(_record_dict(record), indent=2, ensure_ascii=False))
        return 0
    if args.command == "delete":
        deleted = store.delete(args.key)
        print("deleted" if deleted else "not found")
        return 0 if deleted else 1
    if args.command == "purge":
        print(store.purge())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

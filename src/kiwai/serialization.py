"""Deterministic payload hashing and result serialization."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from .errors import ResultSerializationError


def _normalize(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _normalize(dataclasses.asdict(value))
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (Path, UUID, Decimal)):
        return str(value)
    if isinstance(value, bytes):
        return {"__bytes_sha256__": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, set | frozenset):
        normalized = [_normalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"__type__": f"{type(value).__module__}.{type(value).__qualname__}", "repr": repr(value)}


def canonical_json(value: Any) -> str:
    return json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_digest(function_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    payload = {"function": function_name, "args": args, "kwargs": kwargs}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def dumps_result(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ResultSerializationError(
            "The function result is not JSON serializable. Set cache_result=False or return a JSON-compatible value."
        ) from exc


def loads_result(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)

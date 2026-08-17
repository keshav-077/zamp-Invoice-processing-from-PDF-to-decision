"""Convert pandas/numpy values to JSON-serializable Python types."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def json_safe(value: Any) -> Any:
    """Recursively replace NaN/Inf and numpy scalars for API JSON responses."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, (int, str, bool)):
        return value

    # numpy/pandas scalar types
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except (ValueError, AttributeError):
            pass

    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]

    return str(value)


def records_json_safe(records: list[dict]) -> list[dict]:
    return [json_safe(row) for row in records]


def to_native_number(value: Any) -> float | None:
    """Coerce numpy/opencv scalars to plain float for Postgres query params."""
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def model_dump_json_safe(model: Any) -> str | None:
    """Pydantic model → JSON string with no numpy/pandas scalars."""
    if model is None:
        return None
    import json

    return json.dumps(json_safe(model.model_dump(mode="json")))

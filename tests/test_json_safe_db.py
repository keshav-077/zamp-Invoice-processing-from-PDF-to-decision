"""Postgres param safety — numpy scalars must not reach psycopg2."""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.services.json_safe import json_safe, model_dump_json_safe, to_native_number


def test_to_native_number_from_numpy_float64():
    assert to_native_number(np.float64(0.873)) == pytest.approx(0.873)
    assert isinstance(to_native_number(np.float64(1.0)), float)


def test_json_safe_strips_numpy_in_nested_dict():
    payload = {"residual_amount": np.float64(12.5), "tags": [np.int64(1)]}
    cleaned = json_safe(payload)
    assert cleaned == {"residual_amount": 12.5, "tags": [1]}
    # Must round-trip through json.dumps for Postgres TEXT columns
    json.dumps(cleaned)


def test_model_dump_json_safe_no_numpy_literals():
    from app.models.reconciliation import ReconciliationResult

    result = ReconciliationResult(
        overall_status="partial",
        checks=[],
        residual_amount=float(np.float64(0.0)),
    )
    raw = model_dump_json_safe(result)
    assert raw is not None
    assert "np.float64" not in raw
    assert "float64" not in raw

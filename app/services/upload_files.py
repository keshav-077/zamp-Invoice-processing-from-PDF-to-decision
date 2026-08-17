"""Shared upload filename / parsing helpers for master data import."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd

SUPPORTED_UPLOAD_EXTENSIONS = (".csv", ".xlsx", ".xls")


def resolve_upload_extension(filename: str) -> str:
    """Return the best-matching supported extension (handles names like file.csv.xlsx)."""
    lower = filename.lower()
    for ext in (".xlsx", ".xls", ".csv"):
        if lower.endswith(ext):
            return ext
    return Path(filename).suffix.lower()


def parse_upload_workbook(content: bytes, filename: str) -> dict[str, pd.DataFrame]:
    """Parse CSV/XLSX bytes into sheet-name → DataFrame map."""
    ext = resolve_upload_extension(filename)
    if ext in (".xlsx", ".xls"):
        try:
            xl = pd.ExcelFile(io.BytesIO(content))
            return {
                re.sub(r"\s+", "_", name.strip().lower()): xl.parse(name)
                for name in xl.sheet_names
            }
        except Exception as exc:
            # Some exports are CSV content saved with an Excel extension.
            try:
                return {"data": pd.read_csv(io.BytesIO(content))}
            except Exception:
                raise ValueError(
                    f"Could not read {filename} as Excel or CSV: {exc}"
                ) from exc
    if ext == ".csv":
        return {"data": pd.read_csv(io.BytesIO(content))}
    raise ValueError(
        f"Unsupported file type {ext!r}. Supported: {', '.join(SUPPORTED_UPLOAD_EXTENSIONS)}"
    )

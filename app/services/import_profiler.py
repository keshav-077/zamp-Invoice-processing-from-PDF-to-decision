"""Detect entity shapes and sheet types from arbitrary CSV/XLSX uploads."""

from __future__ import annotations

import hashlib
import io
import re
from typing import Any

import pandas as pd

from app.pipeline.policy_loader import load_import_mapping
from app.services.json_safe import json_safe, records_json_safe


def file_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def source_fingerprint(sheets: dict[str, pd.DataFrame]) -> str:
    parts = []
    for name in sorted(sheets.keys()):
        df = sheets[name]
        cols = "|".join(str(c).strip().lower() for c in df.columns)
        parts.append(f"{name}:{cols}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def normalize_header(name: str) -> str:
    return re.sub(r"\s+", "_", str(name).strip().lower())


def parse_workbook(content: bytes, filename: str) -> dict[str, pd.DataFrame]:
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext in ("xlsx", "xls"):
        xl = pd.ExcelFile(io.BytesIO(content))
        return {
            re.sub(r"\s+", "_", name.strip().lower()): xl.parse(name)
            for name in xl.sheet_names
        }
    if ext == "csv":
        return {"data": pd.read_csv(io.BytesIO(content))}
    raise ValueError(f"Unsupported file type: .{ext}")


def infer_entity_from_sheet(sheet_key: str, columns: list[str]) -> str | None:
    cfg = load_import_mapping()
    hints = cfg.get("sheet_hints", {})

    # Exact sheet name match (preferred)
    for entity, names in hints.items():
        if sheet_key in names:
            return entity

    # Substring match for longer hints only — avoids matching "po" inside "polines"
    for entity, names in hints.items():
        if any(len(h) >= 4 and h in sheet_key for h in names):
            return entity

    norm_cols = {normalize_header(c) for c in columns}
    entity_fields = cfg.get("entities", {})
    scores: dict[str, int] = {}
    for entity, spec in entity_fields.items():
        fields = spec.get("fields", {})
        score = 0
        for aliases in fields.values():
            if any(normalize_header(a) in norm_cols for a in aliases):
                score += 1
        if score:
            scores[entity] = score
    if not scores:
        return None
    return max(scores, key=scores.get)


def infer_entity_from_flat_row(row: dict[str, Any]) -> str | None:
    cfg = load_import_mapping()
    record_type = normalize_header(str(row.get("record_type", "")))
    flat = cfg.get("flat_record_types", {})
    for entity, aliases in flat.items():
        if record_type in aliases:
            return entity
    return None


def profile_workbook(content: bytes, filename: str) -> dict:
    sheets = parse_workbook(content, filename)
    profiled: list[dict] = []
    flat_mode = False

    if len(sheets) == 1 and "data" in sheets:
        df = sheets["data"]
        cols_lower = [normalize_header(c) for c in df.columns]
        if "record_type" in cols_lower:
            flat_mode = True
            df.columns = cols_lower
            for entity in load_import_mapping().get("flat_record_types", {}):
                subset = df[df["record_type"].astype(str).str.lower().isin(
                    load_import_mapping()["flat_record_types"][entity]
                )]
                if not subset.empty:
                    profiled.append(
                        {
                            "sheet": "data",
                            "entity": entity,
                            "row_count": len(subset),
                            "columns": list(subset.columns),
                            "sample_rows": records_json_safe(subset.head(3).to_dict(orient="records")),
                        }
                    )
        else:
            entity = infer_entity_from_sheet("data", list(df.columns))
            profiled.append(
                {
                    "sheet": "data",
                    "entity": entity or "unknown",
                    "row_count": len(df),
                    "columns": list(df.columns),
                    "sample_rows": records_json_safe(df.head(3).to_dict(orient="records")),
                }
            )
    else:
        for sheet_key, df in sheets.items():
            entity = infer_entity_from_sheet(sheet_key, list(df.columns))
            profiled.append(
                {
                    "sheet": sheet_key,
                    "entity": entity or "unknown",
                    "row_count": len(df),
                    "columns": [str(c) for c in df.columns],
                    "sample_rows": records_json_safe(df.head(3).to_dict(orient="records")),
                }
            )

    return {
        "filename": filename,
        "checksum": file_checksum(content),
        "source_fingerprint": source_fingerprint(sheets),
        "flat_mode": flat_mode,
        "sheets": profiled,
        "raw_sheet_names": list(sheets.keys()),
    }

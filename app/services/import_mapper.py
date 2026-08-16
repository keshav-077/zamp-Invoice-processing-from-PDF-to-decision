"""Column mapping with confidence scoring and reusable profiles."""

from __future__ import annotations

import json
from typing import Any

from app.db import repository
from app.pipeline.policy_loader import load_import_mapping
from app.services.import_profiler import normalize_header


def _score_column(header: str, aliases: list[str]) -> float:
    norm = normalize_header(header)
    if norm in [normalize_header(a) for a in aliases]:
        return 1.0
    for alias in aliases:
        an = normalize_header(alias)
        if an in norm or norm in an:
            return 0.75
    return 0.0


def propose_column_mappings(
    entity: str,
    columns: list[str],
    saved_profile: dict | None = None,
) -> list[dict]:
    cfg = load_import_mapping()
    thresholds = cfg.get("confidence", {})
    auto_accept = float(thresholds.get("auto_accept", 0.85))
    review_below = float(thresholds.get("review_below", 0.55))

    entity_spec = cfg.get("entities", {}).get(entity, {})
    fields = entity_spec.get("fields", {})
    saved_map = (saved_profile or {}).get("column_map", {}).get(entity, {})

    proposals: list[dict] = []
    used_canonical: set[str] = set()

    for col in columns:
        norm_col = normalize_header(col)
        if saved_map.get(norm_col):
            canonical = saved_map[norm_col]
            proposals.append(
                {
                    "source_column": col,
                    "canonical_field": canonical,
                    "confidence": 1.0,
                    "status": "profile",
                    "reason": "Saved mapping profile",
                }
            )
            used_canonical.add(canonical)
            continue

        best_field = None
        best_score = 0.0
        for canonical, aliases in fields.items():
            if canonical in used_canonical:
                continue
            score = _score_column(col, aliases)
            if score > best_score:
                best_score = score
                best_field = canonical

        if best_field and best_score >= review_below:
            status = "auto" if best_score >= auto_accept else "review"
            proposals.append(
                {
                    "source_column": col,
                    "canonical_field": best_field,
                    "confidence": round(best_score, 2),
                    "status": status,
                    "reason": f"Alias match ({best_score:.0f}%)",
                }
            )
            used_canonical.add(best_field)
        else:
            proposals.append(
                {
                    "source_column": col,
                    "canonical_field": None,
                    "confidence": 0.0,
                    "status": "metadata",
                    "reason": "Preserved as custom metadata",
                }
            )

    return proposals


def apply_mappings(row: dict[str, Any], mappings: list[dict]) -> tuple[dict, dict]:
    canonical: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    mapping_by_col = {m["source_column"]: m for m in mappings}

    for key, value in row.items():
        if value is None or (isinstance(value, float) and str(value) == "nan"):
            continue
        mapping = mapping_by_col.get(key) or mapping_by_col.get(normalize_header(key))
        if mapping and mapping.get("canonical_field"):
            canonical[mapping["canonical_field"]] = value
        else:
            metadata[key] = value
    return canonical, metadata


def load_profile(company_id: str, source_fingerprint: str) -> dict | None:
    return repository.get_mapping_profile(company_id, source_fingerprint)


def save_profile(
    company_id: str,
    source_fingerprint: str,
    column_map: dict,
    confirmed_by: str = "system",
) -> None:
    repository.save_mapping_profile(
        company_id=company_id,
        source_fingerprint=source_fingerprint,
        profile_json=json.dumps({"column_map": column_map}),
        confirmed_by=confirmed_by,
    )

"""Load ExplanationSnapshot records from persisted DB rows."""

from __future__ import annotations

import json
from typing import Any

from app.models.explanation import (
    ControlVerification,
    EvidenceGap,
    ExplanationSnapshot,
    NarrativeEntry,
    UpstreamArtifact,
)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def snapshot_from_explanation_row(row: dict, document_id: str) -> ExplanationSnapshot:
    """Reconstruct a full ExplanationSnapshot from an explanation_snapshots row."""
    snapshot_data = row.get("snapshot_json")
    if isinstance(snapshot_data, str):
        snapshot_data = _as_dict(snapshot_data)
    if isinstance(snapshot_data, dict) and snapshot_data.get("explanation_id"):
        try:
            return ExplanationSnapshot.model_validate(snapshot_data)
        except Exception:
            pass

    narrative_raw = row.get("narrative_json") or []
    narrative = [
        NarrativeEntry.model_validate(item)
        for item in _as_list(narrative_raw)
        if isinstance(item, dict)
    ]

    gaps_raw = row.get("gaps_json") or []
    gaps = [
        EvidenceGap.model_validate(item)
        for item in _as_list(gaps_raw)
        if isinstance(item, dict)
    ]

    controls_raw = row.get("control_verification_json") or []
    controls = [
        ControlVerification.model_validate(item)
        for item in _as_list(controls_raw)
        if isinstance(item, dict)
    ]

    artifacts_raw = row.get("upstream_artifacts_json") or []
    artifacts = [
        UpstreamArtifact.model_validate(item)
        for item in _as_list(artifacts_raw)
        if isinstance(item, dict)
    ]

    return ExplanationSnapshot(
        explanation_id=row.get("explanation_id", ""),
        tenant_id=row.get("tenant_id", "TENANT-DEFAULT"),
        decision_id=row.get("decision_id", ""),
        invoice_id=document_id,
        validation_run_id=row.get("validation_run_id", ""),
        explanation_status=row.get("explanation_status", "COMPLETE"),
        policy_version=row.get("policy_version", ""),
        policy_hash=row.get("policy_hash", ""),
        decision_outcome=row.get("decision_outcome", ""),
        decision_substate=row.get("decision_substate", ""),
        upstream_artifacts=artifacts,
        narrative=narrative,
        rule_trace_summary=_as_list(row.get("rule_trace_json")),
        routing=_as_dict(row.get("routing_json")),
        authority=_as_dict(row.get("authority_json")),
        control_verifications=controls,
        evidence_refs=_as_list(row.get("evidence_refs_json")),
        evidence_summary=_as_list(row.get("evidence_summary_json")),
        gaps=gaps,
        generated_at=row.get("generated_at", ""),
        processing_time_seconds=float(row.get("processing_time_seconds") or 0),
    )

"""
InvoiceFlow AI — Stage 5: Evidence Resolver

Resolves immutable upstream artifact references from Stages 1–4.
Records artifact_id, version, and SHA-256 content hash.
Missing artifacts become explicit EvidenceGap entries.

PRD Section 7: Historical reconstruction must not depend on
the current contents of an upstream service.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field

from app.db import repository
from app.models.decision import DecisionRecord
from app.models.explanation import UpstreamArtifact, EvidenceGap

logger = logging.getLogger(__name__)


@dataclass
class EvidenceResolution:
    """Result of resolving all upstream artifacts."""
    artifacts: list[UpstreamArtifact] = field(default_factory=list)
    gaps: list[EvidenceGap] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class UpstreamEvidenceContext:
    """
    In-memory pipeline artifacts available before invoice_runs is persisted.

    Stage 5 runs inside the live pipeline before save_run(), so extraction and
    stage2_result_json may only exist in memory. Validation is persisted by
    Stage 3 but can also be passed here for consistency.
    """
    extraction: dict | None = None
    match_package: dict | None = None
    validation_report: dict | None = None


def artifact_to_dict(value) -> dict | None:
    """Normalize pydantic models, dicts, or JSON strings to a dict."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _hash_content(content: str) -> str:
    """Compute SHA-256 hash of content."""
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]}"


def _resolve_extraction(
    document_id: str,
    context: UpstreamEvidenceContext | None,
) -> dict | None:
    """Resolve Stage 1 extraction from in-memory context or persisted run."""
    if context and context.extraction:
        return context.extraction
    run = repository.get_run(document_id)
    if run and run.get("extraction_json"):
        return artifact_to_dict(run["extraction_json"])
    return None


def _resolve_match_package(
    document_id: str,
    context: UpstreamEvidenceContext | None,
) -> dict | None:
    """Resolve Stage 2 match from in-memory context, run row, or po_match_results."""
    if context and context.match_package:
        return context.match_package
    run = repository.get_run(document_id)
    if run and run.get("stage2_result_json"):
        return artifact_to_dict(run["stage2_result_json"])
    match_row = repository.get_match_result(document_id)
    if match_row and match_row.get("match_package_json"):
        return artifact_to_dict(match_row["match_package_json"])
    return None


def _resolve_validation_report(
    document_id: str,
    decision_record: DecisionRecord,
    context: UpstreamEvidenceContext | None,
) -> dict | None:
    """Resolve Stage 3 validation from in-memory context or validation_runs."""
    if context and context.validation_report:
        return context.validation_report
    validation_history = repository.get_validation_history(document_id)
    if not validation_history:
        return None
    target_id = decision_record.validation_run_id
    if target_id:
        for entry in validation_history:
            if entry.get("validation_run_id") == target_id:
                return entry
    return validation_history[0]


def resolve_evidence(
    document_id: str,
    decision_record: DecisionRecord,
    *,
    context: UpstreamEvidenceContext | None = None,
) -> EvidenceResolution:
    """
    Resolve all upstream artifacts for Stages 1-4.

    Missing artifacts produce explicit gaps, never guessed values.

    Args:
        document_id: Invoice document ID
        decision_record: Stage 4 decision record
        context: Optional in-memory artifacts from the live pipeline

    Returns:
        EvidenceResolution with artifacts, gaps, and evidence refs.
    """
    resolution = EvidenceResolution()

    # --- Stage 1: Extraction ---
    try:
        extraction_data = _resolve_extraction(document_id, context)
        if extraction_data:
            content = json.dumps(extraction_data, sort_keys=True)
            resolution.artifacts.append(UpstreamArtifact(
                stage=1,
                artifact_id=document_id,
                artifact_type="extraction",
                artifact_version="stage1",
                artifact_hash=_hash_content(content),
                resolved=True,
            ))
            resolution.evidence_refs.append(f"stage1:extraction:{document_id}")
        else:
            resolution.gaps.append(EvidenceGap(
                stage=1,
                artifact_type="extraction",
                reason="Extraction data not found in database",
                impact="Cannot verify extracted field values",
            ))
    except Exception as e:
        resolution.gaps.append(EvidenceGap(
            stage=1,
            artifact_type="extraction",
            reason=f"Error resolving: {e}",
            impact="Stage 1 evidence unavailable",
        ))

    # --- Stage 2: Match ---
    try:
        match_data = _resolve_match_package(document_id, context)
        if match_data:
            content = json.dumps(match_data, sort_keys=True)
            resolution.artifacts.append(UpstreamArtifact(
                stage=2,
                artifact_id=document_id,
                artifact_type="po_match",
                artifact_version="stage2",
                artifact_hash=_hash_content(content),
                resolved=True,
            ))
            resolution.evidence_refs.append(f"stage2:po_match:{document_id}")
        else:
            resolution.gaps.append(EvidenceGap(
                stage=2,
                artifact_type="po_match",
                reason="PO match data not found",
                impact="Cannot verify PO matching evidence",
            ))
    except Exception as e:
        resolution.gaps.append(EvidenceGap(
            stage=2,
            artifact_type="po_match",
            reason=f"Error resolving: {e}",
            impact="Stage 2 evidence unavailable",
        ))

    # --- Stage 3: Validation ---
    try:
        validation_data = _resolve_validation_report(document_id, decision_record, context)
        if validation_data:
            vr_id = validation_data.get("validation_run_id", decision_record.validation_run_id)
            content = json.dumps(validation_data, sort_keys=True)
            resolution.artifacts.append(UpstreamArtifact(
                stage=3,
                artifact_id=vr_id,
                artifact_type="validation_report",
                artifact_version=decision_record.validation_run_id,
                artifact_hash=_hash_content(content),
                resolved=True,
            ))
            resolution.evidence_refs.append(f"stage3:validation:{vr_id}")
        else:
            resolution.gaps.append(EvidenceGap(
                stage=3,
                artifact_type="validation_report",
                reason="Validation report not found",
                impact="Cannot verify validation findings",
            ))
    except Exception as e:
        resolution.gaps.append(EvidenceGap(
            stage=3,
            artifact_type="validation_report",
            reason=f"Error resolving: {e}",
            impact="Stage 3 evidence unavailable",
        ))

    # --- Stage 4: Decision ---
    try:
        content = decision_record.model_dump_json()
        resolution.artifacts.append(UpstreamArtifact(
            stage=4,
            artifact_id=decision_record.decision_id,
            artifact_type="decision_record",
            artifact_version=decision_record.engine_version,
            artifact_hash=_hash_content(content),
            resolved=True,
        ))
        resolution.evidence_refs.append(f"stage4:decision:{decision_record.decision_id}")
    except Exception as e:
        resolution.gaps.append(EvidenceGap(
            stage=4,
            artifact_type="decision_record",
            reason=f"Error resolving: {e}",
            impact="Stage 4 evidence unavailable",
        ))

    # Add Stage 4 evidence refs
    resolution.evidence_refs.extend(decision_record.evidence_refs)

    logger.info(
        f"[{document_id}] Evidence resolved: "
        f"{len(resolution.artifacts)} artifacts, {len(resolution.gaps)} gaps"
    )
    return resolution

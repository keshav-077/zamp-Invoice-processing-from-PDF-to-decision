"""
InvoiceFlow AI — Stage 5: Explanation Orchestrator

Chains the complete 10-step explanation pipeline:
  1. Ingest DecisionRecord (schema validate)
  2. Idempotency check (dedup by decision_id)
  3. Resolve upstream evidence (Stage 1-4 artifacts)
  4. Validate provenance + policy references
  5. Build deterministic narrative from rule_trace
  6. Attach routing/authority/SLA
  7. Run control verification
  8. Run completeness gate
  9. Persist Explanation Snapshot
  10. Append audit ledger entry (hash-chained)

Primary invariant: Stage 5 explains and proves; it never decides.
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone

from app.models.decision import DecisionRecord
from app.models.explanation import (
    ExplanationSnapshot, IntegrityProof, UpstreamArtifact,
)
from app.db import repository
from app.pipeline.stage5.evidence_resolver import resolve_evidence, UpstreamEvidenceContext, artifact_to_dict
from app.pipeline.stage5.narrative_builder import build_narrative
from app.pipeline.stage5.completeness_gate import validate_completeness
from app.pipeline.stage5.control_verifier import verify_controls
from app.pipeline.stage5.audit_ledger import append_explanation_audit, compute_content_hash

logger = logging.getLogger(__name__)


class Stage5Orchestrator:
    """Orchestrates the complete Stage 5 Explanation pipeline."""

    def __init__(self, tenant_id: str = "TENANT-DEFAULT"):
        self.tenant_id = tenant_id

    def explain(
        self,
        document_id: str,
        decision_record: DecisionRecord,
        *,
        extraction=None,
        match_package=None,
        validation_report=None,
    ) -> ExplanationSnapshot:
        """
        Run the complete Stage 5 explanation pipeline.

        Args:
            document_id: Invoice document ID
            decision_record: Stage 4 DecisionRecord
            extraction: Optional in-memory Stage 1 extraction (before save_run)
            match_package: Optional in-memory Stage 2 match package
            validation_report: Optional in-memory Stage 3 validation report

        Returns:
            ExplanationSnapshot — the canonical explanation record.
        """
        start_time = time.time()
        generated_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"[{document_id}] Stage 5: Starting explanation pipeline")

        # ── Step 1: Validate input ──
        if not decision_record or not decision_record.decision_id:
            logger.error(f"[{document_id}] Stage 5: Invalid decision record")
            return self._error_snapshot(document_id, "Invalid decision record", start_time)

        # ── Step 2: Idempotency check ──
        existing = repository.get_explanation_by_decision(decision_record.decision_id)
        if existing:
            logger.info(
                f"[{document_id}] Stage 5: Explanation already exists "
                f"for decision {decision_record.decision_id} — returning existing"
            )
            # Return existing snapshot as ExplanationSnapshot
            return ExplanationSnapshot(
                explanation_id=existing.get("explanation_id", ""),
                decision_id=decision_record.decision_id,
                invoice_id=document_id,
                explanation_status=existing.get("explanation_status", "COMPLETE"),
                generated_at=existing.get("generated_at", generated_at),
            )

        # ── Step 3: Resolve upstream evidence ──
        logger.info(f"[{document_id}] Step 3: Evidence resolution")
        context = None
        if extraction is not None or match_package is not None or validation_report is not None:
            context = UpstreamEvidenceContext(
                extraction=artifact_to_dict(extraction),
                match_package=artifact_to_dict(match_package),
                validation_report=artifact_to_dict(validation_report),
            )
        evidence = resolve_evidence(document_id, decision_record, context=context)

        # ── Step 4: Policy references ──
        policy_version = decision_record.trace.policy.policy_version
        policy_hash = compute_content_hash(
            json.dumps(decision_record.trace.policy.model_dump())
        )

        # ── Step 5: Build deterministic narrative ──
        logger.info(f"[{document_id}] Step 5: Narrative builder")
        narrative = build_narrative(decision_record)

        # ── Step 6: Build rule trace summary ──
        rule_trace_summary = [
            {
                "rule_id": r.rule_id,
                "result": r.result,
                "priority": r.priority,
                "detail": r.detail,
            }
            for r in decision_record.trace.rules_evaluated
        ]

        # ── Step 7: Control verification ──
        logger.info(f"[{document_id}] Step 7: Control verification")
        exp = repository.get_explanation(document_id)
        human_actions = (exp or {}).get("human_actions_json") or []
        control_verifications = verify_controls(decision_record, human_actions=human_actions)

        # ── Build snapshot ──
        snapshot = ExplanationSnapshot(
            tenant_id=self.tenant_id,
            decision_id=decision_record.decision_id,
            invoice_id=document_id,
            validation_run_id=decision_record.validation_run_id,
            policy_version=policy_version,
            policy_hash=policy_hash,
            decision_outcome=decision_record.decision,
            decision_substate=decision_record.decision_substate,
            upstream_artifacts=evidence.artifacts,
            narrative=narrative,
            rule_trace_summary=rule_trace_summary,
            routing=decision_record.trace.routing.model_dump(),
            authority=decision_record.trace.authority.model_dump(),
            control_verifications=control_verifications,
            evidence_refs=evidence.evidence_refs,
            evidence_summary=list(decision_record.evidence_summary),
            gaps=evidence.gaps,
            generated_at=generated_at,
        )

        # ── Step 8: Completeness gate ──
        logger.info(f"[{document_id}] Step 8: Completeness gate")
        completeness = validate_completeness(snapshot)
        if completeness.is_complete:
            snapshot.explanation_status = "COMPLETE"
        else:
            snapshot.explanation_status = "INCOMPLETE"
            snapshot.gaps.extend(completeness.gaps)

        # ── Compute integrity proof ──
        snapshot_json = snapshot.model_dump_json()
        content_hash = compute_content_hash(snapshot_json)
        previous_hash = repository.get_last_audit_hash()

        snapshot.integrity = IntegrityProof(
            content_hash=content_hash,
            previous_hash=previous_hash,
        )

        snapshot.processing_time_seconds = round(time.time() - start_time, 2)

        # ── Step 9: Persist ──
        logger.info(f"[{document_id}] Step 9: Persist explanation")
        self._persist_snapshot(snapshot)

        # ── Step 10: Audit ledger ──
        logger.info(f"[{document_id}] Step 10: Audit ledger")
        try:
            ledger_seq = append_explanation_audit(
                explanation_id=snapshot.explanation_id,
                decision_id=snapshot.decision_id,
                invoice_id=snapshot.invoice_id,
                explanation_json=snapshot_json,
                tenant_id=self.tenant_id,
            )
            snapshot.integrity.ledger_sequence = ledger_seq
        except Exception as e:
            logger.error(f"[{document_id}] Audit ledger error: {e}", exc_info=True)

        logger.info(
            f"[{document_id}] Stage 5 complete: {snapshot.explanation_status} "
            f"({snapshot.processing_time_seconds}s)"
        )
        return snapshot

    def _persist_snapshot(self, snapshot: ExplanationSnapshot) -> None:
        """Persist the explanation snapshot to the database."""
        try:
            repository.save_explanation(
                explanation_id=snapshot.explanation_id,
                tenant_id=snapshot.tenant_id,
                decision_id=snapshot.decision_id,
                invoice_id=snapshot.invoice_id,
                explanation_status=snapshot.explanation_status,
                snapshot_json=snapshot.model_dump_json(),
                generated_at=snapshot.generated_at,
                narrative_json=json.dumps([n.model_dump() for n in snapshot.narrative]),
                rule_trace_json=json.dumps(snapshot.rule_trace_summary),
                routing_json=json.dumps(snapshot.routing),
                authority_json=json.dumps(snapshot.authority),
                control_verification_json=json.dumps(
                    [c.model_dump() for c in snapshot.control_verifications]
                ),
                evidence_refs_json=json.dumps(snapshot.evidence_refs),
                evidence_summary_json=json.dumps(snapshot.evidence_summary),
                gaps_json=json.dumps([g.model_dump() for g in snapshot.gaps]),
                upstream_artifacts_json=json.dumps(
                    [a.model_dump() for a in snapshot.upstream_artifacts]
                ),
                policy_version=snapshot.policy_version,
                policy_hash=snapshot.policy_hash,
                decision_outcome=snapshot.decision_outcome,
                decision_substate=snapshot.decision_substate,
                integrity_json=snapshot.integrity.model_dump_json(),
                sampling_json=snapshot.sampling_audit.model_dump_json(),
                engine_version=snapshot.engine_version,
                processing_time_seconds=snapshot.processing_time_seconds,
            )
        except Exception as e:
            logger.error(f"Failed to persist explanation: {e}", exc_info=True)

    def _error_snapshot(
        self, document_id: str, reason: str, start_time: float
    ) -> ExplanationSnapshot:
        """Create an INCOMPLETE snapshot for error cases."""
        from app.models.explanation import EvidenceGap
        return ExplanationSnapshot(
            tenant_id=self.tenant_id,
            decision_id="",
            invoice_id=document_id,
            explanation_status="INCOMPLETE",
            gaps=[EvidenceGap(
                stage=4, artifact_type="decision_record",
                reason=reason, impact="Cannot generate explanation",
            )],
            processing_time_seconds=round(time.time() - start_time, 2),
        )

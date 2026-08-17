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
    ExplanationSnapshot, IntegrityProof, EvidenceGap,
)
from app.db import repository
from app.pipeline.stage5.evidence_resolver import (
    resolve_evidence,
    UpstreamEvidenceContext,
    artifact_to_dict,
    _resolve_validation_report,
)
from app.pipeline.stage5.narrative_builder import (
    build_narrative,
    build_narrative_from_artifacts,
)
from app.pipeline.stage5.completeness_gate import validate_completeness
from app.pipeline.stage5.control_verifier import verify_controls
from app.pipeline.stage5.audit_ledger import append_explanation_audit, compute_content_hash
from app.pipeline.stage5.snapshot_loader import snapshot_from_explanation_row

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
        routing_status: str | None = None,
        verification=None,
        reconciliation=None,
    ) -> ExplanationSnapshot:
        """
        Run the complete Stage 5 explanation pipeline.

        Never raises — returns INCOMPLETE snapshot with narrative on failure.
        """
        start_time = time.time()
        generated_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"[{document_id}] Stage 5: Starting explanation pipeline")

        if not decision_record or not decision_record.decision_id:
            logger.error(f"[{document_id}] Stage 5: Invalid decision record")
            return self._error_snapshot(document_id, "Invalid decision record", start_time)

        existing = repository.get_explanation_by_decision(decision_record.decision_id)
        if existing:
            logger.info(
                f"[{document_id}] Stage 5: Explanation already exists "
                f"for decision {decision_record.decision_id} — returning stored snapshot"
            )
            snapshot = snapshot_from_explanation_row(existing, document_id)
            if not snapshot.narrative:
                snapshot.narrative = self._build_narrative_safe(
                    document_id,
                    decision_record,
                    extraction=extraction,
                    match_package=match_package,
                    validation_report=validation_report,
                    routing_status=routing_status,
                    verification=verification,
                    reconciliation=reconciliation,
                )
            return snapshot

        try:
            return self._run_explain(
                document_id=document_id,
                decision_record=decision_record,
                extraction=extraction,
                match_package=match_package,
                validation_report=validation_report,
                routing_status=routing_status,
                verification=verification,
                reconciliation=reconciliation,
                start_time=start_time,
                generated_at=generated_at,
            )
        except Exception as e:
            logger.error(f"[{document_id}] Stage 5 failed: {e}", exc_info=True)
            return self._fallback_snapshot(
                document_id=document_id,
                decision_record=decision_record,
                error=str(e),
                extraction=extraction,
                match_package=match_package,
                validation_report=validation_report,
                routing_status=routing_status,
                verification=verification,
                reconciliation=reconciliation,
                start_time=start_time,
                generated_at=generated_at,
            )

    def _run_explain(
        self,
        *,
        document_id: str,
        decision_record: DecisionRecord,
        extraction,
        match_package,
        validation_report,
        routing_status: str | None,
        verification,
        reconciliation,
        start_time: float,
        generated_at: str,
    ) -> ExplanationSnapshot:
        context = None
        if any(v is not None for v in (extraction, match_package, validation_report)):
            context = UpstreamEvidenceContext(
                extraction=artifact_to_dict(extraction),
                match_package=artifact_to_dict(match_package),
                validation_report=artifact_to_dict(validation_report),
            )
        evidence = resolve_evidence(document_id, decision_record, context=context)

        run = repository.get_run(document_id) or {}
        extraction_dict = artifact_to_dict(extraction) or artifact_to_dict(run.get("extraction_json"))
        match_dict = artifact_to_dict(match_package) or artifact_to_dict(run.get("stage2_result_json"))
        validation_dict = artifact_to_dict(validation_report)
        if validation_dict is None:
            validation_dict = _resolve_validation_report(document_id, decision_record, context)
        verification_dict = artifact_to_dict(verification) or artifact_to_dict(run.get("verification_json"))
        reconciliation_dict = artifact_to_dict(reconciliation) or artifact_to_dict(run.get("reconciliation_json"))
        routing_status = routing_status or run.get("status")

        policy_version = decision_record.trace.policy.policy_version
        policy_hash = compute_content_hash(
            json.dumps(decision_record.trace.policy.model_dump())
        )

        narrative = self._build_narrative_safe(
            document_id,
            decision_record,
            extraction=extraction_dict,
            match_package=match_dict,
            validation_report=validation_dict,
            routing_status=routing_status,
            verification=verification_dict,
            reconciliation=reconciliation_dict,
        )

        rule_trace_summary = [
            {
                "rule_id": r.rule_id,
                "result": r.result,
                "priority": r.priority,
                "detail": r.detail,
            }
            for r in decision_record.trace.rules_evaluated
        ]

        exp = repository.get_explanation(document_id)
        human_actions_raw = (exp or {}).get("human_actions_json") or []
        human_actions = human_actions_raw if isinstance(human_actions_raw, list) else []
        control_verifications = verify_controls(decision_record, human_actions=human_actions)

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

        completeness = validate_completeness(snapshot)
        if completeness.is_complete:
            snapshot.explanation_status = "COMPLETE"
        else:
            snapshot.explanation_status = "INCOMPLETE"
            snapshot.gaps.extend(completeness.gaps)

        snapshot_json = snapshot.model_dump_json()
        content_hash = compute_content_hash(snapshot_json)
        previous_hash = repository.get_last_audit_hash()
        snapshot.integrity = IntegrityProof(
            content_hash=content_hash,
            previous_hash=previous_hash,
        )
        snapshot.processing_time_seconds = round(time.time() - start_time, 2)

        self._persist_snapshot(snapshot)

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
            f"({len(snapshot.narrative)} narrative steps, {snapshot.processing_time_seconds}s)"
        )
        return snapshot

    def _build_narrative_safe(self, document_id, decision_record, **kwargs) -> list:
        try:
            narrative = build_narrative(decision_record, **kwargs)
            if narrative:
                return narrative
        except Exception as e:
            logger.error(f"[{document_id}] Narrative build error: {e}", exc_info=True)
        return build_narrative_from_artifacts(document_id, decision_record=decision_record, **kwargs)

    def _fallback_snapshot(
        self,
        *,
        document_id: str,
        decision_record: DecisionRecord,
        error: str,
        extraction,
        match_package,
        validation_report,
        routing_status: str | None,
        verification,
        reconciliation,
        start_time: float,
        generated_at: str,
    ) -> ExplanationSnapshot:
        """Produce a usable explanation even when persistence or audit fails."""
        run = repository.get_run(document_id) or {}
        narrative = self._build_narrative_safe(
            document_id,
            decision_record,
            extraction=artifact_to_dict(extraction) or artifact_to_dict(run.get("extraction_json")),
            match_package=artifact_to_dict(match_package) or artifact_to_dict(run.get("stage2_result_json")),
            validation_report=artifact_to_dict(validation_report),
            routing_status=routing_status or run.get("status"),
            verification=artifact_to_dict(verification) or artifact_to_dict(run.get("verification_json")),
            reconciliation=artifact_to_dict(reconciliation) or artifact_to_dict(run.get("reconciliation_json")),
        )
        if narrative:
            notice = type(narrative[0])(
                step=2,
                category="stage5_notice",
                text=(
                    f"Note: explanation engine encountered an error ({error}). "
                    "The steps below were rebuilt from stored pipeline data."
                ),
                source_rule_id="STAGE5_RECOVERY",
                icon="⚠️",
            )
            renumbered = [narrative[0]]
            renumbered.append(notice)
            for i, entry in enumerate(narrative[1:], start=3):
                renumbered.append(entry.model_copy(update={"step": i}))
            narrative = renumbered

        snapshot = ExplanationSnapshot(
            tenant_id=self.tenant_id,
            decision_id=decision_record.decision_id,
            invoice_id=document_id,
            validation_run_id=decision_record.validation_run_id,
            explanation_status="INCOMPLETE",
            policy_version=decision_record.trace.policy.policy_version,
            decision_outcome=decision_record.decision,
            decision_substate=decision_record.decision_substate,
            narrative=narrative,
            evidence_summary=list(decision_record.evidence_summary),
            gaps=[EvidenceGap(
                stage=5,
                artifact_type="explanation_engine",
                reason=error,
                impact="Full audit persistence may be incomplete; narrative rebuilt from artifacts",
            )],
            generated_at=generated_at,
            processing_time_seconds=round(time.time() - start_time, 2),
        )
        try:
            self._persist_snapshot(snapshot)
        except Exception as persist_err:
            logger.error(f"[{document_id}] Fallback persist failed: {persist_err}", exc_info=True)
        return snapshot

    def _persist_snapshot(self, snapshot: ExplanationSnapshot) -> None:
        """Persist the explanation snapshot to the database."""
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

    def _error_snapshot(
        self, document_id: str, reason: str, start_time: float
    ) -> ExplanationSnapshot:
        """Create an INCOMPLETE snapshot for error cases."""
        from app.models.explanation import NarrativeEntry
        return ExplanationSnapshot(
            tenant_id=self.tenant_id,
            decision_id="",
            invoice_id=document_id,
            explanation_status="INCOMPLETE",
            narrative=[
                NarrativeEntry(
                    step=1,
                    category="stage5_error",
                    text=f"Explanation could not be generated: {reason}",
                    source_rule_id="STAGE5_ERROR",
                    icon="❌",
                )
            ],
            gaps=[EvidenceGap(
                stage=4, artifact_type="decision_record",
                reason=reason, impact="Cannot generate explanation",
            )],
            processing_time_seconds=round(time.time() - start_time, 2),
        )

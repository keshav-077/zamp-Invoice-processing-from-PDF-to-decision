"""
InvoiceFlow AI — Stage 4: Decision Orchestrator

Chains the complete 10-step decision pipeline:
  1. Contract + Freshness Gate
  2. Hard Control Gate
  3. Mandatory Overrides
  4. Stage 3 State Evaluation
  5. Policy Resolution
  6. Policy Evaluation
  7. Authority + SoD Resolution
  8. Final Disposition
  9. Routing + SLA
  10. Immutable Decision Trace + Persist
"""

import json
import logging
import time
from datetime import datetime, timezone

from app.models.validation import ValidationReport
from app.models.decision import (
    DecisionRecord, DecisionTrace, RuleEvaluation,
    PolicyResolution, AuthorityResolution, RoutingDecision,
)
from app.db import repository
from app.pipeline.stage4.decision_context import build_decision_context
from app.pipeline.stage4.contract_gate import validate_decision_contract
from app.pipeline.stage4.hard_control_gate import evaluate_hard_controls
from app.pipeline.stage4.mandatory_overrides import evaluate_overrides
from app.pipeline.stage4.policy_engine import evaluate_policy
from app.pipeline.stage4.authority_resolver import resolve_authority
from app.pipeline.stage4.routing_engine import resolve_routing

logger = logging.getLogger(__name__)


class Stage4Orchestrator:
    """Orchestrates the complete Stage 4 Decision pipeline."""

    def __init__(
        self,
        auto_approve_limit: float = 5000.0,
        manager_limit: float = 50000.0,
        director_limit: float = 500000.0,
        freshness_hours: int = 24,
    ):
        self.auto_approve_limit = auto_approve_limit
        self.manager_limit = manager_limit
        self.director_limit = director_limit
        self.freshness_hours = freshness_hours

    def decide(
        self,
        document_id: str,
        validation_report: ValidationReport,
    ) -> DecisionRecord:
        """
        Run the complete Stage 4 decision pipeline.

        Args:
            document_id: Invoice document ID
            validation_report: Stage 3 ValidationReport

        Returns:
            DecisionRecord — immutable business decision
        """
        start_time = time.time()
        decided_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"[{document_id}] Stage 4: Starting decision pipeline")

        all_rules: list[RuleEvaluation] = []
        triggered_rules: list[str] = []
        decision_path: list[str] = []
        evidence_summary: list[str] = []

        # ── Step 0: Build Decision Context ──
        ctx = build_decision_context(validation_report)
        decision_path.append(f"Context built: state={ctx.validation_state}, amount={ctx.amount}")

        # ── Step 1: Contract + Freshness Gate ──
        logger.info(f"[{document_id}] Step 1: Contract gate")
        contract_result = validate_decision_contract(ctx, self.freshness_hours)
        if contract_result.rule:
            all_rules.append(contract_result.rule)

        if not contract_result.is_valid:
            decision_path.append(f"Contract gate: {contract_result.reason}")
            if contract_result.rule and contract_result.rule.result == "TRIGGERED":
                triggered_rules.append(contract_result.rule.rule_id)
            evidence_summary.append(f"❌ Contract gate: {contract_result.reason}")

            return self._build_record(
                document_id=document_id,
                validation_run_id=ctx.validation_run_id,
                decision=contract_result.decision or "WAITING_FOR_VALIDATION",
                substate=contract_result.substate or "POLICY_CONFIGURATION_ERROR",
                reason_codes=[contract_result.reason],
                all_rules=all_rules,
                triggered_rules=triggered_rules,
                decision_path=decision_path,
                evidence_summary=evidence_summary,
                evidence_refs=ctx.evidence_refs,
                start_time=start_time,
                decided_at=decided_at,
                ctx=ctx,
            )

        decision_path.append("Contract gate: PASSED")

        # ── Step 2: Hard Control Gate ──
        logger.info(f"[{document_id}] Step 2: Hard control gate")
        hard_result = evaluate_hard_controls(ctx)
        if hard_result.rules:
            all_rules.extend(hard_result.rules)

        if hard_result.triggered:
            decision_path.append(f"Hard control: REJECT ({', '.join(hard_result.reason_codes or [])})")
            triggered_rules.extend(r.rule_id for r in (hard_result.rules or []) if r.result == "TRIGGERED")
            evidence_summary.append(f"🚫 Hard control REJECT: {', '.join(hard_result.reason_codes or [])}")

            return self._build_record(
                document_id=document_id,
                validation_run_id=ctx.validation_run_id,
                decision="REJECT",
                substate="TERMINAL_REJECT",
                reason_codes=hard_result.reason_codes or [],
                all_rules=all_rules,
                triggered_rules=triggered_rules,
                decision_path=decision_path,
                evidence_summary=evidence_summary,
                evidence_refs=ctx.evidence_refs,
                start_time=start_time,
                decided_at=decided_at,
                ctx=ctx,
            )

        decision_path.append("Hard control gate: PASSED")

        # ── Step 3: Mandatory Overrides ──
        logger.info(f"[{document_id}] Step 3: Mandatory overrides")
        override_result = evaluate_overrides(ctx)
        if override_result.rules:
            all_rules.extend(override_result.rules)

        if override_result.triggered:
            decision_path.append(
                f"Override: {override_result.substate} ({', '.join(override_result.reason_codes or [])})"
            )
            triggered_rules.extend(r.rule_id for r in (override_result.rules or []) if r.result == "TRIGGERED")
            evidence_summary.append(
                f"⚠️ Override: {', '.join(override_result.reason_codes or [])}"
            )

            routing = resolve_routing(override_result.substate or "STANDARD_REVIEW")
            return self._build_record(
                document_id=document_id,
                validation_run_id=ctx.validation_run_id,
                decision="REVIEW_REQUIRED",
                substate=override_result.substate or "STANDARD_REVIEW",
                reason_codes=override_result.reason_codes or [],
                all_rules=all_rules,
                triggered_rules=triggered_rules,
                decision_path=decision_path,
                evidence_summary=evidence_summary,
                evidence_refs=ctx.evidence_refs,
                routing=routing,
                start_time=start_time,
                decided_at=decided_at,
                ctx=ctx,
            )

        decision_path.append("Mandatory overrides: NONE triggered")

        # ── Steps 4-6: Policy Evaluation ──
        logger.info(f"[{document_id}] Steps 4-6: Policy evaluation")
        policy_result = evaluate_policy(
            ctx,
            auto_approve_limit=self.auto_approve_limit,
            manager_limit=self.manager_limit,
            director_limit=self.director_limit,
        )
        if policy_result.rules:
            all_rules.extend(policy_result.rules)
            triggered_rules.extend(
                r.rule_id for r in policy_result.rules if r.result == "TRIGGERED"
            )

        if not policy_result.continue_to_authority:
            # Policy determined outcome (HOLD/REVIEW/INCOMPLETE/ERROR)
            decision_path.append(
                f"Policy: {policy_result.decision}/{policy_result.substate}"
            )
            evidence_summary.append(
                f"📋 Policy: {policy_result.decision} ({', '.join(policy_result.reason_codes or [])})"
            )

            routing = resolve_routing(policy_result.substate or "STANDARD_REVIEW")
            return self._build_record(
                document_id=document_id,
                validation_run_id=ctx.validation_run_id,
                decision=policy_result.decision or "REVIEW_REQUIRED",
                substate=policy_result.substate or "STANDARD_REVIEW",
                reason_codes=policy_result.reason_codes or [],
                all_rules=all_rules,
                triggered_rules=triggered_rules,
                decision_path=decision_path,
                evidence_summary=evidence_summary,
                evidence_refs=ctx.evidence_refs,
                policy=policy_result.policy,
                routing=routing,
                start_time=start_time,
                decided_at=decided_at,
                ctx=ctx,
            )

        decision_path.append(
            f"Policy: tier={policy_result.policy.materiality_tier}, "
            f"auto_eligible={policy_result.policy.auto_approve_eligible}"
        )

        # ── Step 7: Authority Resolution ──
        logger.info(f"[{document_id}] Step 7: Authority resolution")
        authority_result = resolve_authority(ctx, policy_result.policy)
        all_rules.extend(authority_result.rules)
        triggered_rules.extend(
            r.rule_id for r in authority_result.rules if r.result == "TRIGGERED"
        )

        decision_path.append(
            f"Authority: {authority_result.decision}/{authority_result.substate}"
        )

        # ── Step 8: Final Disposition ──
        decision = authority_result.decision
        substate = authority_result.substate

        if substate == "AUTO_APPROVED":
            evidence_summary.append(f"✅ AUTO_APPROVED: ${ctx.amount or 0:,.2f}")
            if ctx.matched_po_number and ctx.amount:
                from app.adapters.erp_adapter import get_erp_adapter

                get_erp_adapter().record_invoice_posting(
                    document_id=document_id,
                    po_number=ctx.matched_po_number,
                    amount=float(ctx.amount),
                )
        elif substate == "APPROVAL_REQUIRED":
            evidence_summary.append(
                f"📝 APPROVAL_REQUIRED: ${ctx.amount or 0:,.2f} → "
                f"{authority_result.authority.approver_group}"
            )

        # ── Step 9: Routing ──
        logger.info(f"[{document_id}] Step 9: Routing")
        routing = resolve_routing(
            substate,
            approver_group=authority_result.authority.approver_group
            if authority_result.authority.required else None,
        )

        # ── Step 10: Build + Persist ──
        record = self._build_record(
            document_id=document_id,
            validation_run_id=ctx.validation_run_id,
            decision=decision,
            substate=substate,
            reason_codes=[],
            all_rules=all_rules,
            triggered_rules=triggered_rules,
            decision_path=decision_path,
            evidence_summary=evidence_summary,
            evidence_refs=ctx.evidence_refs,
            policy=policy_result.policy,
            authority=authority_result.authority,
            routing=routing,
            start_time=start_time,
            decided_at=decided_at,
            ctx=ctx,
        )

        logger.info(
            f"[{document_id}] Stage 4 complete: {decision}/{substate} "
            f"({record.processing_time_seconds}s)"
        )
        return record

    def _build_record(
        self,
        document_id: str,
        validation_run_id: str,
        decision: str,
        substate: str,
        reason_codes: list[str],
        all_rules: list[RuleEvaluation],
        triggered_rules: list[str],
        decision_path: list[str],
        evidence_summary: list[str],
        evidence_refs: list[str],
        start_time: float,
        decided_at: str,
        ctx=None,
        policy: PolicyResolution | None = None,
        authority: AuthorityResolution | None = None,
        routing: RoutingDecision | None = None,
    ) -> DecisionRecord:
        """Build the immutable DecisionRecord and persist it."""

        trace = DecisionTrace(
            rules_evaluated=all_rules,
            triggered_rules=triggered_rules,
            policy=policy or PolicyResolution(),
            authority=authority or AuthorityResolution(),
            routing=routing or RoutingDecision(),
            stage3_state_used=ctx.validation_state if ctx else "",
            stage3_reason_codes_used=ctx.reason_codes if ctx else [],
            decision_path=decision_path,
        )

        record = DecisionRecord(
            invoice_id=document_id,
            validation_run_id=validation_run_id,
            decision=decision,
            decision_substate=substate,
            reason_codes=reason_codes,
            trace=trace,
            evidence_refs=evidence_refs,
            evidence_summary=evidence_summary,
            decided_at=decided_at,
            processing_time_seconds=round(time.time() - start_time, 2),
        )

        # Persist
        self._persist_record(record)
        return record

    def _persist_record(self, record: DecisionRecord) -> None:
        """Persist the decision record to the audit trail."""
        try:
            repository.save_decision_record(
                decision_id=record.decision_id,
                document_id=record.invoice_id,
                validation_run_id=record.validation_run_id,
                decision=record.decision,
                decision_substate=record.decision_substate,
                record_json=record.model_dump_json(),
                reason_codes_json=json.dumps(record.reason_codes),
                rules_json=json.dumps([r.model_dump() for r in record.trace.rules_evaluated]),
                policy_json=record.trace.policy.model_dump_json(),
                authority_json=record.trace.authority.model_dump_json(),
                routing_json=record.trace.routing.model_dump_json(),
                trace_json=record.trace.model_dump_json(),
                evidence_refs_json=json.dumps(record.evidence_refs),
                evidence_summary_json=json.dumps(record.evidence_summary),
                decided_at=record.decided_at,
                engine_version=record.engine_version,
                processing_time_seconds=record.processing_time_seconds,
            )
        except Exception as e:
            logger.error(f"Failed to persist decision: {e}", exc_info=True)

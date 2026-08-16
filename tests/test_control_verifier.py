"""
Tests for Stage 5: Control Verifier
"""

import pytest
from app.models.decision import (
    DecisionRecord, DecisionTrace, AuthorityResolution,
)
from app.pipeline.stage5.control_verifier import verify_controls


def _make_record(substate="AUTO_APPROVED", dual_control=False):
    return DecisionRecord(
        invoice_id="INV-001",
        validation_run_id="VR-001",
        decision="APPROVE",
        decision_substate=substate,
        trace=DecisionTrace(
            authority=AuthorityResolution(
                dual_control_required=dual_control,
            ),
        ),
    )


class TestAutoApproved:
    def test_not_required(self):
        record = _make_record(substate="AUTO_APPROVED")
        verifications = verify_controls(record)
        assert len(verifications) == 1
        assert verifications[0].status == "NOT_REQUIRED"
        assert verifications[0].control_type == "AUTO_APPROVAL"


class TestTerminalReject:
    def test_not_required(self):
        record = _make_record(substate="TERMINAL_REJECT")
        verifications = verify_controls(record)
        assert len(verifications) == 1
        assert verifications[0].status == "NOT_REQUIRED"


class TestApprovalRequired:
    def test_pending(self):
        record = _make_record(substate="APPROVAL_REQUIRED")
        verifications = verify_controls(record)
        assert len(verifications) >= 1
        approval = [v for v in verifications if v.control_type == "APPROVAL"]
        assert len(approval) == 1
        assert approval[0].status == "PENDING"

    def test_dual_control(self):
        record = _make_record(substate="APPROVAL_REQUIRED", dual_control=True)
        verifications = verify_controls(record)
        dual = [v for v in verifications if v.control_type == "DUAL_CONTROL"]
        assert len(dual) == 1
        assert dual[0].status == "PENDING"


class TestWaitingStates:
    def test_waiting_for_grn(self):
        record = _make_record(substate="WAITING_FOR_GRN")
        verifications = verify_controls(record)
        assert len(verifications) == 1
        assert verifications[0].status == "PENDING"
        assert verifications[0].control_type == "DATA_RECEIPT"

    def test_revalidation_required(self):
        record = _make_record(substate="REVALIDATION_REQUIRED")
        verifications = verify_controls(record)
        assert verifications[0].status == "PENDING"


class TestSecurityReview:
    def test_vendor_security(self):
        record = _make_record(substate="VENDOR_SECURITY_REVIEW")
        verifications = verify_controls(record)
        assert len(verifications) >= 1
        bank = [v for v in verifications if v.control_type == "BANK_VERIFICATION"]
        assert len(bank) == 1
        assert bank[0].status == "PENDING"

    def test_fraud_review(self):
        record = _make_record(substate="FRAUD_REVIEW")
        verifications = verify_controls(record)
        fraud = [v for v in verifications if v.control_type == "FRAUD_INVESTIGATION"]
        assert len(fraud) == 1
        assert fraud[0].status == "PENDING"

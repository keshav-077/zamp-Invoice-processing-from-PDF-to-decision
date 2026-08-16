"""ERP adapter interface — mock/Postgres only for PS-1 prototype."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.db import repository


class ERPAdapter(ABC):
    @abstractmethod
    def get_po(self, po_number: str) -> dict | None: ...

    @abstractmethod
    def list_open_pos(self, vendor_id: str | None = None) -> list[dict]: ...

    @abstractmethod
    def record_invoice_posting(self, document_id: str, po_number: str, amount: float) -> bool: ...


class PostgresERPAdapter(ERPAdapter):
    """Uses seeded Postgres/SQLite PO master as ERP stand-in."""

    def get_po(self, po_number: str) -> dict | None:
        return repository.get_po(po_number)

    def list_open_pos(self, vendor_id: str | None = None) -> list[dict]:
        if vendor_id:
            return repository.search_pos_by_vendor(vendor_id, "open")
        return repository.get_all_open_pos()

    def record_invoice_posting(self, document_id: str, po_number: str, amount: float) -> bool:
        return repository.record_invoice_allocation(
            document_id=document_id,
            po_number=po_number,
            invoice_amount=amount,
        )


class MockERPAdapter(PostgresERPAdapter):
    """Alias for demo — same as Postgres adapter until NetSuite/SAP integration."""


def get_erp_adapter() -> ERPAdapter:
    return PostgresERPAdapter()

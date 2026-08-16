"""Tenant/company context for scoped master data and pipeline operations."""

from __future__ import annotations

from contextvars import ContextVar

DEFAULT_COMPANY_ID = "DEFAULT"

_current_company: ContextVar[str] = ContextVar("company_id", default=DEFAULT_COMPANY_ID)


def get_company_id() -> str:
    return _current_company.get()


def set_company_id(company_id: str | None) -> None:
    _current_company.set(company_id or DEFAULT_COMPANY_ID)


def company_scope(company_id: str | None = None) -> str:
    return company_id or get_company_id()

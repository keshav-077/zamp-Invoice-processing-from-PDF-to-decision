"""
Catalog invoice files from my-project/dataset (or a custom path).

Uses the production InputHandler + Extractor when GEMINI_API_KEY is set.
Falls back to loading an existing invoice_catalog.json for offline use.

Usage (from invoiceflow-ai/):
  python scripts/catalog_invoices.py
  python scripts/catalog_invoices.py --dataset ../my-project/dataset
  python scripts/catalog_invoices.py --offline   # skip LLM, use seed catalog only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline.input_handler import InputHandler  # noqa: E402

logger = logging.getLogger(__name__)

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg"}
DEFAULT_DATASET = ROOT.parent / "my-project" / "dataset"
OUTPUT_JSON = ROOT / "data" / "invoice_catalog.json"
OUTPUT_MD = ROOT / "data" / "invoice_catalog.md"


def _field_value(extraction, name: str):
    field = getattr(extraction, name, None)
    if field is None:
        return None, 0.0, "not_found"
    return field.value, field.confidence, field.status


def _propose_scenario(extraction, filename: str) -> str:
    inv_num, _, inv_st = _field_value(extraction, "invoice_number")
    po_ref, _, po_st = _field_value(extraction, "po_reference")
    total, _, _ = _field_value(extraction, "total_amount")

    if "demo3" in filename or "arithmetic" in filename:
        return "arithmetic"
    if "demo4" in filename or (inv_st == "not_found" and not inv_num):
        return "missing_field"
    if not po_ref and po_st in ("not_found", "uncertain"):
        return "ambiguous"
    if total and float(total) <= 5000:
        return "happy"
    return "standard"


def extraction_to_entry(path: Path, extraction) -> dict:
    lines = [
        {
            "description": li.description,
            "quantity": li.quantity,
            "unit_price": li.unit_price,
            "amount": li.amount,
        }
        for li in extraction.line_items
    ]
    inv_num, _, _ = _field_value(extraction, "invoice_number")
    po_ref, _, _ = _field_value(extraction, "po_reference")
    vendor, _, _ = _field_value(extraction, "vendor_name")
    inv_date, _, _ = _field_value(extraction, "invoice_date")
    currency, _, _ = _field_value(extraction, "currency")
    subtotal, _, _ = _field_value(extraction, "subtotal")
    tax_amount, _, _ = _field_value(extraction, "tax_amount")
    total_amount, _, _ = _field_value(extraction, "total_amount")

    return {
        "filename": path.name,
        "source_path": str(path),
        "vendor_name": vendor,
        "po_reference": po_ref,
        "invoice_number": inv_num,
        "invoice_date": inv_date,
        "currency": currency or "USD",
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "line_items": lines,
        "quality_notes": "",
        "proposed_scenario": _propose_scenario(extraction, path.name),
        "cataloged_at": datetime.now(timezone.utc).isoformat(),
        "extraction_source": "llm",
    }


async def catalog_with_llm(files: list[Path]) -> list[dict]:
    from app.providers.factory import get_provider
    from app.pipeline.extractor import Extractor

    provider = get_provider()
    handler = InputHandler()
    extractor = Extractor(provider)
    entries = []

    for path in files:
        logger.info("Extracting: %s", path.name)
        try:
            pages = handler.validate_and_preprocess(path)
            extraction = await extractor.extract(pages)
            entries.append(extraction_to_entry(path, extraction))
        except Exception as exc:
            logger.error("Failed %s: %s", path.name, exc)
            entries.append(
                {
                    "filename": path.name,
                    "source_path": str(path),
                    "error": str(exc),
                    "proposed_scenario": "unknown",
                    "cataloged_at": datetime.now(timezone.utc).isoformat(),
                    "extraction_source": "failed",
                }
            )
    return entries


def write_markdown(entries: list[dict], path: Path) -> None:
    lines = [
        "# Invoice Catalog",
        "",
        "Review and correct fields before building PO.xlsx.",
        "",
        "| File | Vendor | PO Ref | Invoice # | Total | Scenario |",
        "|------|--------|--------|-----------|-------|----------|",
    ]
    for e in entries:
        if e.get("error"):
            lines.append(f"| {e['filename']} | ERROR | — | — | — | {e.get('error','')} |")
            continue
        lines.append(
            f"| {e['filename']} | {e.get('vendor_name') or '—'} | "
            f"{e.get('po_reference') or '—'} | {e.get('invoice_number') or '—'} | "
            f"{e.get('total_amount') or '—'} | {e.get('proposed_scenario', '—')} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Catalog dataset invoices")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--offline", action="store_true", help="Skip LLM; keep existing JSON")
    args = parser.parse_args()

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    if args.offline and OUTPUT_JSON.exists():
        logger.info("Offline mode — catalog unchanged at %s", OUTPUT_JSON)
        return

    files = sorted(
        p for p in args.dataset.glob("*") if p.suffix.lower() in SUPPORTED
    )
    if not files:
        logger.warning("No invoice files in %s", args.dataset)
        if OUTPUT_JSON.exists():
            logger.info("Using existing %s", OUTPUT_JSON)
            return
        sys.exit(1)

    entries = await catalog_with_llm(files)
    payload = {
        "dataset_path": str(args.dataset),
        "cataloged_at": datetime.now(timezone.utc).isoformat(),
        "invoices": entries,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_markdown(entries, OUTPUT_MD)
    logger.info("Wrote %s (%d invoices)", OUTPUT_JSON, len(entries))


if __name__ == "__main__":
    asyncio.run(main())

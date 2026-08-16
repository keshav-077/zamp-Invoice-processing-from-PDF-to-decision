"""
Generate two split-billing invoice PDFs against PO-SPLIT-01 ($10,000 blanket PO).

Usage:
  python scripts/generate_split_billing_pdfs.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test_invoices" / "split_billing"


def _make_pdf(path: Path, title: str, lines: list[tuple[str, float]], total: float, po: str, inv_no: str):
    import fitz  # PyMuPDF

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 72
    for text in [
        title,
        f"PO Number: {po}",
        f"Invoice Number: {inv_no}",
        f"Vendor: Split Billing Demo Corp",
        "",
        "Description                          Amount",
        "-" * 45,
    ]:
        page.insert_text((72, y), text, fontsize=11)
        y += 18

    for desc, amt in lines:
        page.insert_text((72, y), f"{desc[:30]:<30} ${amt:,.2f}", fontsize=11)
        y += 16

    y += 10
    page.insert_text((72, y), f"TOTAL: ${total:,.2f}", fontsize=13)
    doc.save(path)
    doc.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    _make_pdf(
        OUT / "split_billing_part1.pdf",
        "INVOICE — Part 1 of 2",
        [("Professional services — phase A", 4000.00)],
        4000.00,
        "PO-SPLIT-01",
        "SPLIT-INV-001",
    )
    _make_pdf(
        OUT / "split_billing_part2.pdf",
        "INVOICE — Part 2 of 2",
        [("Professional services — phase B", 3500.00)],
        3500.00,
        "PO-SPLIT-01",
        "SPLIT-INV-002",
    )
    print(f"Wrote split billing PDFs to {OUT}")


if __name__ == "__main__":
    main()

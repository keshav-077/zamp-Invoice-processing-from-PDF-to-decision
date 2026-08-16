"""
InvoiceFlow AI — Synthetic Test Invoice Generator

Generates 4 demo invoice PDFs covering key scenarios:
1. Clean invoice (all fields, correct arithmetic)
2. Low-quality scan simulation (degraded quality)
3. Arithmetic mismatch (subtotal + tax ≠ total)
4. Missing critical field (no invoice number)

Uses PyMuPDF (fitz) for PDF generation.
"""

import fitz  # PyMuPDF
from pathlib import Path


OUTPUT_DIR = Path(__file__).parent


def create_clean_invoice():
    """Demo 1: Clean invoice — all fields present, correct arithmetic."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4

    # Header
    page.insert_text((50, 50), "ACME CORPORATION", fontsize=20, fontname="helv", color=(0.1, 0.1, 0.4))
    page.insert_text((50, 72), "123 Business Ave, Suite 400", fontsize=9, color=(0.4, 0.4, 0.4))
    page.insert_text((50, 84), "New York, NY 10001 | acme@example.com", fontsize=9, color=(0.4, 0.4, 0.4))

    # Invoice label
    page.insert_text((400, 50), "INVOICE", fontsize=24, fontname="helv", color=(0.1, 0.1, 0.4))

    # Invoice details
    details = [
        ("Invoice Number:", "INV-2026-0471"),
        ("Invoice Date:", "2026-07-14"),
        ("Due Date:", "2026-08-14"),
        ("PO Reference:", "PO-2298"),
        ("Currency:", "USD"),
    ]
    y = 110
    for label, value in details:
        page.insert_text((380, y), label, fontsize=9, fontname="helv", color=(0.3, 0.3, 0.3))
        page.insert_text((480, y), value, fontsize=9, fontname="helv")
        y += 16

    # Bill To
    page.insert_text((50, 120), "Bill To:", fontsize=10, fontname="helv", color=(0.3, 0.3, 0.3))
    page.insert_text((50, 135), "TechStart Inc.", fontsize=11, fontname="helv")
    page.insert_text((50, 149), "456 Innovation Blvd", fontsize=9, color=(0.4, 0.4, 0.4))
    page.insert_text((50, 161), "San Francisco, CA 94102", fontsize=9, color=(0.4, 0.4, 0.4))

    # Line items header
    y = 220
    page.draw_rect(fitz.Rect(40, y - 5, 555, y + 15), color=(0.1, 0.1, 0.4), fill=(0.1, 0.1, 0.4))
    page.insert_text((50, y + 9), "Description", fontsize=9, fontname="helv", color=(1, 1, 1))
    page.insert_text((280, y + 9), "Qty", fontsize=9, fontname="helv", color=(1, 1, 1))
    page.insert_text((340, y + 9), "Unit Price", fontsize=9, fontname="helv", color=(1, 1, 1))
    page.insert_text((460, y + 9), "Amount", fontsize=9, fontname="helv", color=(1, 1, 1))

    # Line items
    items = [
        ("Cloud Infrastructure Setup", "1", "$2,500.00", "$2,500.00"),
        ("API Integration Services", "3", "$800.00", "$2,400.00"),
        ("Security Audit & Compliance", "1", "$1,200.00", "$1,200.00"),
        ("Technical Documentation", "2", "$350.00", "$700.00"),
    ]

    y += 30
    for desc, qty, price, amount in items:
        page.insert_text((50, y), desc, fontsize=9)
        page.insert_text((290, y), qty, fontsize=9)
        page.insert_text((340, y), price, fontsize=9)
        page.insert_text((460, y), amount, fontsize=9)
        y += 22
        page.draw_line((40, y - 8), (555, y - 8), color=(0.9, 0.9, 0.9))

    # Totals
    y += 20
    page.draw_line((350, y - 10), (555, y - 10), color=(0.7, 0.7, 0.7), width=0.5)
    page.insert_text((370, y), "Subtotal:", fontsize=10, fontname="helv", color=(0.3, 0.3, 0.3))
    page.insert_text((470, y), "$6,800.00", fontsize=10, fontname="helv")
    y += 20
    page.insert_text((370, y), "Tax (8%):", fontsize=10, fontname="helv", color=(0.3, 0.3, 0.3))
    page.insert_text((470, y), "$544.00", fontsize=10, fontname="helv")
    y += 5
    page.draw_line((350, y + 5), (555, y + 5), color=(0.1, 0.1, 0.4), width=1.5)
    y += 22
    page.insert_text((370, y), "TOTAL DUE:", fontsize=12, fontname="helv", color=(0.1, 0.1, 0.4))
    page.insert_text((470, y), "$7,344.00", fontsize=12, fontname="helv", color=(0.1, 0.1, 0.4))

    # Payment terms
    y += 50
    page.insert_text((50, y), "Payment Terms: Net 30", fontsize=9, color=(0.4, 0.4, 0.4))
    page.insert_text((50, y + 14), "Please include invoice number with payment.", fontsize=8, color=(0.5, 0.5, 0.5))

    # Footer
    page.insert_text((50, 800), "Thank you for your business!", fontsize=10, fontname="helv", color=(0.3, 0.3, 0.3))

    output_path = OUTPUT_DIR / "demo1_clean_invoice.pdf"
    doc.save(str(output_path))
    doc.close()
    print(f"Created: {output_path}")


def create_low_quality_scan():
    """Demo 2: Low-quality scan — slightly degraded, simulating a scan."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # Simulate scan background (slightly gray)
    page.draw_rect(fitz.Rect(0, 0, 595, 842), fill=(0.95, 0.94, 0.93))

    # Header — slightly misaligned to simulate scan
    page.insert_text((52, 53), "GLOBAL SUPPLY CO.", fontsize=18, fontname="helv", color=(0.15, 0.15, 0.15))
    page.insert_text((51, 73), "789 Industrial Park Dr", fontsize=8, color=(0.45, 0.45, 0.45))
    page.insert_text((51, 83), "Chicago, IL 60601", fontsize=8, color=(0.45, 0.45, 0.45))

    page.insert_text((395, 52), "INVOICE", fontsize=22, fontname="helv", color=(0.2, 0.2, 0.2))

    # Invoice details
    details = [
        ("Invoice #:", "GS-2026-1847"),
        ("Date:", "2026-06-28"),
        ("Due:", "2026-07-28"),
        ("PO Ref:", "PO-4410"),
    ]
    y = 110
    for label, value in details:
        page.insert_text((380, y), label, fontsize=8, color=(0.35, 0.35, 0.35))
        page.insert_text((450, y), value, fontsize=8)
        y += 14

    # Bill To
    page.insert_text((52, 120), "Bill To:", fontsize=9, color=(0.35, 0.35, 0.35))
    page.insert_text((52, 134), "MegaCorp Industries", fontsize=10)
    page.insert_text((52, 147), "321 Enterprise Way, Dallas, TX", fontsize=8, color=(0.45, 0.45, 0.45))

    # Line items
    y = 200
    page.draw_rect(fitz.Rect(42, y - 4, 553, y + 14), fill=(0.3, 0.3, 0.3))
    page.insert_text((52, y + 9), "Item", fontsize=8, color=(0.95, 0.95, 0.95))
    page.insert_text((280, y + 9), "Qty", fontsize=8, color=(0.95, 0.95, 0.95))
    page.insert_text((340, y + 9), "Rate", fontsize=8, color=(0.95, 0.95, 0.95))
    page.insert_text((460, y + 9), "Total", fontsize=8, color=(0.95, 0.95, 0.95))

    items = [
        ("Industrial Bearings Type-A", "50", "$45.00", "$2,250.00"),
        ("Hydraulic Seals Pack", "20", "$120.00", "$2,400.00"),
        ("Steel Connector Plates", "100", "$12.50", "$1,250.00"),
    ]

    y += 28
    for desc, qty, price, amount in items:
        page.insert_text((52, y), desc, fontsize=8, color=(0.15, 0.15, 0.15))
        page.insert_text((290, y), qty, fontsize=8)
        page.insert_text((340, y), price, fontsize=8)
        page.insert_text((460, y), amount, fontsize=8)
        y += 20

    # Totals
    y += 15
    page.insert_text((370, y), "Subtotal:", fontsize=9, color=(0.35, 0.35, 0.35))
    page.insert_text((460, y), "$5,900.00", fontsize=9)
    y += 16
    page.insert_text((370, y), "Sales Tax:", fontsize=9, color=(0.35, 0.35, 0.35))
    page.insert_text((460, y), "$472.00", fontsize=9)
    y += 20
    page.draw_line((350, y - 5), (553, y - 5), color=(0.3, 0.3, 0.3), width=1)
    page.insert_text((370, y), "Amount Due:", fontsize=11, fontname="helv")
    page.insert_text((460, y), "$6,372.00", fontsize=11, fontname="helv")

    output_path = OUTPUT_DIR / "demo2_scan_invoice.pdf"
    doc.save(str(output_path))
    doc.close()
    print(f"Created: {output_path}")


def create_arithmetic_mismatch():
    """Demo 3: Arithmetic mismatch — subtotal + tax ≠ total."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    page.insert_text((50, 50), "BRIGHTWAVE SOLUTIONS", fontsize=18, fontname="helv", color=(0.05, 0.3, 0.55))
    page.insert_text((50, 70), "555 Tech Campus, Austin, TX 78701", fontsize=8, color=(0.4, 0.4, 0.4))

    page.insert_text((420, 50), "INVOICE", fontsize=22, fontname="helv", color=(0.05, 0.3, 0.55))

    details = [
        ("Invoice No:", "BW-7723"),
        ("Date:", "2026-08-01"),
        ("Due Date:", "2026-09-01"),
        ("PO #:", "PO-9001"),
        ("Currency:", "USD"),
    ]
    y = 100
    for label, value in details:
        page.insert_text((400, y), label, fontsize=9, color=(0.3, 0.3, 0.3))
        page.insert_text((490, y), value, fontsize=9)
        y += 15

    # Line items
    y = 220
    page.draw_rect(fitz.Rect(40, y - 4, 555, y + 14), fill=(0.05, 0.3, 0.55))
    page.insert_text((50, y + 9), "Service Description", fontsize=9, color=(1, 1, 1))
    page.insert_text((300, y + 9), "Hours", fontsize=9, color=(1, 1, 1))
    page.insert_text((370, y + 9), "Rate/hr", fontsize=9, color=(1, 1, 1))
    page.insert_text((470, y + 9), "Amount", fontsize=9, color=(1, 1, 1))

    items = [
        ("Frontend Development", "40", "$150.00", "$6,000.00"),
        ("Backend API Development", "60", "$175.00", "$10,500.00"),
        ("QA Testing", "20", "$100.00", "$2,000.00"),
    ]

    y += 28
    for desc, qty, price, amount in items:
        page.insert_text((50, y), desc, fontsize=9)
        page.insert_text((310, y), qty, fontsize=9)
        page.insert_text((370, y), price, fontsize=9)
        page.insert_text((470, y), amount, fontsize=9)
        y += 22

    # INTENTIONAL ARITHMETIC ERROR: 18500 + 1480 = 19980, but total shows 20,350
    y += 20
    page.insert_text((380, y), "Subtotal:", fontsize=10)
    page.insert_text((480, y), "$18,500.00", fontsize=10)
    y += 18
    page.insert_text((380, y), "Tax (8%):", fontsize=10)
    page.insert_text((480, y), "$1,480.00", fontsize=10)
    y += 5
    page.draw_line((370, y + 5), (555, y + 5), color=(0.05, 0.3, 0.55), width=1.5)
    y += 22
    page.insert_text((380, y), "TOTAL:", fontsize=13, fontname="helv", color=(0.05, 0.3, 0.55))
    page.insert_text((480, y), "$20,350.00", fontsize=13, fontname="helv", color=(0.05, 0.3, 0.55))

    # Note about the "error"
    y += 40
    page.insert_text((50, y), "* Includes express delivery surcharge", fontsize=8, color=(0.5, 0.5, 0.5))

    output_path = OUTPUT_DIR / "demo3_arithmetic_mismatch.pdf"
    doc.save(str(output_path))
    doc.close()
    print(f"Created: {output_path}")


def create_missing_field_invoice():
    """Demo 4: Missing critical field — no invoice number visible."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    page.insert_text((50, 50), "SUMMIT CONSULTING GROUP", fontsize=17, fontname="helv", color=(0.4, 0.15, 0.1))
    page.insert_text((50, 70), "100 Mountain View Rd, Denver, CO 80202", fontsize=8, color=(0.4, 0.4, 0.4))

    page.insert_text((430, 50), "INVOICE", fontsize=22, fontname="helv", color=(0.4, 0.15, 0.1))

    # NO INVOICE NUMBER — intentionally missing
    details = [
        ("Date:", "2026-05-20"),
        ("Due:", "2026-06-20"),
        ("Currency:", "USD"),
    ]
    y = 100
    for label, value in details:
        page.insert_text((420, y), label, fontsize=9, color=(0.3, 0.3, 0.3))
        page.insert_text((490, y), value, fontsize=9)
        y += 15

    page.insert_text((50, 120), "To: Pacific Retail Corp", fontsize=10, fontname="helv")

    # Line items
    y = 200
    page.draw_rect(fitz.Rect(40, y - 4, 555, y + 14), fill=(0.4, 0.15, 0.1))
    page.insert_text((50, y + 9), "Consulting Service", fontsize=9, color=(1, 1, 1))
    page.insert_text((400, y + 9), "Fee", fontsize=9, color=(1, 1, 1))

    items = [
        ("Strategic Planning Workshop (2 days)", "$5,000.00"),
        ("Market Analysis Report", "$3,500.00"),
        ("Executive Presentation", "$1,500.00"),
    ]

    y += 28
    for desc, amount in items:
        page.insert_text((50, y), desc, fontsize=9)
        page.insert_text((430, y), amount, fontsize=9)
        y += 22

    y += 20
    page.insert_text((380, y), "Subtotal:", fontsize=10)
    page.insert_text((470, y), "$10,000.00", fontsize=10)
    y += 18
    page.insert_text((380, y), "Tax (7%):", fontsize=10)
    page.insert_text((470, y), "$700.00", fontsize=10)
    y += 20
    page.draw_line((370, y - 2), (555, y - 2), color=(0.4, 0.15, 0.1), width=1.5)
    page.insert_text((380, y + 8), "TOTAL:", fontsize=12, fontname="helv", color=(0.4, 0.15, 0.1))
    page.insert_text((470, y + 8), "$10,700.00", fontsize=12, fontname="helv", color=(0.4, 0.15, 0.1))

    output_path = OUTPUT_DIR / "demo4_missing_invoice_number.pdf"
    doc.save(str(output_path))
    doc.close()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    print("Generating synthetic test invoices...")
    create_clean_invoice()
    create_low_quality_scan()
    create_arithmetic_mismatch()
    create_missing_field_invoice()
    print("Done! 4 test invoices created.")

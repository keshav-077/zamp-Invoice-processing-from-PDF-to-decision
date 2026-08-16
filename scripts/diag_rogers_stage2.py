"""Diagnostic: Stage 2 scoring for Rogers clean extraction (no LLM)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.extraction import InvoiceExtraction, FieldExtraction, LineItem
from app.pipeline.stage2.orchestrator import Stage2Orchestrator
from app.pipeline.stage2.evidence_scorer import EvidenceScorer

lines = [
    ("Giant 50'S Christmas Cracker", 1, 2.89, 2.89),
    ("Set 12 Colour Pencils Spaceboy", 7, 0.65, 4.55),
    ("Heart Ivory Trellis Large", 4, 1.65, 6.60),
    ("Baking Mould Heart White Chocolate", 10, 2.55, 25.50),
    ("Grow Your Own Flowers Set Of 3", 9, 7.95, 71.55),
    ("Edwardian Parasol Black", 10, 12.46, 124.60),
    ("Plasters In Tin Vintage Paisley", 8, 1.65, 13.20),
]

ext = InvoiceExtraction(
    vendor_name=FieldExtraction(value="Rogers, Smith and Hobbs", confidence=0.9, status="extracted"),
    invoice_number=FieldExtraction(value="229655", confidence=0.95, status="extracted"),
    invoice_date=FieldExtraction(value="1987-05-16", confidence=0.95, status="extracted"),
    currency=FieldExtraction(value="USD", confidence=0.99, status="inferred"),
    subtotal=FieldExtraction(value=248.89, confidence=0.95, status="extracted"),
    tax_amount=FieldExtraction(value=48.04, confidence=0.95, status="extracted"),
    total_amount=FieldExtraction(value=300.46, confidence=0.95, status="extracted"),
    po_reference=FieldExtraction(value=None, confidence=0, status="not_found"),
    line_items=[
        LineItem(description=d, quantity=q, unit_price=u, amount=a, confidence=0.9)
        for d, q, u, a in lines
    ],
)

s2 = Stage2Orchestrator()
pkg = s2.match("diag-clean", ext, suggestion_mode=True)
print("match_status:", pkg.match_status)
candidates = pkg.suggested_candidates or pkg.matched_pos or []
for i, c in enumerate(candidates[:5]):
    print(f"  #{i+1} {c.po_number} score={c.score.total:.0f} po={c.score.po_match} vendor={c.score.vendor_match} lines={c.score.line_match} amt={c.score.amount_match} date={c.score.date_match}")

scorer = EvidenceScorer()
print("isolated amount score (300.46 vs 10000 remaining):", scorer._score_amount(300.46, 10000.0))

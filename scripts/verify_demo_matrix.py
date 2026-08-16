"""
Verify demo matrix expectations against pipeline runs.

Usage (from invoiceflow-ai/):
  python scripts/verify_demo_matrix.py --offline
  python scripts/verify_demo_matrix.py
  python scripts/verify_demo_matrix.py --duplicate
  python scripts/verify_demo_matrix.py --file d2.jpg
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEMO_FILES = ROOT / "test_invoices" / "dataset"
SPLIT_FILES = ROOT / "test_invoices" / "split_billing"
CATALOG = ROOT / "data" / "invoice_catalog.json"
PO_XLSX = ROOT / "data" / "PO.xlsx"

# Strict expectations for five primary PS-1 scenarios
EXPECTATIONS: dict[str, dict] = {
    "d2.jpg": {
        "stage2": {"matched", "high_confidence_match"},
        "stage3": {"VALIDATED"},
        "stage4": {"AUTO_APPROVED", "APPROVAL_REQUIRED"},
        "strict": True,
    },
    "d8.jpg": {
        "stage2": {"ambiguous_match"},
        "stage3": {"VALIDATED", "HOLD", "REVIEW_REQUIRED"},
        "stage4": {"REVIEW_REQUIRED"},
        "strict": True,
    },
    "d14.jpg": {
        "stage2": {"matched", "high_confidence_match", "partial_match", "ambiguous_match"},
        "stage3": {"HOLD"},
        "stage4": {"REVIEW_REQUIRED"},
        "strict": True,
    },
    "split_billing_part2.pdf": {
        "stage2": {"matched", "high_confidence_match"},
        "stage3": {"VALIDATED", "HOLD"},
        "stage4": {"AUTO_APPROVED", "APPROVAL_REQUIRED"},
        "strict": True,
        "path": SPLIT_FILES / "split_billing_part2.pdf",
    },
    "d9.jpg": {
        "stage2": {"matched", "high_confidence_match"},
        "stage3": {"VALIDATED", "HOLD"},
        "stage4": {"AUTO_APPROVED", "APPROVAL_REQUIRED"},
        "strict": True,
    },
    "rogers_crumpled.png": {
        "stage2": {"matched", "high_confidence_match"},
        "stage3": {"VALIDATED", "HOLD"},
        "stage4": {"AUTO_APPROVED", "APPROVAL_REQUIRED"},
        "strict": False,
        "path": DEMO_FILES / "rogers_crumpled.png",
    },
}


def offline_checks() -> bool:
    ok = True
    for path, label in [
        (CATALOG, "invoice_catalog.json"),
        (PO_XLSX, "PO.xlsx"),
        (DEMO_FILES, "test_invoices/dataset/"),
        (SPLIT_FILES / "split_billing_part2.pdf", "split_billing_part2.pdf"),
        (DEMO_FILES / "rogers_crumpled.png", "rogers_crumpled.png"),
    ]:
        if not path.exists():
            print(f"FAIL missing {label}: {path}")
            ok = False
        else:
            print(f"OK   {label}")
    if CATALOG.exists():
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        print(f"OK   catalog entries: {len(data.get('invoices', []))}")
    if DEMO_FILES.exists():
        files = list(DEMO_FILES.glob("*"))
        print(f"OK   dataset copies: {len(files)}")
    return ok


async def run_file(path: Path) -> dict:
    from app.pipeline.orchestrator import PipelineOrchestrator
    from app.db import repository
    from app.providers.factory import get_provider

    provider = get_provider()
    orchestrator = PipelineOrchestrator(provider)
    result = await orchestrator.process_invoice(path)
    repository.save_run(result)
    return {
        "document_id": result.document_id,
        "status": result.status,
        "stage2": result.stage2_status,
        "stage3": result.stage3_status,
        "stage4": result.stage4_decision,
        "stage4_substate": result.stage4_status,
        "time_s": round(result.processing_time_seconds, 1),
    }


def check_result(filename: str, outcome: dict) -> bool:
    exp = EXPECTATIONS.get(filename)
    if not exp:
        print(f"  SKIP no expectations for {filename}")
        return True
    ok = True
    strict = exp.get("strict", False)
    s2 = outcome.get("stage2") or ""
    s3 = outcome.get("stage3") or ""
    s4 = outcome.get("stage4") or ""

    if s2 not in exp["stage2"]:
        level = "FAIL" if strict else "WARN"
        print(f"  {level} stage2: got {s2!r}, expected one of {exp['stage2']}")
        if strict:
            ok = False
    if s3 and s3 not in exp["stage3"]:
        level = "FAIL" if strict else "WARN"
        print(f"  {level} stage3: got {s3!r}, expected one of {exp['stage3']}")
        if strict:
            ok = False
    if s4 and s4 not in exp["stage4"]:
        level = "FAIL" if strict else "WARN"
        print(f"  {level} stage4: got {s4!r}, expected one of {exp['stage4']}")
        if strict:
            ok = False
    if ok:
        print(f"  PASS stage2={s2} stage3={s3} stage4={s4} ({outcome.get('time_s')}s)")
    return ok


async def run_duplicate_test() -> bool:
    """Upload d9.jpg twice; second submission should be blocked as duplicate."""
    path = DEMO_FILES / "d9.jpg"
    if not path.exists():
        print("\nduplicate test: MISSING d9.jpg")
        return False
    print("\nduplicate test (d9.jpg x2):")
    first = await run_file(path)
    print(f"  first:  stage4={first.get('stage4')}")
    second = await run_file(path)
    s3 = second.get("stage3") or ""
    s4 = second.get("stage4") or ""
    blocked = s3 == "HOLD" or s4 in ("TERMINAL_REJECT", "REVIEW_REQUIRED")
    if blocked:
        print(f"  PASS duplicate blocked: stage3={s3} stage4={s4}")
        return True
    print(f"  FAIL duplicate not blocked: stage3={s3} stage4={s4}")
    return False


async def run_split_billing_setup() -> bool:
    """Process part 1 so part 2 validates against remaining balance."""
    part1 = SPLIT_FILES / "split_billing_part1.pdf"
    if not part1.exists():
        print("\n  SKIP split part1 — run scripts/generate_split_billing_pdfs.py")
        return True
    print("\nsplit billing part 1 (setup):")
    outcome = await run_file(part1)
    print(f"  part1: stage2={outcome.get('stage2')} stage4={outcome.get('stage4')}")
    return True


def reset_db() -> None:
    from app.db.database import close_db, init_db
    from app.db.seed_data import seed_database
    from app.config import settings

    close_db()
    db_path = settings.db_path
    if db_path.exists():
        db_path.unlink()
    init_db()
    seed_database()


async def main_async(args: argparse.Namespace) -> int:
    if args.offline:
        return 0 if offline_checks() else 1

    if not offline_checks():
        return 1

    print("\nResetting database...")
    reset_db()
    from app.db.database import get_connection

    conn = get_connection()
    print(f"  Seeded {conn.execute('SELECT COUNT(*) FROM vendors').fetchone()[0]} vendors")

    all_ok = True

    if args.duplicate or not args.file:
        if not await run_duplicate_test():
            all_ok = False
        reset_db()
        print("\nRe-seeded after duplicate test")

    if SPLIT_FILES.joinpath("split_billing_part2.pdf").exists():
        await run_split_billing_setup()

    targets = [args.file] if args.file else [
        k for k in EXPECTATIONS if k != "d9.jpg" or args.file
    ]
    if not args.file:
        targets = ["d2.jpg", "d8.jpg", "d14.jpg", "split_billing_part2.pdf"]

    for name in targets:
        exp = EXPECTATIONS.get(name, {})
        path = exp.get("path") or DEMO_FILES / name
        if not path.exists():
            print(f"\n{name}: MISSING at {path}")
            all_ok = False
            continue
        print(f"\n{name}:")
        try:
            outcome = await run_file(path)
            if not check_result(name, outcome):
                all_ok = False
        except Exception as exc:
            print(f"  FAIL pipeline error: {exc}")
            all_ok = False

    return 0 if all_ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify demo matrix")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--duplicate", action="store_true", help="Run duplicate block test")
    parser.add_argument("--file", type=str, default="")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

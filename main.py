import argparse
import shutil
import sys
from pathlib import Path

import anthropic
import yaml

from cache import load_results, save_results
from extractor import extract_invoice_info, extract_payment_info
from journal import generate_csv
from matcher import match_payments
from merger import merge_pdfs
from orderer import order_payments


def _preflight(
    merged_dir: Path,
    payments_ordered_dir: Path,
    csv_path: Path,
    clean: bool,
    journal_only: bool = False,
    match_cache_path: Path = None,
) -> None:
    output_dirs = [merged_dir, payments_ordered_dir]

    missing = [d for d in output_dirs if not d.exists()]
    if not csv_path.parent.exists():
        missing.append(csv_path.parent)
    if missing:
        for d in missing:
            print(f"Error: output directory does not exist: {d}", file=sys.stderr)
        sys.exit(1)

    if clean:
        if not journal_only:
            for d in output_dirs:
                for item in d.iterdir():
                    print(f"  removing {item}")
                    item.unlink() if item.is_file() else shutil.rmtree(item)
            if match_cache_path and match_cache_path.exists():
                print(f"  removing {match_cache_path}")
                match_cache_path.unlink()
        if csv_path.exists():
            print(f"  removing {csv_path}")
            csv_path.unlink()
        return

    if journal_only:
        empty_dirs = [str(d) for d in output_dirs if not any(d.iterdir())]
        if empty_dirs:
            print("Error: --journal-only requires output from a completed run; these directories are empty:", file=sys.stderr)
            for d in empty_dirs:
                print(f"  {d}", file=sys.stderr)
            sys.exit(1)
        if match_cache_path and not match_cache_path.exists():
            print(f"Error: {match_cache_path} not found — run without --journal-only first.", file=sys.stderr)
            sys.exit(1)
        if csv_path.exists():
            print(f"Error: {csv_path} already exists. Use --clean to remove it.", file=sys.stderr)
            sys.exit(1)
    else:
        conflicts = [str(d) for d in output_dirs if any(d.iterdir())]
        if csv_path.exists():
            conflicts.append(str(csv_path))
        if conflicts:
            print("Error: output from a previous run already exists:", file=sys.stderr)
            for c in conflicts:
                print(f"  {c}", file=sys.stderr)
            print("Use --clean to remove existing output before running.", file=sys.stderr)
            sys.exit(1)


def load_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="fibutool — bookkeeping PDF processor")
    parser.add_argument(
        "--last-receipt-number", type=int, required=True, metavar="N",
        help="Last used receipt number (next receipt will be N+1)",
    )
    parser.add_argument(
        "--workdir", type=Path, default=Path("."),
        help="Working directory containing payments/, invoices/, merged/, payments-ordered/ and journal.csv (default: .)",
    )
    parser.add_argument(
        "--config", type=Path, default=Path("config.yaml"),
        help="Config file (default: ./config.yaml)",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Remove existing output files before running",
    )
    parser.add_argument(
        "--journal-only", action="store_true",
        help="Skip extraction, matching, and merging; regenerate journal.csv from the match cache written by a previous run",
    )
    args = parser.parse_args()

    workdir = args.workdir
    payments_dir = workdir / "payments"
    invoices_dir = workdir / "invoices"
    payments_ordered_dir = workdir / "payments-ordered"
    merged_dir = workdir / "merged"
    csv_path = workdir / "journal.csv"
    match_cache_path = workdir / "match_results.json"

    _preflight(merged_dir, payments_ordered_dir, csv_path, args.clean,
               journal_only=args.journal_only, match_cache_path=match_cache_path)

    if args.journal_only:
        # ── Journal-only mode: load cached match results, regenerate CSV ──────
        print(f"Loading match cache from {match_cache_path}...")
        results = load_results(match_cache_path)
        print(f"  {len(results)} match result(s) loaded.")
    else:
        config = load_config(args.config)
        own_company_names: list[str] = config.get("own_company_names", [])
        api_key: str = config.get("anthropic_api_key") or ""
        client = anthropic.Anthropic(api_key=api_key or None)

        payment_pdfs = sorted(p for p in payments_dir.glob("*.pdf"))
        invoice_pdfs = sorted(p for p in invoices_dir.glob("*.pdf"))

        if not payment_pdfs:
            print(f"Error: no PDF files found in {payments_dir}", file=sys.stderr)
            sys.exit(1)

        # ── Step 1: Extract + order payments ─────────────────────────────────
        print(f"Step 1: Extracting {len(payment_pdfs)} payment(s)...")
        payments = []
        for pdf_path in payment_pdfs:
            print(f"  {pdf_path.name} ... ", end="", flush=True)
            try:
                info = extract_payment_info(pdf_path, client, own_company_names)
                payments.append(info)
                print(f"{info.booking_date}  {info.currency} {info.amount}  [{info.direction}]  {info.counterparty}")
            except Exception as e:
                print(f"ERROR: {e}", file=sys.stderr)

        if not payments:
            print("Error: no payments could be extracted.", file=sys.stderr)
            sys.exit(1)

        sorted_payments = order_payments(payments_ordered_dir, args.last_receipt_number, payments)
        print(f"  → {len(sorted_payments)} payments written to {payments_ordered_dir}/")

        # ── Step 2: Extract invoices + match ──────────────────────────────────
        print(f"\nStep 2: Extracting {len(invoice_pdfs)} invoice(s)...")
        invoices = []
        for pdf_path in invoice_pdfs:
            print(f"  {pdf_path.name} ... ", end="", flush=True)
            try:
                info = extract_invoice_info(pdf_path, client)
                invoices.append(info)
                print(f"{info.invoice_date}  {info.currency} {info.amount}  {info.counterparty}")
            except Exception as e:
                print(f"ERROR: {e}", file=sys.stderr)

        if invoice_pdfs and not invoices:
            print("Warning: no invoices could be extracted — all payments will be unmatched.", file=sys.stderr)

        print("  Matching payments to invoices...")
        results = match_payments(sorted_payments, invoices, client)

        save_results(results, match_cache_path)
        print(f"  Match cache saved → {match_cache_path}")

        # ── Step 3: Merge PDFs ────────────────────────────────────────────────
        print(f"\nStep 3: Merging PDFs into {merged_dir}/...")
        for result in results:
            out = merge_pdfs(result, merged_dir)
            if result.invoice:
                print(f"  {out.name}  ←  {result.invoice.pdf_path.name}")
            else:
                print(f"  {out.name}  ⚠  no invoice matched")

    # ── Step 4: CSV journal ──────────────────────────────────────────────────
    generate_csv(results, csv_path)
    print(f"\nStep 4: Journal written → {csv_path}")

    # ── Summary ──────────────────────────────────────────────────────────────
    warnings = [w for r in results for w in r.warnings]
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  ⚠  {w}")

    matched = sum(1 for r in results if r.invoice)
    print(f"\nDone — {matched}/{len(results)} payments matched to invoices.")


if __name__ == "__main__":
    main()

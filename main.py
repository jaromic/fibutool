import argparse
import sys
from pathlib import Path

import anthropic
import yaml

from extractor import extract_invoice_info, extract_payment_info
from journal import generate_csv
from matcher import match_payments
from merger import merge_pdfs
from orderer import order_payments


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
        "--payments", type=Path, default=Path("payments"),
        help="Folder with payment receipt PDFs (default: ./payments)",
    )
    parser.add_argument(
        "--invoices", type=Path, default=Path("invoices"),
        help="Folder with invoice PDFs (default: ./invoices)",
    )
    parser.add_argument(
        "--merged", type=Path, default=Path("merged"),
        help="Directory for merged invoice+payment PDFs (default: ./merged)",
    )
    parser.add_argument(
        "--journal", type=Path, default=Path("."),
        help="Journal output: directory (journal.csv placed inside) or full file path (default: ./journal.csv)",
    )
    parser.add_argument(
        "--config", type=Path, default=Path("config.yaml"),
        help="Config file (default: ./config.yaml)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    own_company_names: list[str] = config.get("own_company_names", [])
    api_key: str = config.get("anthropic_api_key") or ""
    client = anthropic.Anthropic(api_key=api_key or None)

    payments_ordered_dir = Path("payments-ordered")
    merged_dir = args.merged
    csv_path = args.journal / "journal.csv" if not args.journal.suffix else args.journal

    payment_pdfs = sorted(p for p in args.payments.glob("*.pdf"))
    invoice_pdfs = sorted(p for p in args.invoices.glob("*.pdf"))

    if not payment_pdfs:
        print(f"Error: no PDF files found in {args.payments}", file=sys.stderr)
        sys.exit(1)

    # ── Step 1: Extract + order payments ─────────────────────────────────────
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

    # ── Step 2: Extract invoices + match ─────────────────────────────────────
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

    # ── Step 3: Merge PDFs ───────────────────────────────────────────────────
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

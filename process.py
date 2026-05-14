"""fibutool — bookkeeping PDF processor.

Two-directory model
-------------------
App directory  — shared across all sessions; holds config and the installed executable.
               Default: same directory as this script (process.py)
               Override with:   --config <path>

Work directory — per-session; holds input PDFs, output files, log, and intermediary data.
               Default: current working directory (cd into the session folder, then run fibutool)
               Override with:   --workdir <path>
"""

import argparse
import shutil
import sys
from pathlib import Path

import anthropic
import yaml

from cache import load_all_invoices, load_results, save_results
from extractor import (
    apply_percentage_rules,
    extract_invoice_info,
    extract_payment_info,
    validate_category_rules,
    validate_business_percentage_rules,
    validate_position_business_rules,
    validate_extracted_positions,
)
from journal import generate_csv
from matcher import match_payments
from merger import merge_pdfs
from models import InvoiceInfo, MatchResult
from orderer import order_payments
from shared import Tee, default_config_path, setup_logging

try:
    from importlib.metadata import version as _pkg_version
    _VERSION = _pkg_version("fibutool")
except Exception:
    _VERSION = "dev"


# ── Preflight ────────────────────────────────────────────────────────────────

def _preflight(
    merged_dir: Path,
    payments_ordered_dir: Path,
    csv_path: Path,
    clean: bool,
    journal_only: bool = False,
    resume: bool = False,
    match_cache_path: Path = None,
) -> None:
    output_dirs = [merged_dir, payments_ordered_dir]

    missing = [d for d in output_dirs if not d.exists()]
    if not csv_path.parent.exists():
        missing.append(csv_path.parent)
    if missing:
        for d in missing:
            print(f"fibutool: output directory does not exist: {d}", file=sys.stderr)
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
            print("fibutool: --journal-only requires output from a completed run; these directories are empty:", file=sys.stderr)
            for d in empty_dirs:
                print(f"  {d}", file=sys.stderr)
            sys.exit(1)
        if match_cache_path and not match_cache_path.exists():
            print(f"fibutool: {match_cache_path} not found — run without --journal-only first.", file=sys.stderr)
            sys.exit(1)
        if csv_path.exists():
            print(f"fibutool: {csv_path} already exists; use --clean to remove it.", file=sys.stderr)
            sys.exit(1)
    elif not resume:
        conflicts = [str(d) for d in output_dirs if any(d.iterdir())]
        if csv_path.exists():
            conflicts.append(str(csv_path))
        if conflicts:
            print("fibutool: output from a previous run already exists:", file=sys.stderr)
            for c in conflicts:
                print(f"  {c}", file=sys.stderr)
            print("Use --clean to remove existing output before running.", file=sys.stderr)
            sys.exit(1)


# ── Argument parsing and configuration ───────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fibutool",
        description="fibutool — bookkeeping PDF processor",
    )
    parser.add_argument(
        "--version", "-V", action="version", version=f"%(prog)s {_VERSION}",
    )
    parser.add_argument(
        "--last-receipt-number", "-n", type=int, default=None, metavar="N",
        help="Last used receipt number (next receipt will be N+1); required unless --journal-only",
    )
    parser.add_argument(
        "--workdir", "-w", type=Path, default=Path("."), metavar="DIR",
        # Work directory: per-session data, logs, and intermediary files.
        # Defaults to the current directory so you can cd into the session folder and run fibutool.
        help="Work directory: per-session PDFs, output files, and logs (default: current directory)",
    )
    parser.add_argument(
        "--config", "-c", type=Path, default=None, metavar="FILE",
        # App directory: shared config, survives across sessions.
        help=f"Config file (default: {default_config_path()})",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Remove existing output files before running",
    )
    parser.add_argument(
        "--journal-only", action="store_true",
        help="Skip extraction, matching, and merging; regenerate journal.csv from the match cache written by a previous run",
    )
    parser.add_argument(
        "--only-payment", metavar="FILE", type=Path, default=None,
        help="Process only this payment PDF instead of all files in payments/",
    )
    parser.add_argument(
        "--only-invoice", metavar="FILE", type=Path, default=None,
        help="Process only this invoice PDF instead of all files in invoices/",
    )
    return parser.parse_args()


def _load_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _validate_config(config: dict) -> None:
    try:
        validate_category_rules(config.get("category_rules", {}))
        validate_business_percentage_rules(config.get("business_percentage_rules", {}))
        validate_position_business_rules(config.get("position_business_rules", {}))
    except ValueError as e:
        print(f"fibutool: config error — {e}", file=sys.stderr)
        sys.exit(1)


# ── Pipeline helpers ─────────────────────────────────────────────────────────

def _glob_pdfs(directory: Path) -> list[Path]:
    """Return sorted PDF paths from directory, case-insensitively (.pdf and .PDF)."""
    return sorted(p for p in directory.iterdir() if p.suffix.lower() == ".pdf")

def _extract_invoices(
    pdf_paths: list[Path],
    client,
    category_rules: dict,
    position_business_rules: dict,
    default_ausgaben_category: str = "sonstige Betriebsausgaben",
    default_einnahmen_category: str = "Waren-/Leistungserlöse",
    own_company_names: list[str] | None = None,
) -> tuple[list[InvoiceInfo], list[str]]:
    """Extract invoice info from PDFs. Returns (invoices, warnings)."""
    invoices, warnings = [], []
    for pdf_path in pdf_paths:
        print(f"  {pdf_path.name} ... ", end="", flush=True)
        try:
            info = extract_invoice_info(
                pdf_path, client, category_rules, position_business_rules,
                default_ausgaben_category, default_einnahmen_category,
                own_company_names=own_company_names,
            )
            invoices.append(info)
            print(f"{info.invoice_date}  {info.currency} {info.gross_total}  {info.counterparty}")
            warnings.extend(validate_extracted_positions(info))
        except Exception as e:
            print(f"FAILED: {e}")
            warnings.append(f"[main] {pdf_path.name}: invoice extraction failed: {e}")
    return invoices, warnings


def _full_mode(
    args,
    payments_dir: Path,
    invoices_dir: Path,
    payments_ordered_dir: Path,
    match_cache_path: Path,
    client,
    config: dict,
) -> tuple[list[MatchResult], list[str]]:
    own_company_names: list[str] = config.get("own_company_names", [])
    category_rules: dict = config.get("category_rules", {})
    business_percentage_rules: dict = config.get("business_percentage_rules", {})
    position_business_rules: dict = config.get("position_business_rules", {})

    if args.only_payment:
        if not args.only_payment.exists():
            print(f"fibutool: --only-payment file not found: {args.only_payment}", file=sys.stderr)
            sys.exit(1)
        payment_pdfs = [args.only_payment]
    else:
        payment_pdfs = _glob_pdfs(payments_dir)

    if args.only_invoice:
        if not args.only_invoice.exists():
            print(f"fibutool: --only-invoice file not found: {args.only_invoice}", file=sys.stderr)
            sys.exit(1)
        invoice_pdfs = [args.only_invoice]
    else:
        invoice_pdfs = _glob_pdfs(invoices_dir)

    if not payment_pdfs:
        print(f"fibutool: no PDF files found in {payments_dir}", file=sys.stderr)
        sys.exit(1)

    # Step 1: Extract + order payments
    print(f"Step 1: Extracting {len(payment_pdfs)} payment(s)...")
    payments = []
    payment_warnings: list[str] = []
    for pdf_path in payment_pdfs:
        print(f"  {pdf_path.name} ... ", end="", flush=True)
        try:
            info = extract_payment_info(pdf_path, client, own_company_names)
            payments.append(info)
            print(f"{info.booking_date}  {info.currency} {info.amount}  [{info.direction}]  {info.counterparty}")
            if info.direction == "incoming" and any(
                name.lower() in info.counterparty.lower() for name in own_company_names
            ):
                payment_warnings.append(
                    f"[extractor] {pdf_path.name}: incoming payment has own company name as counterparty"
                    f" — LLM likely extracted our account name instead of the sender's name"
                )
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)

    if not payments:
        print("fibutool: no payments could be extracted.", file=sys.stderr)
        sys.exit(1)

    sorted_payments = order_payments(payments_ordered_dir, args.last_receipt_number, payments)
    print(f"  → {len(sorted_payments)} payments written to {payments_ordered_dir}/")

    default_ausgaben_category: str = config.get("default_ausgaben_category", "sonstige Betriebsausgaben")
    default_einnahmen_category: str = config.get("default_einnahmen_category", "Waren-/Leistungserlöse")

    # Step 2: Extract invoices + match
    print(f"\nStep 2: Extracting {len(invoice_pdfs)} invoice(s)...")
    invoices, invoice_warnings = _extract_invoices(
        invoice_pdfs, client, category_rules, position_business_rules,
        default_ausgaben_category, default_einnahmen_category,
        own_company_names=own_company_names,
    )

    if invoice_pdfs and not invoices:
        print("Warning: no invoices could be extracted — all payments will be unmatched.", file=sys.stderr)

    print("  Matching payments to invoices...")
    results = match_payments(sorted_payments, invoices, client)
    for result in results:
        if result.invoice:
            result.business_percentage = apply_percentage_rules(
                result.invoice.counterparty, business_percentage_rules
            )

    save_results(results, match_cache_path, all_invoices=invoices)
    print(f"  Match cache saved → {match_cache_path}")

    return results, payment_warnings + invoice_warnings


def _resume_mode(
    invoices_dir: Path,
    match_cache_path: Path,
    client,
    config: dict,
) -> tuple[list[MatchResult], list[str]]:
    category_rules: dict = config.get("category_rules", {})
    business_percentage_rules: dict = config.get("business_percentage_rules", {})
    position_business_rules: dict = config.get("position_business_rules", {})

    print(f"Resume mode — loading previous results from {match_cache_path}")
    prev_results = load_results(match_cache_path)
    prev_invoices = load_all_invoices(match_cache_path)

    already_seen_names = {inv.pdf_path.name for inv in prev_invoices}
    new_invoice_pdfs = [p for p in _glob_pdfs(invoices_dir) if p.name not in already_seen_names]

    default_ausgaben_category: str = config.get("default_ausgaben_category", "sonstige Betriebsausgaben")
    default_einnahmen_category: str = config.get("default_einnahmen_category", "Waren-/Leistungserlöse")
    own_company_names: list[str] = config.get("own_company_names", [])

    print(f"\nStep 2: Extracting {len(new_invoice_pdfs)} new invoice(s)...")
    new_invoices, warnings = _extract_invoices(
        new_invoice_pdfs, client, category_rules, position_business_rules,
        default_ausgaben_category, default_einnahmen_category,
        own_company_names=own_company_names,
    )

    all_invoices = prev_invoices + new_invoices
    unmatched = [r for r in prev_results if r.invoice is None]

    if unmatched:
        already_matched_names = {r.invoice.pdf_path.name for r in prev_results if r.invoice is not None}
        available_invoices = [inv for inv in all_invoices if inv.pdf_path.name not in already_matched_names]
        print(f"  Re-matching {len(unmatched)} previously unmatched payment(s) against {len(available_invoices)} available invoice(s)...")
        rematched = match_payments([r.payment for r in unmatched], available_invoices, client)
        for result in rematched:
            if result.invoice:
                result.business_percentage = apply_percentage_rules(
                    result.invoice.counterparty, business_percentage_rules
                )
        rematched_by_path = {r.payment.pdf_path: r for r in rematched}
    else:
        rematched_by_path = {}

    results = [
        rematched_by_path.get(r.payment.pdf_path, r) if r.invoice is None else r
        for r in prev_results
    ]

    save_results(results, match_cache_path, all_invoices=all_invoices)
    print(f"  Match cache updated → {match_cache_path}")

    return results, warnings


def _do_merge_pdfs(results: list[MatchResult], merged_dir: Path, decimal_separator: str) -> None:
    print(f"\nStep 3: Merging PDFs into {merged_dir}/...")
    for result in results:
        out = merge_pdfs(result, merged_dir, decimal_separator)
        if result.invoice:
            print(f"  {out.name}  ←  {result.invoice.pdf_path.name}")
        else:
            print(f"  {out.name}  ⚠  no invoice matched")


def _print_summary(results: list[MatchResult], warnings: list[str]) -> None:
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  ⚠  {w}")
    matched = sum(1 for r in results if r.invoice)
    print(f"\nDone — {matched}/{len(results)} payments matched to invoices.")


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    args = _parse_args()
    workdir = args.workdir
    match_cache_path = workdir / "match_results.json"
    is_resume = match_cache_path.exists() and not args.clean and not args.journal_only

    if not args.journal_only and not is_resume and args.last_receipt_number is None:
        print("fibutool: error — --last-receipt-number / -n is required unless --journal-only is set or resuming from cache", file=sys.stderr)
        sys.exit(2)

    setup_logging(workdir, "fibutool")

    config_path = args.config if args.config is not None else default_config_path()
    print(f"fibutool {_VERSION}  |  config: {config_path}  |  workdir: {workdir.resolve()}")

    payments_dir      = workdir / "payments"
    invoices_dir      = workdir / "invoices"
    payments_ordered_dir = workdir / "payments-ordered"
    merged_dir        = workdir / "merged"
    csv_path          = workdir / "journal.csv"

    _preflight(merged_dir, payments_ordered_dir, csv_path, args.clean,
               journal_only=args.journal_only, resume=is_resume, match_cache_path=match_cache_path)

    config = _load_config(config_path)
    mixed_vat_label: str       = config.get("mixed_vat_label", "gemischt")
    decimal_separator: str     = config.get("decimal_separator", ",")
    ig_vat_rate: int           = config.get("ig_vat_rate", 20)
    default_einnahmen_category = config.get("default_einnahmen_category", "Waren-/Leistungserlöse")
    default_ausgaben_category  = config.get("default_ausgaben_category", "sonstige Betriebsausgaben")

    if args.journal_only:
        print(f"Loading match cache from {match_cache_path}...")
        results = load_results(match_cache_path)
        print(f"  {len(results)} match result(s) loaded.")
        warnings: list[str] = []
    else:
        _validate_config(config)
        # Anthropic API client — shared across all extraction and matching calls
        client = anthropic.Anthropic(api_key=config.get("anthropic_api_key") or None)

        if is_resume:
            results, warnings = _resume_mode(invoices_dir, match_cache_path, client, config)
        else:
            results, warnings = _full_mode(
                args, payments_dir, invoices_dir, payments_ordered_dir, match_cache_path, client, config
            )

        _do_merge_pdfs(results, merged_dir, decimal_separator)

    # Step 4: CSV journal
    generate_csv(results, csv_path, mixed_vat_label, decimal_separator, ig_vat_rate,
                 default_einnahmen_category, default_ausgaben_category)
    print(f"\nStep 4: Journal written → {csv_path}")

    warnings += [w for r in results for w in r.warnings]
    _print_summary(results, warnings)


if __name__ == "__main__":
    main()

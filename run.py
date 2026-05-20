"""run.py — fibutool session orchestrator.

Reads the last receipt number and latest payment date from the original journal,
prompts the user to download bank payment receipts, then runs fetcher and fibutool.

Stages
------
1. Read journal  → last receipt number N, fetcher since date X
2. User prompt   → download bank payment receipts since X into payments/
3. fetcher       → download invoices automatically
4. fibutool      → extract, match, merge, journal
"""

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path
from shutil import copy2

import yaml

from shared import default_config_path, setup_logging


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run",
        description="run — fibutool session orchestrator",
    )
    parser.add_argument(
        "--workdir", "-w", type=Path, default=Path("."), metavar="DIR",
        help="Work directory for this session (default: current directory)",
    )
    parser.add_argument(
        "--config", "-c", type=Path, default=None, metavar="FILE",
        help=f"Config file (default: {default_config_path()})",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Remove previous run output and force a full run (passed through to fibutool-process)",
    )
    parser.add_argument(
        "--non-interactive", "-y", action="store_true",
        help="Skip interactive prompts (Stage 2 user confirmation); stage failures abort immediately",
    )
    return parser.parse_args()


def _prompt_manual_journal_state() -> int:
    """Prompt the user to enter receipt number manually.

    Returns last_receipt_number. Aborts the process on Ctrl+C, reprompts on invalid receipt number.
    """
    last_receipt_number: int | None = None
    while last_receipt_number is None:
        try:
            last_receipt_number = int(input("  Enter last receipt number manually: ").strip())
        except KeyboardInterrupt:
            print("\nAborted.", file=sys.stderr)
            sys.exit(1)
        except ValueError:
            print("  Invalid last receipt number — please enter an integer.")


def _prompt_arc(stage: str, non_interactive: bool = False) -> str:
    """Prompt the user for abort / retry / continue after a stage failure."""
    if non_interactive:
        print(f"\n[{stage}] failed. Non-interactive mode — aborting.", file=sys.stderr)
        return "abort"
    while True:
        try:
            choice = input(f"\n[{stage}] failed. [a]bort / [r]etry / [c]ontinue? ").strip().lower()
        except EOFError:
            return "abort"
        if choice in ("a", "abort"):
            return "abort"
        if choice in ("r", "retry"):
            return "retry"
        if choice in ("c", "continue"):
            return "continue"
        print("  Please enter 'a', 'r', or 'c'.")


def _run_stage(label: str, cmd: list[str]) -> bool:
    """Run a subprocess stage, streaming output through the parent Tee. Returns True on success."""
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        bufsize=1,
    ) as proc:
        for line in proc.stdout:
            sys.stdout.write(line)
        proc.wait()
        returncode = proc.returncode
    if returncode != 0:
        print(f"\n  Exit code: {returncode}", file=sys.stderr)
    return returncode == 0


def main() -> None:
    args = _parse_args()
    non_interactive = args.non_interactive
    workdir = args.workdir.resolve()
    setup_logging(workdir, "run")
    config_path = (args.config if args.config is not None else default_config_path()).resolve()

    with open(config_path, encoding="utf-8") as f:
        try:
            config = yaml.safe_load(f)
        except yaml.scanner.ScannerError as e:
            print(f"Config file formatting error: {e}", file=sys.stderr)
            sys.exit(1)

    here = Path(__file__).parent
    fetcher_cmd_base = [sys.executable, str(here / "fetcher.py"),
                        "--workdir", str(workdir), "--config", str(config_path)]
    fibutool_cmd_base = [sys.executable, str(here / "process.py"),
                         "--workdir", str(workdir), "--config", str(config_path)]

    # ── Stage 1: read journal ─────────────────────────────────────────────────
    from journal_reader import read_journal_state

    last_receipt_number: int | None = None
    last_payment_date: date | None = None

    while True:
        try:
            entries, last_receipt_year, last_receipt_number, last_payment_date = read_journal_state(config)
            print(f"\nJournal state:")
            print(f"  Last receipt year:   {last_receipt_year}")
            print(f"  Last receipt number: {last_receipt_number}")
            print(f"  Latest payment date: {last_payment_date}")
            print(f"\n  Latest 5 journal entries:\n")
            for (year, receipt_number, payment_date, description, amount) in entries[-5:]:
                print(f"   {year}-{receipt_number:03d}  {payment_date}  {amount: 7.2f}  {description}")
            break
        except Exception as e:
            print(f"\njournal_reader error: {e}", file=sys.stderr)
            choice = _prompt_arc("journal read", non_interactive)
            if choice == "abort":
                sys.exit(1)
            elif choice == "retry":
                continue
            else:  # continue — fall back to manual entry
                last_receipt_number = _prompt_manual_journal_state()
                break

    # ── Stage 2: user downloads payment receipts ──────────────────────────────
    payments_dir = workdir / "payments"
    if non_interactive:
        if not payments_dir.exists():
            print(f"Non-interactive mode: payments directory {payments_dir}/ not found — aborting.", file=sys.stderr)
            sys.exit(1)
        if not (any(payments_dir.glob("*.pdf")) or any(payments_dir.glob("*.PDF"))):
            print(f"Non-interactive mode: no PDF files found in {payments_dir}/ — aborting.", file=sys.stderr)
            sys.exit(1)
        print(f"\nNon-interactive mode: payments directory confirmed ({payments_dir})")
    else:
        if last_payment_date:
            print(f"\nPlease download all bank payment receipts since {last_payment_date}")
        else:
            print(f"\nPlease download all bank payment receipts")
        print(f"and place them in:  {payments_dir}")
        while True:
            try:
                input("\nPress Enter when done (Ctrl+C to abort)...")
            except KeyboardInterrupt:
                print("\nAborted.", file=sys.stderr)
                sys.exit(1)
            if not payments_dir.exists():
                print(f"  Directory {payments_dir}/ does not exist — please create it and add payment receipts.")
            elif not (any(payments_dir.glob("*.pdf")) or any(payments_dir.glob("*.PDF"))):
                print(f"  No PDF files found in {payments_dir}/ — please add payment receipts and try again.")
            else:
                break

    # ── Stage 3: fetcher ──────────────────────────────────────────────────────
    if args.clean:
        seen_registry_path = workdir / "fetcher_seen.json"
        print(f"  removing {seen_registry_path}")
        seen_registry_path.unlink(missing_ok=True)
        for f in (workdir / "invoices").glob("*_fetched*.pdf", case_sensitive=False):
            print(f"  removing {f.name}")
            f.unlink(missing_ok=True)

    fetcher_cmd = fetcher_cmd_base
    if last_payment_date:
        fetcher_cmd = fetcher_cmd_base + ["--anchor-date", str(last_payment_date)]
    while True:
        if _run_stage("fetcher — downloading invoices", fetcher_cmd):
            break
        choice = _prompt_arc("fetcher", non_interactive)
        if choice == "abort":
            sys.exit(1)
        elif choice == "continue":
            break
        # retry: loop

    # ── Stage 4: fibutool ─────────────────────────────────────────────────────
    match_results = workdir / "match_results.json"
    if match_results.exists() and not args.clean:
        print("\nResuming from existing match_results.json  (run with --clean to start fresh)")
        fibutool_cmd = fibutool_cmd_base
    else:
        fibutool_cmd = fibutool_cmd_base + ["-n", str(last_receipt_number)]
        if args.clean:
            fibutool_cmd += ["--clean"]
    while True:
        if _run_stage("fibutool — processing session", fibutool_cmd):
            break
        choice = _prompt_arc("fibutool", non_interactive)
        if choice == "abort":
            sys.exit(1)
        elif choice == "continue":
            break
        # retry: loop

    # ── Stage 5: journal updater ──────────────────────────────────────────────
    updater_cmd = [sys.executable, str(here / "journal_updater.py"),
                   "--workdir", str(workdir), "--config", str(config_path)]
    while True:
        if _run_stage("journal updater — appending entries to Excel workbook", updater_cmd):
            break
        choice = _prompt_arc("journal updater", non_interactive)
        if choice == "abort":
            sys.exit(1)
        elif choice == "continue":
            break
        # retry: loop

    # ── Stage 6: copy merged receipts to permanent storage ────────────────────
    permanent_merged_dir_str = config.get("original_journal",{}).get("permanent_merged_dir")
    n_copied = n_skipped = 0

    if permanent_merged_dir_str:
        permanent_merged_dir = Path(permanent_merged_dir_str).expanduser()
        if permanent_merged_dir.exists():
            for merged_receipt in (workdir / "merged").glob("*.pdf", case_sensitive=False):
                target_path = permanent_merged_dir / merged_receipt.name
                if not target_path.exists():
                    copy2(merged_receipt, target_path)
                    n_copied += 1
                else:
                    print(f"'{merged_receipt.name}' already exists in '{permanent_merged_dir}', skipping.")
                    n_skipped += 1
        else:
            print(f"Permanent merge dir '{permanent_merged_dir}' does not exist, not copying merged files.")
    else:
        print(f"Permanent merge dir not configured, not copying merged files.")

    print(f"{n_copied} files copied. {n_skipped} files skipped.")

if __name__ == "__main__":
    main()

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
from datetime import date, timedelta
from pathlib import Path

import yaml


def _default_config_path() -> Path:
    return Path(__file__).parent / "config.yaml"


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
        help=f"Config file (default: {_default_config_path()})",
    )
    return parser.parse_args()


def _prompt_manual_journal_state() -> tuple[int, str]:
    """Prompt the user to enter receipt number and since date manually.

    Returns (receipt_number, since_str). Aborts the process on Ctrl+C or
    invalid receipt number. Re-prompts until a valid YYYY-MM-DD date is entered.
    """
    receipt_number: int | None = None
    while receipt_number is None:
        try:
            receipt_number = int(input("  Enter last receipt number manually: ").strip())
        except KeyboardInterrupt:
            print("\nAborted.", file=sys.stderr)
            sys.exit(1)
        except ValueError:
            print("  Invalid receipt number — please enter an integer.")

    while True:
        try:
            since_str = input("  Enter fetcher since date (YYYY-MM-DD): ").strip()
            date.fromisoformat(since_str)
            return receipt_number, since_str
        except KeyboardInterrupt:
            print("\nAborted.", file=sys.stderr)
            sys.exit(1)
        except ValueError:
            print(f"  Invalid date '{since_str}' — expected YYYY-MM-DD, please try again.")


def _prompt_arc(stage: str) -> str:
    """Prompt the user for abort / retry / continue after a stage failure."""
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
    """Run a subprocess stage. Returns True on success."""
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")
    return subprocess.run(cmd).returncode == 0


def main() -> None:
    args = _parse_args()
    workdir = args.workdir.resolve()
    config_path = (args.config if args.config is not None else _default_config_path()).resolve()

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

    receipt_number: int | None = None
    since_str: str | None = None

    while True:
        try:
            receipt_number, last_payment_date = read_journal_state(config)
            offset = int(config.get("original_journal", {}).get("since_offset_days", 14))
            since_date = last_payment_date - timedelta(days=offset)
            since_str = str(since_date)
            print(f"\nJournal state:")
            print(f"  Last receipt number : {receipt_number}")
            print(f"  Latest payment date : {last_payment_date}")
            print(f"  Fetcher since date  : {since_date}  (offset: -{offset} days)")
            break
        except Exception as e:
            print(f"\njournal_reader error: {e}", file=sys.stderr)
            choice = _prompt_arc("journal read")
            if choice == "abort":
                sys.exit(1)
            elif choice == "retry":
                continue
            else:  # continue — fall back to manual entry
                receipt_number, since_str = _prompt_manual_journal_state()
                break

    # ── Stage 2: user downloads payment receipts ──────────────────────────────
    payments_dir = workdir / "payments"
    print(f"\nPlease download all bank payment receipts since {since_str}")
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
    fetcher_cmd = fetcher_cmd_base + ["--since", since_str]
    while True:
        if _run_stage("fetcher — downloading invoices", fetcher_cmd):
            break
        choice = _prompt_arc("fetcher")
        if choice == "abort":
            sys.exit(1)
        elif choice == "continue":
            break
        # retry: loop

    # ── Stage 4: fibutool ─────────────────────────────────────────────────────
    fibutool_cmd = fibutool_cmd_base + ["-n", str(receipt_number)]
    while True:
        if _run_stage("fibutool — processing session", fibutool_cmd):
            break
        choice = _prompt_arc("fibutool")
        if choice == "abort":
            sys.exit(1)
        elif choice == "continue":
            break
        # retry: loop


if __name__ == "__main__":
    main()

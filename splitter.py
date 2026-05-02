"""
Split merged PDFs (invoice pages first, payment receipt last) back into
separate invoice and payment PDFs.  Intended for test-data generation.

Reads all PDFs from the merged/ subdirectory of --workdir.
Writes results into payments/ and invoices/ subdirectories of --workdir.
All three subdirectories must exist; payments/ and invoices/ must be empty.

Usage:
    python splitter.py
    python splitter.py --workdir test_data/
"""

import argparse
import random
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def _strip_prefix(stem: str) -> str:
    """Remove the NNN_YYYY-MM-DD_ prefix added by the orderer, returning the original name."""
    parts = stem.split("_")
    return "_".join(parts[2:]) if len(parts) > 2 else stem


def split_merged_pdf(
    merged_path: Path, payments_dir: Path, invoices_dir: Path
) -> tuple[Path | None, Path]:
    """
    Split one merged PDF into (invoice_path, payment_path).

    The last page is always the payment receipt; all preceding pages are the invoice.
    Payment filename: original name with orderer prefix stripped.
    Invoice filename: inv<10 random digits>.pdf
    Returns (None, payment_path) when the input has only one page (no invoice).
    """
    reader = PdfReader(merged_path)
    n = len(reader.pages)

    payment_name = _strip_prefix(merged_path.stem)
    payment_writer = PdfWriter()
    payment_writer.add_page(reader.pages[-1])
    payment_path = payments_dir / f"{payment_name}.pdf"
    with open(payment_path, "wb") as f:
        payment_writer.write(f)

    invoice_path = None
    if n > 1:
        invoice_writer = PdfWriter()
        for page in reader.pages[:-1]:
            invoice_writer.add_page(page)
        invoice_path = invoices_dir / f"inv{random.randint(0, 9_999_999_999):010d}.pdf"
        with open(invoice_path, "wb") as f:
            invoice_writer.write(f)

    return invoice_path, payment_path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="splitter",
        description="Split merged PDFs into separate invoice and payment files",
    )
    parser.add_argument(
        "--workdir", "-w", type=Path, default=Path("."), metavar="DIR",
        help="Working directory containing merged/, payments/, and invoices/ (default: .)",
    )
    args = parser.parse_args()

    merged_dir  = args.workdir / "merged"
    payments_dir = args.workdir / "payments"
    invoices_dir = args.workdir / "invoices"

    if not merged_dir.exists():
        print(f"splitter: input directory does not exist: {merged_dir}", file=sys.stderr)
        sys.exit(1)

    merged_pdfs = sorted(merged_dir.glob("*.pdf"))
    if not merged_pdfs:
        print(f"splitter: no PDF files found in {merged_dir}", file=sys.stderr)
        sys.exit(1)

    for d in (payments_dir, invoices_dir):
        if not d.exists():
            print(f"splitter: output directory does not exist: {d}", file=sys.stderr)
            sys.exit(1)

    for d in (payments_dir, invoices_dir):
        if any(d.iterdir()):
            print(f"splitter: output directory is not empty: {d}", file=sys.stderr)
            sys.exit(1)

    for merged_path in merged_pdfs:
        invoice_path, payment_path = split_merged_pdf(merged_path, payments_dir, invoices_dir)

        if invoice_path:
            print(f"{merged_path.name}  →  {invoice_path.name}  +  {payment_path.name}")
        else:
            print(f"{merged_path.name}  →  {payment_path.name}  (single page, no invoice)")


if __name__ == "__main__":
    main()

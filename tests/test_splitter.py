import sys
import re
from io import BytesIO
from pathlib import Path
from pypdf import PdfReader, PdfWriter

sys.path.insert(0, str(Path(__file__).parent.parent))
from splitter import _strip_prefix, split_merged_pdf


def make_pdf(pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestStripPrefix:
    def test_numeric_prefix(self):
        assert _strip_prefix("001_2024-01-15_receipt") == "receipt"

    def test_year_receipt_prefix(self):
        assert _strip_prefix("2025-130_2025-03-21_receipt") == "receipt"

    def test_original_name_with_underscores(self):
        assert _strip_prefix("001_2024-01-15_my_bank_receipt") == "my_bank_receipt"

    def test_no_prefix(self):
        assert _strip_prefix("receipt") == "receipt"


class TestSplitMergedPdf:
    def test_split_single_page(self, tmp_path):

        merged = tmp_path / "2026-001_2026-01-15_receipt.pdf"
        merged.write_bytes(make_pdf(1))
        payments_dir = tmp_path / "payments"
        invoices_dir = tmp_path / "invoices"
        payments_dir.mkdir()
        invoices_dir.mkdir()

        invoice_path, payment_path = split_merged_pdf(merged, payments_dir, invoices_dir)

        assert invoice_path is None
        assert payment_path.exists()
        assert payment_path.name == 'receipt.pdf'
        assert PdfReader(payment_path).get_num_pages() == 1
        assert list(invoices_dir.iterdir()) == []

    def test_split_multi_page(self, tmp_path):

        merged = tmp_path / "2026-001_2026-01-15_receipt.pdf"
        merged.write_bytes(make_pdf(3))
        payments_dir = tmp_path / "payments"
        invoices_dir = tmp_path / "invoices"
        payments_dir.mkdir()
        invoices_dir.mkdir()

        invoice_path, payment_path = split_merged_pdf(merged, payments_dir, invoices_dir)

        assert payment_path.name == 'receipt.pdf'
        assert invoice_path is not None
        assert invoice_path.exists()
        assert re.match(r'inv\d{10}\.pdf', invoice_path.name)
        assert payment_path.exists()
        assert PdfReader(invoice_path).get_num_pages() == 2
        assert PdfReader(payment_path).get_num_pages() == 1

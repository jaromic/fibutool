from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from merger import merge_pdfs
from models import InvoiceInfo, InvoicePosition, MatchResult, PaymentInfo


def make_pdf(pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def make_payment(tmp_path: Path, name: str = "payment.pdf") -> PaymentInfo:
    pdf_path = tmp_path / name
    pdf_path.write_bytes(make_pdf(1))
    return PaymentInfo(
        booking_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        currency="EUR",
        counterparty="Acme GmbH",
        direction="outgoing",
        pdf_path=pdf_path,
        ordered_path=pdf_path,
    )


def make_invoice(tmp_path: Path, name: str = "invoice.pdf", pages: int = 1) -> InvoiceInfo:
    pdf_path = tmp_path / name
    pdf_path.write_bytes(make_pdf(pages))
    return InvoiceInfo(
        invoice_date=date(2026, 1, 10),
        gross_total=Decimal("100.00"),
        currency="EUR",
        counterparty="Acme GmbH",
        pdf_path=pdf_path,
    )


def test_merge_without_invoice(tmp_path):
    payment = make_payment(tmp_path)
    result = MatchResult(payment=payment, invoice=None)
    merged_dir = tmp_path / "merged"

    output = merge_pdfs(result, merged_dir)

    assert output.exists()
    assert PdfReader(output).get_num_pages() == 1


def test_merge_with_invoice(tmp_path):
    payment = make_payment(tmp_path)
    invoice = make_invoice(tmp_path, pages=2)
    result = MatchResult(payment=payment, invoice=invoice)
    merged_dir = tmp_path / "merged"

    output = merge_pdfs(result, merged_dir)

    assert output.exists()
    assert PdfReader(output).get_num_pages() == 3  # 2 invoice + 1 payment


def test_merge_with_overview(tmp_path):
    payment = make_payment(tmp_path)
    invoice = make_invoice(tmp_path)
    invoice.positions = [
        InvoicePosition(
            description="Business item",
            net_amount=Decimal("50.00"),
            vat_rate=20,
            vat_amount=Decimal("10.00"),
            gross_amount=Decimal("60.00"),
            is_business=True,
        ),
        InvoicePosition(
            description="Private item",
            net_amount=Decimal("30.00"),
            vat_rate=20,
            vat_amount=Decimal("6.00"),
            gross_amount=Decimal("36.00"),
            is_business=False,
        ),
    ]
    result = MatchResult(payment=payment, invoice=invoice)
    merged_dir = tmp_path / "merged"

    output = merge_pdfs(result, merged_dir)

    assert output.exists()
    # 1 invoice page + 1 overview page + 1 payment page
    assert PdfReader(output).get_num_pages() == 3

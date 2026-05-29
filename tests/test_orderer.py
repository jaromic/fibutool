from datetime import date
from decimal import Decimal
from pathlib import Path

from models import PaymentInfo
from orderer import order_payments

def make_payment(name: str, direction: str = "outgoing") -> PaymentInfo:
    return PaymentInfo(
        booking_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        currency="EUR",
        counterparty="Acme GmbH",
        direction=direction,
        pdf_path=Path(name),
    )

def test_empty_list(tmp_path):
    assert order_payments(
        payments_ordered_dir=tmp_path / "payments_ordered_dir",
        last_receipt_number=0,
        payments=[]) == []

def test_single_payment(tmp_path):
    payments=[make_payment(name="payment1.pdf", direction="outgoing")]
    (tmp_path / "payments_ordered_dir").mkdir()
    (tmp_path / "payment1.pdf").write_text("dummy text")
    ordered_payments=order_payments(
        payments_ordered_dir=tmp_path / "payments_ordered_dir",
        last_receipt_number=2,
        payments=payments,
        workdir=tmp_path)
    assert ordered_payments[0].ordered_path.name.endswith("payment1.pdf")
    assert ordered_payments[0].ordered_path.name.startswith(f"{payments[0].booking_date.year}-003")
    assert ordered_payments[0].receipt_number==3

def test_multiple_payments(tmp_path):
    payments=[
        make_payment(name="payment1.pdf", direction="incoming"),
        make_payment(name="payment2.pdf", direction="outgoing")
    ]
    payments[0].booking_date=date(2026, 1, 15)
    payments[1].booking_date = date(2026, 1, 14)
    (tmp_path / "payments_ordered_dir").mkdir()
    (tmp_path / "payment1.pdf").write_text("dummy text 1")
    (tmp_path / "payment2.pdf").write_text("dummy text 2")
    ordered_payments=order_payments(
        payments_ordered_dir=tmp_path / "payments_ordered_dir",
        last_receipt_number=0,
        payments=payments,
        workdir=tmp_path)
    assert ordered_payments[0].ordered_path.name.endswith("payment2.pdf")
    assert ordered_payments[1].ordered_path.name.endswith("payment1.pdf")
    assert ordered_payments[0].ordered_path.name.startswith(f"{ordered_payments[0].booking_date.year}-001")
    assert ordered_payments[1].ordered_path.name.startswith(f"{ordered_payments[1].booking_date.year}-002")
    assert ordered_payments[0].receipt_number==1
    assert ordered_payments[1].receipt_number==2

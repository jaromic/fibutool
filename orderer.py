import shutil
from pathlib import Path

from models import PaymentInfo


def order_payments(
    payments_ordered_dir: Path,
    last_receipt_number: int,
    payments: list[PaymentInfo],
    workdir: Path = Path("."),
) -> list[PaymentInfo]:
    sorted_payments = sorted(payments, key=lambda p: (p.booking_date, p.pdf_path.name))

    receipt_num = last_receipt_number + 1
    for payment in sorted_payments:
        new_name = (
            f"{payment.booking_date.year}-{receipt_num:03d}_{payment.booking_date.isoformat()}_{payment.pdf_path.name}"
        )
        dest = payments_ordered_dir / new_name
        shutil.copy2(workdir / payment.pdf_path, dest)
        payment.ordered_path = dest
        payment.receipt_number = receipt_num
        receipt_num += 1

    return sorted_payments

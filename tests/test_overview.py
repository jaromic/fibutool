from datetime import date
from decimal import Decimal
from pathlib import Path

from models import InvoiceInfo, InvoicePosition
from overview import generate_overview_pdf


def _invoice_with_positions():
    positions = [
        InvoicePosition("Büroanteil", Decimal("83.33"), 20, Decimal("16.67"), Decimal("100.00"), is_business=True),
        InvoicePosition("Privatanteil", Decimal("750.00"), 20, Decimal("150.00"), Decimal("900.00"), is_business=False),
    ]
    return InvoiceInfo(
        invoice_date=date(2024, 3, 1),
        amount=Decimal("1000.00"),
        currency="EUR",
        counterparty="Marktgemeinde Bisamberg",
        pdf_path=Path("invoice.pdf"),
        positions=positions,
        business_percentage=10.0,
    )


class TestGenerateOverviewPdf:
    def test_returns_pdf_bytes(self):
        result = generate_overview_pdf(_invoice_with_positions())
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"

    def test_non_empty(self):
        result = generate_overview_pdf(_invoice_with_positions())
        assert len(result) > 1000

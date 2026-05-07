from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional


@dataclass
class InvoicePosition:
    description: str
    net_amount: Decimal
    vat_rate: int        # percentage 0-100
    vat_amount: Decimal
    gross_amount: Decimal
    is_business: bool = True


@dataclass
class PaymentInfo:
    booking_date: date
    amount: Decimal
    currency: str
    counterparty: str
    direction: str          # 'outgoing' | 'incoming'
    pdf_path: Path
    address: Optional[str] = None
    ordered_path: Optional[Path] = None
    receipt_number: Optional[int] = None
    forex_fee: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class InvoiceInfo:
    invoice_date: date
    gross_total: Decimal
    currency: str
    counterparty: str
    pdf_path: Path
    invoice_type: str = "incoming_invoice"  # incoming_invoice | outgoing_invoice | credit_note
    address: Optional[str] = None
    country: Optional[str] = None           # supplier country in German, e.g. "Österreich"
    vat_rate: Optional[int] = None          # VAT percentage 0-100 as shown on the invoice
    net_total: Optional[Decimal] = None     # net total from invoice summary, if shown
    positions: list["InvoicePosition"] = field(default_factory=list)
    detail_category: Optional[str] = None
    afa: bool = False
    matched: bool = False


@dataclass
class MatchResult:
    payment: PaymentInfo
    invoice: Optional[InvoiceInfo]
    match_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    business_percentage: float = 100.0

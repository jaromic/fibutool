from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional


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


@dataclass
class InvoiceInfo:
    invoice_date: date
    amount: Decimal
    currency: str
    counterparty: str
    pdf_path: Path
    address: Optional[str] = None
    matched: bool = False


@dataclass
class MatchResult:
    payment: PaymentInfo
    invoice: Optional[InvoiceInfo]
    match_reason: str = ""
    warnings: list = field(default_factory=list)

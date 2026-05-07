import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from models import InvoiceInfo, InvoicePosition, MatchResult, PaymentInfo


class _Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, Path):
            return obj.as_posix()
        return super().default(obj)


def _path(s: str) -> Path:
    return Path(s.replace("\\", "/"))


def _position_from_dict(d: dict) -> InvoicePosition:
    return InvoicePosition(
        description=d["description"],
        net_amount=Decimal(d["net_amount"]),
        vat_rate=int(d["vat_rate"]),
        vat_amount=Decimal(d["vat_amount"]),
        gross_amount=Decimal(d["gross_amount"]),
        is_business=d.get("is_business", True),
    )


def _invoice_from_dict(d: dict) -> InvoiceInfo:
    raw_gross = d["gross_total"]
    raw_net = d.get("net_total")
    return InvoiceInfo(
        invoice_date=date.fromisoformat(d["invoice_date"]),
        gross_total=Decimal(raw_gross),
        net_total=Decimal(raw_net) if raw_net is not None else None,
        currency=d["currency"],
        counterparty=d["counterparty"],
        pdf_path=_path(d["pdf_path"]),
        invoice_type=d.get("invoice_type", "incoming_invoice"),
        address=d.get("address"),
        country=d.get("country"),
        vat_rate=d.get("vat_rate"),
        positions=[_position_from_dict(p) for p in d.get("positions", [])],
        detail_category=d.get("detail_category"),
        afa=d.get("afa", False),
        matched=d.get("matched", False),
    )


def _payment_from_dict(d: dict) -> PaymentInfo:
    return PaymentInfo(
        booking_date=date.fromisoformat(d["booking_date"]),
        amount=Decimal(d["amount"]),
        currency=d["currency"],
        counterparty=d["counterparty"],
        direction=d["direction"],
        forex_fee=Decimal(d.get("forex_fee", "0")),
        pdf_path=_path(d["pdf_path"]),
        address=d.get("address"),
        ordered_path=_path(d["ordered_path"]) if d.get("ordered_path") else None,
        receipt_number=d.get("receipt_number"),
    )


def save_results(
    results: list[MatchResult],
    path: Path,
    all_invoices: list[InvoiceInfo] | None = None,
) -> None:
    data = {
        "matches": [asdict(r) for r in results],
        "invoices": [asdict(inv) for inv in (all_invoices or [])],
    }
    path.write_text(json.dumps(data, indent=2, cls=_Encoder), encoding="utf-8")


def load_all_invoices(path: Path) -> list[InvoiceInfo]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return [_invoice_from_dict(d) for d in raw.get("invoices", [])]
    return []


def load_results(path: Path) -> list[MatchResult]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["matches"] if isinstance(raw, dict) else raw
    return [
        MatchResult(
            payment=_payment_from_dict(item["payment"]),
            invoice=_invoice_from_dict(item["invoice"]) if item["invoice"] else None,
            match_reason=item.get("match_reason", ""),
            warnings=item.get("warnings", []),
            business_percentage=float(
                item.get("business_percentage")
                or (item["invoice"].get("business_percentage", 100.0) if item.get("invoice") else 100.0)
            ),
        )
        for item in items
    ]

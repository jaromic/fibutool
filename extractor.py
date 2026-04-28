import base64
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import anthropic

from models import InvoiceInfo, PaymentInfo

PAYMENT_SYSTEM_PROMPT = """\
You extract structured data from Austrian bank payment receipt PDFs.
Respond with a single JSON object only — no markdown, no explanation.

Fields:
- booking_date: the "Buchungsdatum" (booking date) in ISO format YYYY-MM-DD
- amount: transaction amount as decimal string with dot as separator, always positive (e.g. "1234.56")
- currency: 3-letter currency code (e.g. "EUR")
- counterparty: name of the other party (recipient for outgoing payments, sender for incoming)
- direction: "outgoing" if money left our account, "incoming" if money entered our account
- street: street address of the counterparty, or null if not shown
- postal_code: postal code of the counterparty, or null if not shown
- town: town/city of the counterparty, or null if not shown
- country: country of the counterparty, or null if not shown\
"""

INVOICE_SYSTEM_PROMPT = """\
You extract structured data from invoice PDFs.
Respond with a single JSON object only — no markdown, no explanation.

Fields:
- invoice_date: invoice date in ISO format YYYY-MM-DD
- amount: total amount including VAT as decimal string with dot as separator, always positive (e.g. "1234.56")
- currency: 3-letter currency code (e.g. "EUR")
- counterparty: the other company's name (issuer for bills we received, recipient for invoices we sent)
- street: street address of the counterparty, or null if not shown
- postal_code: postal code of the counterparty, or null if not shown
- town: town/city of the counterparty, or null if not shown
- country: country of the counterparty, or null if not shown\
"""


def _parse_amount(raw: str) -> Decimal:
    s = raw.strip().replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rindex(",") > s.rindex("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"Cannot parse amount: {raw!r}") from e


def _parse_json(text: str) -> dict:
    # Strip markdown code fences if the model wraps output despite instructions
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(stripped)


def _format_address(data: dict) -> Optional[str]:
    street = data.get("street")
    postal_code = data.get("postal_code")
    town = data.get("town")
    country = data.get("country")
    parts = []
    if street:
        parts.append(street)
    if postal_code and town:
        parts.append(f"{postal_code} {town}")
    elif town:
        parts.append(town)
    elif postal_code:
        parts.append(postal_code)
    if country:
        parts.append(country)
    return ", ".join(parts) if parts else None


def _call_claude(pdf_path: Path, client: anthropic.Anthropic, system_prompt: str) -> dict:
    pdf_data = base64.standard_b64encode(pdf_path.read_bytes()).decode("utf-8")
    document = {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
    }
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": [document]}],
    )
    return _parse_json(response.content[0].text)


def extract_payment_info(
    pdf_path: Path,
    client: anthropic.Anthropic,
    own_company_names: list[str],
) -> PaymentInfo:
    data = _call_claude(pdf_path, client, PAYMENT_SYSTEM_PROMPT)
    counterparty = data["counterparty"]
    direction = data.get("direction", "outgoing")
    if any(name.lower() in counterparty.lower() for name in own_company_names):
        direction = "incoming"
    return PaymentInfo(
        booking_date=date.fromisoformat(data["booking_date"]),
        amount=_parse_amount(data["amount"]),
        currency=data["currency"].upper(),
        counterparty=counterparty,
        address=_format_address(data),
        direction=direction,
        pdf_path=pdf_path,
    )


def extract_invoice_info(pdf_path: Path, client: anthropic.Anthropic) -> InvoiceInfo:
    data = _call_claude(pdf_path, client, INVOICE_SYSTEM_PROMPT)
    return InvoiceInfo(
        invoice_date=date.fromisoformat(data["invoice_date"]),
        amount=_parse_amount(data["amount"]),
        currency=data["currency"].upper(),
        counterparty=data["counterparty"],
        address=_format_address(data),
        pdf_path=pdf_path,
    )

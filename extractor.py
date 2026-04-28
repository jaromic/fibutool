import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import anthropic
import pdfplumber

from models import InvoiceInfo, PaymentInfo

PAYMENT_SYSTEM_PROMPT = """\
You extract structured data from Austrian bank payment receipt PDFs.
Respond with a single JSON object only — no markdown, no explanation.

Fields:
- booking_date: the "Buchungsdatum" (booking date) in ISO format YYYY-MM-DD
- amount: transaction amount as decimal string with dot as separator, always positive (e.g. "1234.56")
- currency: 3-letter currency code (e.g. "EUR")
- counterparty: name of the other party (recipient for outgoing payments, sender for incoming)
- direction: "outgoing" if money left our account, "incoming" if money entered our account\
"""

INVOICE_SYSTEM_PROMPT = """\
You extract structured data from invoice PDFs.
Respond with a single JSON object only — no markdown, no explanation.

Fields:
- invoice_date: invoice date in ISO format YYYY-MM-DD
- amount: total amount including VAT as decimal string with dot as separator, always positive (e.g. "1234.56")
- currency: 3-letter currency code (e.g. "EUR")
- counterparty: the other company's name (issuer for bills we received, recipient for invoices we sent)\
"""


def extract_pdf_text(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n\n--- PAGE BREAK ---\n\n".join(p for p in pages if p.strip())
    if not text.strip():
        raise ValueError(
            f"No text extracted from {pdf_path.name} — may be a scanned PDF requiring OCR"
        )
    return text


def _parse_amount(raw: str) -> Decimal:
    s = raw.strip().replace(" ", "").replace(" ", "")
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


def extract_payment_info(
    pdf_path: Path,
    client: anthropic.Anthropic,
    own_company_names: list[str],
) -> PaymentInfo:
    text = extract_pdf_text(pdf_path)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": PAYMENT_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": f"PDF text:\n\n{text}"}],
    )
    data = _parse_json(response.content[0].text)
    counterparty = data["counterparty"]
    direction = data.get("direction", "outgoing")
    if any(name.lower() in counterparty.lower() for name in own_company_names):
        direction = "incoming"
    return PaymentInfo(
        booking_date=date.fromisoformat(data["booking_date"]),
        amount=_parse_amount(data["amount"]),
        currency=data["currency"].upper(),
        counterparty=counterparty,
        direction=direction,
        pdf_path=pdf_path,
    )


def extract_invoice_info(pdf_path: Path, client: anthropic.Anthropic) -> InvoiceInfo:
    text = extract_pdf_text(pdf_path)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": INVOICE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": f"PDF text:\n\n{text}"}],
    )
    data = _parse_json(response.content[0].text)
    return InvoiceInfo(
        invoice_date=date.fromisoformat(data["invoice_date"]),
        amount=_parse_amount(data["amount"]),
        currency=data["currency"].upper(),
        counterparty=data["counterparty"],
        pdf_path=pdf_path,
    )

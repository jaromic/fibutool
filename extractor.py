import base64
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import anthropic

from models import InvoiceInfo, InvoicePosition, PaymentInfo

PAYMENT_SYSTEM_PROMPT = """\
You extract structured data from Austrian bank payment receipt PDFs.
Respond with a single JSON object only — no markdown, no explanation.

Fields:
- booking_date: the "Buchungsdatum" (booking date) in ISO format YYYY-MM-DD
- amount: transaction amount as decimal string with dot as separator, always positive (e.g. "1234.56")
- currency: 3-letter currency code (e.g. "EUR")
- counterparty: name of the other party (recipient for outgoing payments, sender for incoming)
- direction: "outgoing" if money left our account, "incoming" if money entered our account.
  Key indicator: a minus sign on the amount means debit (we paid → "outgoing");
  no minus sign / positive amount means credit (we received → "incoming")
- forex_fee: foreign currency fee (Fremdwährungsentgelt) as a positive decimal string if shown
  separately on the receipt, otherwise "0"\
"""

DETAIL_CATEGORIES = [
    "Waren, Rohstoffe, Hilfsstoffe",
    "Fremdpersonal",
    "Personalaufwand",
    "GWG",
    "Abschreibung Anlagevermögen",
    "Instandhaltungen Gebäude",
    "Reise- und Fahrtspesen inkl. Kilometergeld und Diäten",
    "Tatsächliche KfZ-Kosten",
    "Miet- und Pachtaufwand, Leasing",
    "Lizenzgebühren",
    "Werbe- und Repräsentationsaufwand",
    "Zinsen und ähnliche Aufwendungen",
    "Pflichtversicherungsbeiträge",
    "betriebliche Spenden an Forschungs- und Lehreinrichtungen",
    "betriebliche Spenden an mildtätige Organisationen",
    "betriebliche Spenden an Umweltorganisationen und Tierheime",
    "betriebliche Spenden an freiwillige Feuerwehren",
    "Büromaterial",
    "Reinigungsmaterial",
    "Fachliteratur",
    "Seminargebühren",
    "Telefon/Internet",
    "Porto/Gebühren",
    "sonstige Betriebsausgaben",
    "Waren-/Leistungserlöse",
    "Übrige Erträge",
]

_CATEGORY_DEFAULT_INCOMING = "sonstige Betriebsausgaben"
_CATEGORY_DEFAULT_OUTGOING = "Waren-/Leistungserlöse"


def validate_category_rules(rules: dict[str, str]) -> None:
    invalid = [cat for cat in rules.values() if cat not in DETAIL_CATEGORIES]
    if invalid:
        lines = "\n".join(f"  {c!r}" for c in invalid)
        valid = "\n".join(f"  {c}" for c in DETAIL_CATEGORIES)
        raise ValueError(
            f"category_rules contains unknown categories:\n{lines}\n\nValid categories:\n{valid}"
        )


INVOICE_SYSTEM_PROMPT = """\
You extract structured data from invoice PDFs.
Respond with a single JSON object only — no markdown, no explanation.

Fields:
- invoice_date: invoice date in ISO format YYYY-MM-DD
- amount: total amount including VAT as decimal string with dot as separator, always positive (e.g. "1234.56")
- currency: 3-letter currency code (e.g. "EUR")
- invoice_type: classify the document —
    "incoming_invoice" if it is a bill/Rechnung addressed to us (we have to pay),
    "outgoing_invoice" if it is an invoice we issued to someone else (they pay us),
    "credit_note" if it is a Gutschrift/credit note sent to us by another company (we receive money)
- counterparty: the other company's name (issuer for incoming invoices and credit notes, recipient for outgoing invoices)
- street: street address of the counterparty, or null if not shown
- postal_code: postal code of the counterparty, or null if not shown
- town: town/city of the counterparty, or null if not shown
- country: full country name in German (e.g. "Österreich", "Deutschland", "Schweiz"), or null if not shown — never use ISO codes
- vat_rate: dominant VAT percentage as printed on the invoice, integer 0–100 (e.g. 20 for 20% VAT, 0 for reverse-charge / IG Leistung); use the rate that applies to the majority of the amount if mixed
- positions: array of all invoice line items, each with:
    - description: position text as printed
    - net_amount: net amount as decimal string with dot separator
    - vat_rate: VAT percentage for this position, integer 0–100
    - vat_amount: VAT amount as decimal string with dot separator
    - gross_amount: gross amount as decimal string with dot separator
- afa: true if this invoice is for a depreciable tangible asset (abnutzbares Wirtschaftsgut) that must be
    capitalised and depreciated — applies when net amount exceeds €1000 Anschaffungskosten, or for lower
    amounts if the asset is not independently usable as a GWG (geringwertiges Wirtschaftsgut);
    false for services, consumables, and assets that qualify as GWG\
"""


def _apply_category_rules(
    counterparty: str,
    invoice_type: str,
    rules: dict[str, str],
) -> str:
    cp_lower = counterparty.lower()
    for keyword, category in rules.items():
        if keyword.lower() in cp_lower:
            return category
    if invoice_type == "incoming_invoice":
        return _CATEGORY_DEFAULT_INCOMING
    return _CATEGORY_DEFAULT_OUTGOING


def _apply_percentage_rules(counterparty: str, rules: dict[str, float]) -> float:
    cp_lower = counterparty.lower()
    for keyword, pct in rules.items():
        if keyword.lower() in cp_lower:
            return pct
    return 100.0


def validate_business_percentage_rules(rules: dict[str, float]) -> None:
    invalid = {k: v for k, v in rules.items() if not isinstance(v, (int, float)) or not (0 < v <= 100)}
    if invalid:
        lines = "\n".join(f"  {k!r}: {v}" for k, v in invalid.items())
        raise ValueError(f"business_percentage_rules values must be numbers between 0 and 100:\n{lines}")


def _parse_amount(raw: str) -> Decimal:
    s = raw.strip().replace(" ", "").replace(" ", "")
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
    stripped = text.strip()
    # Strip markdown code fences if the model wraps output despite instructions
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    # Fast path: response is already pure JSON
    if stripped.startswith("{"):
        return json.loads(stripped)
    # Slow path: model prepended reasoning before the JSON object — extract it
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(stripped[start:end + 1])
        except json.JSONDecodeError:
            pass
    preview = text[:300].replace("\n", "\\n")
    raise ValueError(f"LLM returned non-JSON; response preview: {preview!r}")


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


def _parse_positions(raw: list) -> list[InvoicePosition]:
    positions = []
    for p in raw:
        try:
            positions.append(InvoicePosition(
                description=str(p.get("description", "")),
                net_amount=_parse_amount(str(p["net_amount"])),
                vat_rate=int(p["vat_rate"]),
                vat_amount=_parse_amount(str(p["vat_amount"])),
                gross_amount=_parse_amount(str(p["gross_amount"])),
            ))
        except (KeyError, ValueError):
            pass  # skip any malformed position rather than failing the whole invoice
    return positions


def _call_claude(
    pdf_path: Path,
    client: anthropic.Anthropic,
    system_prompt: str,
    max_tokens: int = 512,
) -> dict:
    pdf_data = base64.standard_b64encode(pdf_path.read_bytes()).decode("utf-8")
    document = {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
    }
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": [document]}],
    )
    if response.stop_reason == "max_tokens":
        raise ValueError(f"LLM response truncated (max_tokens={max_tokens} reached) — increase max_tokens or simplify the PDF")
    text_block = next((b.text for b in response.content if b.type == "text"), None)
    if not text_block:
        raise ValueError(f"LLM returned no text (stop_reason={response.stop_reason!r}, content types={[b.type for b in response.content]})")
    return _parse_json(text_block)


def extract_payment_info(
    pdf_path: Path,
    client: anthropic.Anthropic,
    own_company_names: list[str],
) -> PaymentInfo:
    data = _call_claude(pdf_path, client, PAYMENT_SYSTEM_PROMPT)
    counterparty = data["counterparty"]
    direction = data.get("direction", "outgoing")
    # Never override outgoing — a debit sign in the document is definitive even if our company
    # name appears in the counterparty field (e.g. a credit-card pull by a partner who names us).
    if direction != "outgoing" and any(name.lower() in counterparty.lower() for name in own_company_names):
        direction = "incoming"
    return PaymentInfo(
        booking_date=date.fromisoformat(data["booking_date"]),
        amount=_parse_amount(data["amount"]),
        currency=data["currency"].upper(),
        counterparty=counterparty,
        direction=direction,
        forex_fee=_parse_amount(data.get("forex_fee", "0")),
        pdf_path=pdf_path,
    )


def extract_invoice_info(
    pdf_path: Path,
    client: anthropic.Anthropic,
    category_rules: dict[str, str] | None = None,
    business_percentage_rules: dict[str, int] | None = None,
) -> InvoiceInfo:
    data = _call_claude(pdf_path, client, INVOICE_SYSTEM_PROMPT, max_tokens=4096)
    raw_vat = data.get("vat_rate")
    invoice_type = data.get("invoice_type", "incoming_invoice")
    counterparty = data["counterparty"]
    return InvoiceInfo(
        invoice_date=date.fromisoformat(data["invoice_date"]),
        amount=_parse_amount(data["amount"]),
        currency=data["currency"].upper(),
        counterparty=counterparty,
        invoice_type=invoice_type,
        address=_format_address(data),
        country=data.get("country"),
        vat_rate=int(raw_vat) if raw_vat is not None else None,
        positions=_parse_positions(data.get("positions") or []),
        detail_category=_apply_category_rules(counterparty, invoice_type, category_rules or {}),
        business_percentage=_apply_percentage_rules(counterparty, business_percentage_rules or {}),
        afa=bool(data.get("afa", False)),
        pdf_path=pdf_path,
    )

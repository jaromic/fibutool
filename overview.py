from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from models import InvoiceInfo

_DESC_MAX = 35


def _eur(d: Decimal, sep: str = ",") -> str:
    return str(d.quantize(Decimal("0.01"))).replace(".", sep) + " €"


def _truncate(text: str) -> str:
    return text if len(text) <= _DESC_MAX else text[:_DESC_MAX] + "…"


def generate_overview_pdf(invoice: InvoiceInfo, decimal_separator: str = ",") -> bytes:
    """Single-page PDF listing which positions are abzugsfähig (business) vs. privat."""
    sep = decimal_separator
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    elements: list = []

    elements.append(Paragraph("Auflistung der abzugsfähigen Positionen", styles["Heading1"]))
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(
        Paragraph(
            f"{invoice.counterparty} | {invoice.invoice_date.strftime('%d.%m.%Y')}",
            styles["Normal"],
        )
    )
    elements.append(Spacer(1, 0.6 * cm))

    biz_net   = sum(p.net_amount   for p in invoice.positions if p.is_business)
    biz_vat   = sum(p.vat_amount   for p in invoice.positions if p.is_business)
    biz_gross = sum(p.gross_amount for p in invoice.positions if p.is_business)

    # usable width: A4 21 cm − 4 cm margins = 17 cm
    col_widths = [6 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 3.5 * cm]

    header = ["Position", "Netto", "MwSt", "Brutto", "Klassifizierung"]
    rows = [header]
    for p in invoice.positions:
        rows.append([
            _truncate(p.description),
            _eur(p.net_amount, sep),
            _eur(p.vat_amount, sep),
            _eur(p.gross_amount, sep),
            "abzugsfähig" if p.is_business else "privat",
        ])
    rows.append(["Summe abzugsfähige Positionen", _eur(biz_net, sep), _eur(biz_vat, sep), _eur(biz_gross, sep), ""])

    n = len(rows)
    n_pos = len(invoice.positions)
    summary_row = n_pos + 1

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        # header
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D0D0D0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        # position rows
        ("GRID", (0, 0), (-1, n_pos), 0.4, colors.HexColor("#AAAAAA")),
        ("FONTNAME", (0, 1), (-1, n_pos), "Helvetica"),
        # right-align numeric columns
        ("ALIGN", (1, 0), (3, -1), "RIGHT"),
        ("ALIGN", (4, 0), (4, -1), "RIGHT"),
        # colour-code classification labels
        *[
            ("TEXTCOLOR", (4, i + 1), (4, i + 1),
             colors.HexColor("#006400") if invoice.positions[i].is_business else colors.HexColor("#990000"))
            for i in range(n_pos)
        ],
        # summary row
        ("LINEABOVE", (0, summary_row), (-1, summary_row), 1, colors.black),
        ("FONTNAME", (0, summary_row), (-1, summary_row), "Helvetica-Bold"),
        ("BACKGROUND", (0, summary_row), (-1, summary_row), colors.HexColor("#F0F0F0")),
        ("ALIGN", (1, summary_row), (3, summary_row), "RIGHT"),
    ]))
    elements.append(table)

    doc.build(elements)
    return buf.getvalue()

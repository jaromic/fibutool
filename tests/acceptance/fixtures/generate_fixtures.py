#!/usr/bin/env python3
"""
One-time generator for acceptance test fixture PDFs.
Run from project root: python tests/fixtures/acceptance/generate_fixtures.py
Produces 10 PDFs (5 invoices + 5 payment receipts) in pdfs/invoices and pdfs/payments.
"""

from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

HERE = Path(__file__).parent
INVOICES_DIR = HERE / "invoices"
PAYMENTS_DIR = HERE / "payments"

RECIPIENT_NAME = "J. Muster, IT-Dienstleistungen"
RECIPIENT_ADDR = "Testgasse 1, 1010 Wien, Österreich"
RECIPIENT_UID = "ATU12345678"
OUR_IBAN = "AT61 1904 3002 3457 3201"
OUR_BIC = "OPSKATWW"
BANK_NAME = "Österreichische Musterbank AG"

GREY_LIGHT = colors.HexColor("#f0f0f0")
GREY_MID = colors.HexColor("#cccccc")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def de(amount):
    """Format float as German decimal string without currency symbol."""
    s = f"{abs(amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if amount < 0 else "") + s


def de_eur(amount):
    return f"{de(amount)} €"


def build_styles():
    s = getSampleStyleSheet()

    def add(name, parent="Normal", **kw):
        s.add(ParagraphStyle(name, parent=s[parent], **kw))

    add("VendorName", fontSize=14, fontName="Helvetica-Bold", spaceAfter=2)
    add("DocTitle", fontSize=18, fontName="Helvetica-Bold", spaceAfter=6, alignment=TA_RIGHT)
    add("Small", fontSize=8, leading=11)
    add("SmallBold", fontSize=8, leading=11, fontName="Helvetica-Bold")
    add("SmallRight", fontSize=8, leading=11, alignment=TA_RIGHT)
    add("Right", alignment=TA_RIGHT)
    add("Bold", fontName="Helvetica-Bold")
    add("BoldRight", fontName="Helvetica-Bold", alignment=TA_RIGHT)
    add("Note", fontSize=8, leading=11, textColor=colors.HexColor("#555555"))
    return s


STYLES = build_styles()


def p(text, style="Normal"):
    return Paragraph(str(text), STYLES[style])


def sp(n=0.4):
    return Spacer(1, n * cm)


def hr():
    return HRFlowable(width="100%", thickness=0.5, color=GREY_MID, spaceAfter=4)


def table_style(header_rows=1):
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), GREY_LIGHT),
        ("FONTNAME", (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.3, GREY_MID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ])


def new_doc(path, margins=(1.8 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm)):
    return SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=margins[0], rightMargin=margins[1],
        topMargin=margins[2], bottomMargin=margins[3],
    )


# ---------------------------------------------------------------------------
# Invoice generators
# ---------------------------------------------------------------------------

def _positions_table(positions, currency="EUR", col_widths=None):
    """
    positions: list of (description, net, vat_rate, vat, gross)
    Returns a Table flowable.
    """
    fmt = (lambda x: f"${x:,.2f}") if currency == "USD" else de_eur
    header = ["Beschreibung", "Netto", "MwSt %", "MwSt", "Brutto"]
    if currency == "USD":
        header = ["Description", "Net", "VAT %", "VAT", "Gross"]

    rows = [header]
    for desc, net, vat_rate, vat, gross in positions:
        rows.append([
            Paragraph(desc, STYLES["Small"]),
            p(fmt(net), "SmallRight"),
            p(f"{vat_rate} %", "SmallRight"),
            p(fmt(vat), "SmallRight"),
            p(fmt(gross), "SmallRight"),
        ])

    w = col_widths or [9 * cm, 2.2 * cm, 1.5 * cm, 2 * cm, 2.2 * cm]
    t = Table(rows, colWidths=w)
    t.setStyle(table_style())
    return t


def _totals_table(vat_summary, net_total, gross_total, currency="EUR"):
    """vat_summary: list of (rate, amount) tuples."""
    fmt = (lambda x: f"${x:,.2f}") if currency == "USD" else de_eur
    lbl_net = "Subtotal" if currency == "USD" else "Nettosumme"
    lbl_gross = "Total" if currency == "USD" else "Gesamtbetrag"
    lbl_vat = "VAT" if currency == "USD" else "Umsatzsteuer"

    rows = [[p(lbl_net, "SmallBold"), p(fmt(net_total), "SmallRight")]]
    for rate, amount in vat_summary:
        rows.append([
            p(f"{lbl_vat} ({rate} %)", "Small"),
            p(fmt(amount), "SmallRight"),
        ])
    rows.append([p(lbl_gross, "Bold"), p(fmt(gross_total), "BoldRight")])

    t = Table(rows, colWidths=[4 * cm, 2.5 * cm], hAlign="RIGHT")
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 12),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def generate_us_invoice():
    path = INVOICES_DIR / "nexus_ai_INV-2026-00042.pdf"
    doc = new_doc(path)
    story = []

    # Header: two-column (vendor left, title right)
    header = Table(
        [[
            [p("Nexus AI Corp.", "VendorName"),
             p("200 Brannan Street, Suite 100", "Small"),
             p("San Francisco, CA 94107", "Small"),
             p("USA", "Small"),
             sp(0.2),
             p("EIN: 47-1234567", "Small")],
            p("INVOICE", "DocTitle"),
        ]],
        colWidths=[10 * cm, 7 * cm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [header, sp()]

    # Invoice meta
    meta = Table(
        [["Invoice No:", "INV-2026-00042"],
         ["Date:", "May 7, 2026"],
         ["Due Date:", "June 7, 2026"],
         ["Currency:", "USD"]],
        colWidths=[3 * cm, 5 * cm], hAlign="RIGHT",
    )
    meta.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 12),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
    ]))
    story += [meta, sp()]

    story.append(p("Bill To:", "SmallBold"))
    story += [p(RECIPIENT_NAME, "Small"), p(RECIPIENT_ADDR, "Small"),
              p(f"VAT: {RECIPIENT_UID}", "Small"), sp()]

    story.append(hr())
    story.append(_positions_table(
        [("One-time credit purchase", 25.00, 20, 5.00, 30.00)],
        currency="USD",
    ))
    story += [sp(0.2), _totals_table([(20, 5.00)], 25.00, 30.00, currency="USD"), sp()]

    story.append(hr())
    story += [p("Wire Transfer Details:", "SmallBold"),
              p("First National Bank", "Small"),
              p("Routing: 121000358   Account: 1234567890", "Small"),
              sp(0.2),
              p("Note: Invoice issued in USD. Payment received in EUR at prevailing exchange rate.", "Note")]

    doc.build(story)
    print(f"  {path.name}")


def generate_german_hosting_invoice():
    path = INVOICES_DIR / "servercore_2026-05-08_INV0087321.pdf"
    doc = new_doc(path)
    story = []

    header = Table(
        [[
            [p("ServerCore GmbH", "VendorName"),
             p("Technikstraße 8", "Small"),
             p("85774 Unterhaching", "Small"),
             p("Deutschland", "Small"),
             sp(0.2),
             p("USt-IdNr.: DE123456789", "Small")],
            p("RECHNUNG", "DocTitle"),
        ]],
        colWidths=[10 * cm, 7 * cm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [header, sp()]

    meta = Table(
        [["Rechnungsnummer:", "INV-2026-05-08-0087321"],
         ["Rechnungsdatum:", "08.05.2026"],
         ["Leistungszeitraum:", "April 2026"],
         ["Kundennummer:", "SC-10042"]],
        colWidths=[4 * cm, 5 * cm], hAlign="RIGHT",
    )
    meta.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 12),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
    ]))
    story += [meta, sp()]

    story.append(p("Rechnungsempfänger:", "SmallBold"))
    story += [p(RECIPIENT_NAME, "Small"), p(RECIPIENT_ADDR, "Small"),
              p(f"UID: {RECIPIENT_UID}", "Small"), sp()]

    story.append(hr())
    positions = [
        ("EQ4 Dedicated Server (04/2026)", 44.73, 0, 0.00, 44.73),
        ("Primäre IPv4 (04/2026)", 1.70, 0, 0.00, 1.70),
        ("Zusätzliche IP (04/2026)", 1.70, 0, 0.00, 1.70),
        ("CX22 Cloud Server (04/2026)", 4.49, 0, 0.00, 4.49),
        ("Primary IPv4 (04/2026)", 0.50, 0, 0.00, 0.50),
        ("BX20 Storage Box (04/2026)", 5.39, 0, 0.00, 5.39),
    ]
    story.append(_positions_table(positions))
    story += [sp(0.2), _totals_table([(0, 0.00)], 58.51, 58.51), sp()]

    story.append(hr())
    story += [
        p("Hinweis zur Steuerschuld:", "SmallBold"),
        p("Diese Rechnung enthält keine Umsatzsteuer gemäß § 13b UStG "
          "(Steuerschuldnerschaft des Leistungsempfängers / Reverse Charge). "
          "Der Leistungsempfänger schuldet die Umsatzsteuer.", "Note"),
        sp(0.3),
        p("Bankverbindung:", "SmallBold"),
        p("IBAN: DE89 3704 0044 0532 0130 00   BIC: COBADEFFXXX", "Small"),
    ]

    doc.build(story)
    print(f"  {path.name}")


def generate_austrian_gutschrift():
    path = INVOICES_DIR / "talentum_TLT-2026-00158.pdf"
    doc = new_doc(path)
    story = []

    header = Table(
        [[
            [p("Talentum Personalvermittlung GmbH", "VendorName"),
             p("Mariahilfer Straße 77", "Small"),
             p("1060 Wien, Österreich", "Small"),
             sp(0.2),
             p("UID: ATU98765432", "Small"),
             p("FN 123456a HG Wien", "Small")],
            p("GUTSCHRIFT", "DocTitle"),
        ]],
        colWidths=[10 * cm, 7 * cm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [header, sp()]

    meta = Table(
        [["Gutschriftnummer:", "TLT-2026-00158"],
         ["Gutschriftdatum:", "02.04.2026"],
         ["Leistungszeitraum:", "T8 gem. Projektbericht"]],
        colWidths=[4 * cm, 6 * cm], hAlign="RIGHT",
    )
    meta.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 12),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
    ]))
    story += [meta, sp()]

    story.append(p("Empfänger:", "SmallBold"))
    story += [p(RECIPIENT_NAME, "Small"), p(RECIPIENT_ADDR, "Small"),
              p(f"UID: {RECIPIENT_UID}", "Small"), sp()]

    story.append(hr())
    story.append(_positions_table(
        [("Leistung (T8) gem. Ihrem eingereichten Projektbericht", 15370.76, 20, 3074.15, 18444.91)],
        col_widths=[9 * cm, 2.5 * cm, 1.5 * cm, 2.2 * cm, 2.5 * cm],
    ))
    story += [sp(0.2), _totals_table([(20, 3074.15)], 15370.76, 18444.91), sp()]

    story.append(hr())
    story += [
        p("Zahlungsdetails:", "SmallBold"),
        p("IBAN: AT83 2011 1234 5678 9010   BIC: STSPAT2G", "Small"),
        sp(0.2),
        p("Diese Gutschrift wird innerhalb von 14 Tagen auf Ihr Konto überwiesen.", "Note"),
    ]

    doc.build(story)
    print(f"  {path.name}")


def generate_austrian_telecom_invoice():
    path = INVOICES_DIR / "netconnect_NC-2026-0047832.pdf"
    doc = new_doc(path)
    story = []

    header = Table(
        [[
            [p("NetConnect Austria GmbH", "VendorName"),
             p("Hauptplatz 12", "Small"),
             p("2340 Mödling, Österreich", "Small"),
             sp(0.2),
             p("UID: ATU11223344", "Small"),
             p("FN 234567b HG Korneuburg", "Small")],
            p("RECHNUNG", "DocTitle"),
        ]],
        colWidths=[10 * cm, 7 * cm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [header, sp()]

    meta = Table(
        [["Kundennummer:", "27375133"],
         ["Rechnungsnummer:", "NC-2026-0047832"],
         ["Rechnungsdatum:", "05.05.2026"],
         ["Leistungszeitraum:", "01.05.2026 - 31.05.2026"]],
        colWidths=[4 * cm, 5 * cm], hAlign="RIGHT",
    )
    meta.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 12),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
    ]))
    story += [meta, sp()]

    story.append(p("Rechnungsempfänger:", "SmallBold"))
    story += [p(RECIPIENT_NAME, "Small"), p(RECIPIENT_ADDR, "Small"), sp()]

    story.append(hr())
    positions = [
        ("Monatsentgelt NetConnect TV Basic von 01.05.2026 bis 31.05.2026", 13.43, 10, 1.34, 14.77),
        ("Monatsentgelt NetConnect Internet 500 von 01.05.2026 bis 31.05.2026", 35.19, 20, 7.04, 42.23),
        ("Hardwaremiete Modem von 01.05.2026 bis 31.05.2026", 1.58, 20, 0.32, 1.90),
    ]
    story.append(_positions_table(positions))
    story += [sp(0.2), _totals_table([(10, 1.34), (20, 7.35)], 50.20, 58.89), sp()]

    story.append(hr())
    story += [
        p("Bankverbindung:", "SmallBold"),
        p("IBAN: AT12 2011 9876 5432 1000   BIC: BKAUATWW", "Small"),
        sp(0.2),
        p("Zahlbar bis: 20.05.2026. Bei Fragen wenden Sie sich an service@netconnect.example.at", "Note"),
    ]

    doc.build(story)
    print(f"  {path.name}")


def generate_municipal_vorschreibung():
    path = INVOICES_DIR / "waldbach_Vorschreibung_2026-Q2.pdf"
    doc = new_doc(path)
    story = []

    header = Table(
        [[
            [p("Stadtgemeinde Waldbach", "VendorName"),
             p("Rathausplatz 1", "Small"),
             p("8173 Waldbach, Österreich", "Small"),
             sp(0.2),
             p("Tel: 03115 / 1234   office@waldbach.gv.at", "Small")],
            p("VORSCHREIBUNG", "DocTitle"),
        ]],
        colWidths=[10 * cm, 7 * cm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [header, sp()]

    meta = Table(
        [["Vorschreibung:", "2026/Q2"],
         ["Datum:", "20.04.2026"],
         ["Fällig bis:", "15.05.2026"]],
        colWidths=[3.5 * cm, 5 * cm], hAlign="RIGHT",
    )
    meta.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 12),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
    ]))
    story += [meta, sp()]

    story.append(p("Vorgeschrieben an:", "SmallBold"))
    story += [p(RECIPIENT_NAME, "Small"), p(RECIPIENT_ADDR, "Small"), sp()]

    story.append(hr())

    # Wide table with wrapping descriptions
    w = [8.5 * cm, 2 * cm, 1.4 * cm, 1.8 * cm, 2.2 * cm]
    header_row = [
        p("Beschreibung", "SmallBold"),
        p("Netto", "SmallBold"),
        p("MwSt %", "SmallBold"),
        p("MwSt", "SmallBold"),
        p("Brutto", "SmallBold"),
    ]
    positions = [
        ("Grundsteuer B, 01.01.2026-31.12.2026, 11/001-1-1234/5, EZ 42, Grundstück 100, Messbetrag 5,35 x Hebesatz 500/100",
         26.75, 0, 0.00, 26.75),
        ("Kanalbenützungsgeb. Mw, 01.04.2026-30.06.2026, Kanalbenützungsgeb. u. RW, 223,35 m² x 3,14, davon 1/4",
         175.33, 10, 17.53, 192.86),
        ("Nachmittagsbetr. KG KLE, 01.03.2026-30.06.2026, NM Betreuung 33 bis 60 Stunden, Gruber Anna, KLE Gr.1, 12 x 83,00 NM Betreuung 33 bis 60 Stunden, davon 1/3",
         293.81, 13, 38.20, 332.01),
        ("Nachmittagsbetr. KG KLE, 01.03.2026-30.06.2026, NM Betreuung 33 bis 60 Stunden, Gruber Paul, KLE Gr.1, 12 x 83,00 NM Betreuung 33 bis 60 Stunden, davon 1/3",
         293.81, 13, 38.20, 332.01),
        ("Bildungs/Beschäftigungsmat.KL, 01.02.2026-30.06.2026, KDG KLE, Gruber Anna, KLE Gr.1, 1 x 173,00 KDG KLE, davon 1/2",
         76.55, 13, 9.95, 86.50),
        ("Bildungs/Beschäftigungsmat.KL, 01.02.2026-30.06.2026, KDG KLE, Gruber Paul, KLE Gr.1, 1 x 173,00 KDG KLE, davon 1/2",
         76.55, 13, 9.95, 86.50),
        ("Seuchenvorsorgeabgabe, 01.04.2026-30.06.2026, 1.560 Liter",
         3.75, 0, 0.00, 3.75),
        ("Abfallwirtschaftsgebühr, 01.04.2026-30.06.2026, 1 Restmülltonne 120 l / 13 Abf. x 13 Abfuhren x 14,48, davon 1/4",
         77.86, 10, 7.79, 85.65),
        ("Abfallwirtschaftsabgabe, 01.04.2026-30.06.2026, 1 Biotonne 120 l / 40 Abf. x 40 Abfuhren x 3,08 / 1 Papiertonne 240 l / 13 Abf., davon 1/4 / 5% von Abfallwirtschaftsgebühr, davon 1/4",
         3.89, 10, 0.39, 4.28),
    ]
    rows = [header_row] + [
        [Paragraph(desc, STYLES["Small"]),
         p(de_eur(net), "SmallRight"),
         p(f"{vr} %", "SmallRight"),
         p(de_eur(vat), "SmallRight"),
         p(de_eur(gross), "SmallRight")]
        for desc, net, vr, vat, gross in positions
    ]
    t = Table(rows, colWidths=w)
    t.setStyle(table_style())
    story.append(t)

    story += [sp(0.2), _totals_table(
        [(0, 0.00), (10, 25.71), (13, 96.30)],
        1028.30, 1150.29,
    ), sp()]

    story.append(hr())
    story += [
        p("Bankverbindung der Stadtgemeinde Waldbach:", "SmallBold"),
        p("IBAN: AT57 2011 1111 2222 3333   BIC: BKAUATWW", "Small"),
        sp(0.2),
        p("Bitte geben Sie bei der Überweisung den Verwendungszweck \"Vorschreibung 2026/Q2\" an.", "Note"),
    ]

    doc.build(story)
    print(f"  {path.name}")


# ---------------------------------------------------------------------------
# Payment receipt generator
# ---------------------------------------------------------------------------

PAYMENT_FIXTURES = [
    {
        "filename": "E2B12045776D82C4.pdf",
        "date": "11.05.2026",
        "valuta": "13.05.2026",
        "counterparty": "NEXUS AI CORP.",
        "counterparty_iban": None,
        "purpose": "INV-2026-00042",
        "amount": -26.06,
        "reference": "E2B12045776D82C4",
        "note": "Fremdwährung: USD 30,00 / Kurs 1,1515",
    },
    {
        "filename": "E2CB864828ADF1DA.pdf",
        "date": "13.05.2026",
        "valuta": "13.05.2026",
        "counterparty": "ServerCore GmbH",
        "counterparty_iban": "DE89 3704 0044 0532 0130 00",
        "purpose": "INV-2026-05-08-0087321 April 2026",
        "amount": -58.51,
        "reference": "E2CB864828ADF1DA",
        "note": None,
    },
    {
        "filename": "AT611904300234573201_E2CBDE06344971C4.pdf",
        "date": "13.05.2026",
        "valuta": "13.05.2026",
        "counterparty": "TALENTUM PERSONALVERMITTLUNG GMBH",
        "counterparty_iban": "AT83 2011 1234 5678 9010",
        "purpose": "TLT-2026-00158 Gutschrift April 2026",
        "amount": +18444.91,
        "reference": "E2CBDE06344971C4",
        "note": None,
    },
    {
        "filename": "AT611904300234573201_E2CF175EAA18B0C3.pdf",
        "date": "15.05.2026",
        "valuta": "15.05.2026",
        "counterparty": "NetConnect Austria GmbH",
        "counterparty_iban": "AT12 2011 9876 5432 1000",
        "purpose": "NC-2026-0047832 Mai 2026",
        "amount": -58.89,
        "reference": "E2CF175EAA18B0C3",
        "note": None,
    },
    {
        "filename": "AT611904300234573201_E2CF1A61C4E5542B.pdf",
        "date": "15.05.2026",
        "valuta": "15.05.2026",
        "counterparty": "Stadtgemeinde Waldbach",
        "counterparty_iban": "AT57 2011 1111 2222 3333",
        "purpose": "Vorschreibung 2026/Q2",
        "amount": -1150.29,
        "reference": "E2CF1A61C4E5542B",
        "note": None,
    },
]


def generate_payment_receipt(fix):
    path = PAYMENTS_DIR / fix["filename"]
    doc = new_doc(path)
    story = []

    # Bank header
    story += [p(BANK_NAME, "VendorName"), p("Zahlungsbestätigung / Kontoauszugszeile", "Small"), hr(), sp(0.2)]

    # Account info block
    account_info = Table(
        [["Kontoinhaber:", RECIPIENT_NAME],
         ["IBAN:", OUR_IBAN],
         ["BIC:", OUR_BIC]],
        colWidths=[4 * cm, 12 * cm],
    )
    account_info.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 13),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, -1), GREY_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [account_info, sp()]

    # Transaction details
    direction = "Gutschrift (eingehend)" if fix["amount"] > 0 else "Lastschrift (ausgehend)"
    amount_color = colors.HexColor("#1a7a1a") if fix["amount"] > 0 else colors.HexColor("#cc0000")

    rows = [
        ["Buchungsdatum:", fix["date"]],
        ["Valutadatum:", fix["valuta"]],
        ["Buchungstext:", direction],
        ["Auftraggeber/Empfänger:", fix["counterparty"]],
    ]
    if fix.get("counterparty_iban"):
        rows.append(["IBAN Gegenkonto:", fix["counterparty_iban"]])
    rows += [
        ["Verwendungszweck:", fix["purpose"]],
        ["Referenznummer:", fix["reference"]],
    ]

    detail_table = Table(rows, colWidths=[4 * cm, 12 * cm])
    detail_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 13),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (0, -1), 6),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, GREY_MID),
    ]))
    story += [detail_table, sp(0.3)]

    # Amount (prominent)
    sign = "+" if fix["amount"] > 0 else "-"
    amount_str = f"{sign} {de(abs(fix['amount']))} EUR"
    amt_table = Table(
        [["Betrag:", Paragraph(f'<font color="{amount_color.hexval()}" size="14"><b>{amount_str}</b></font>',
                               STYLES["Normal"])]],
        colWidths=[4 * cm, 12 * cm],
    )
    amt_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (0, 0), 9),
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(amt_table)

    if fix.get("note"):
        story += [sp(0.2), p(fix["note"], "Note")]

    story += [sp(0.5), hr(),
              p("Dieses Dokument wurde maschinell erstellt und ist ohne Unterschrift gültig.", "Note")]

    doc.build(story)
    print(f"  {path.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    PAYMENTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Generating invoices...")
    generate_us_invoice()
    generate_german_hosting_invoice()
    generate_austrian_gutschrift()
    generate_austrian_telecom_invoice()
    generate_municipal_vorschreibung()

    print("Generating payment receipts...")
    for fix in PAYMENT_FIXTURES:
        generate_payment_receipt(fix)

    print(f"\nDone. Files written to {HERE / 'pdfs'}")


if __name__ == "__main__":
    main()

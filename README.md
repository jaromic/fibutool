# fibutool   
    
fibutool is a tool helping bookkeeping by automatically renaming, matching, merging payment receipt PDFs and invoice 
receipt PDFs and preparing csv data for adding to the journal

## architecture

fibutool is a CLI bookkeeping tool that processes bank payment receipts and invoices (PDFs) using Claude as an AI backbone.

**Pipeline (4 steps):**

1. **Extract** (`extractor.py`) — sends each PDF as a base64 document to Claude (`claude-sonnet-4-6`) to parse structured fields (date, amount, currency, counterparty, direction, VAT rate, address).

2. **Order** (`orderer.py`) — sorts payments by booking date, renames them with sequential receipt numbers (`001_2024-01-15_original.pdf`), copies them to `payments-ordered/`.

3. **Match** (`matcher.py`) — sends all payments and all invoices in a single batch call to Claude (`claude-opus-4-7`); returns the best assignment for each payment based on company name, amount, direction, and date proximity.

4. **Merge + Journal** (`merger.py`, `journal.py`) — merges each matched invoice+payment into a single PDF in `merged/`; writes a `journal.csv` in Austrian bookkeeping format (semicolon-delimited, UTF-8 BOM for Excel).

**Data model** (`models.py`): three dataclasses — `PaymentInfo`, `InvoiceInfo`, `MatchResult` — flow through the whole pipeline.

**AI usage:** Claude is called once per payment (extraction), once per invoice (extraction), and once total for matching. System prompts use prompt caching to reduce costs.

**Invoice extraction** returns invoice positions (Rechnungspositionen) and the supplier's country in addition to header fields.  From these the pipeline derives:
- **detail_category** — assigned by rule (`category_rules` in config, keyword → EÜR category); no LLM classification
- **business_percentage** (Anteil) — assigned by rule (`business_percentage_rules` in config); defaults to 100 %
- **IG** — set when the invoice carries a `vat_rate` of 0 (the LLM sets this for reverse-charge / IG Leistung wording) and the supplier country is known and not Austria; domestic VAT-exempt invoices (e.g. insurance, SVS) are not marked IG. **Known gap:** non-EU/EEA suppliers (e.g. Switzerland, UK) whose invoices show 0 % VAT for other reasons could be misclassified as IG; this is only triggered by an incorrectly issued invoice and is not addressed deliberately.
- **AfA** — true when the invoice is for a depreciable asset (net > €1000, or not suitable as GWG)
- **mixed VAT** — when positions carry different VAT rates the journal writes "mixed" and fills in the total VAT amount; otherwise the single rate is written and the amount is left for Excel to compute

## prepare development environment

    # Build docker image and run container

    docker build -t fibutool-dev .

    MSYS_NO_PATHCONV=1 docker run -it -v "$(pwd -W)":/workspace -w /workspace --name fibutool-dev fibutool-dev

## execute the tool

    # Set your Anthropic API key in config.yaml, then run from the working directory:
    python main.py --last-receipt-number 42

    # Or point to a specific working directory:
    python main.py --last-receipt-number 42 --workdir /archive/2024/january

    # If output from a previous run exists, the tool will refuse — use --clean to reset:
    python main.py --last-receipt-number 42 --clean

    # Regenerate journal.csv without re-running extraction, matching, or PDF merging.
    # Requires a completed previous run (match_results.json and non-empty output dirs).
    # Use this after editing journal.py to apply a changed format without API costs.
    python main.py --journal-only

    # --clean in journal-only mode removes only journal.csv (cache and merged dirs are kept):
    python main.py --journal-only --clean

    # Test the full pipeline with a single payment and invoice (cheap — 3 API calls total):
    python main.py -n 42 --clean \
        --only-payment payments/suspicious.pdf \
        --only-invoice invoices/matching_invoice.pdf

## split merged PDFs (test-data helper)

`splitter.py` reverses the merge step: it splits merged PDFs back into separate
invoice and payment files.  Useful for quickly preparing test data from an
existing set of merged PDFs.

    # Split all PDFs in merged/ into payments/ and invoices/ (current directory):
    python splitter.py

    # Or point to a specific working directory:
    python splitter.py --workdir test_data/

The working directory must contain `merged/`, `payments/`, and `invoices/`
subdirectories.  `merged/` must be non-empty; `payments/` and `invoices/` must
exist and be empty — the tool refuses to overwrite existing files.

Each merged PDF is split as follows: the last page becomes
`payments/<stem>_payment.pdf`; all preceding pages (if any) become
`invoices/<stem>_invoice.pdf`.

## folder layout

All input and output lives under the working directory (default: current directory).
The output directories must exist before the first run. The tool refuses to run if they
are missing or contain files from a previous run (use --clean to reset).

    <workdir>/payments/           ← input: bank payment confirmation PDFs
    <workdir>/invoices/           ← input: invoice PDFs (incoming and outgoing)
    <workdir>/payments-ordered/   ← output: payments renamed NNN_YYYY-MM-DD_<orig>.pdf  (must exist)
    <workdir>/merged/             ← output: merged PDFs (invoice pages first, then payment)  (must exist)
    <workdir>/journal.csv         ← output: journal rows ready for import into Excel
    <workdir>/match_results.json  ← cache: extracted + matched data written after step 2; required for --journal-only
    config.yaml                   ← API key, company names, and matching rules (default: ./config.yaml)

config.yaml structure:

    anthropic_api_key: sk-ant-...

    own_company_names:            # used to detect incoming payments (our name in counterparty)
      - Acme GmbH
      - Max Mustermann

    category_rules:               # maps counterparty keyword (case-insensitive substring) → EÜR category
      Acme Telecom: "Telefon/Internet"
      Example Software: "Lizenzgebühren"
      Sozialversicherung: "Pflichversicherungsbeiträge" # intentionally mis-spelled
      Cloud Provider: "sonstige Betriebsausgaben"
      # unmatched incoming_invoice → "sonstige Betriebsausgaben"
      # unmatched outgoing_invoice / credit_note → "Waren-/Leistungserlöse"
      # category values must be from the built-in Austrian EÜR list; invalid values abort at startup

    business_percentage_rules:    # maps counterparty keyword → Anteil % (1–100, default 100)
      Acme Telecom: 67            # 67 % business use for phone/internet
      "Gemeinde Musterstadt": 10  # 10 % business share of municipal bill
      Cloud Provider: 50

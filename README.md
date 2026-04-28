# fibutool   
    
fibutool is a tool helping bookkeeping by automatically renaming, matching, merging payment receipt PDFs and invoice 
receipt PDFs and preparing csv data for adding to the journal

## architecture

fibutool is a CLI bookkeeping tool that processes bank payment receipts and invoices (PDFs) using Claude as an AI backbone.

**Pipeline (4 steps):**

1. **Extract** (`extractor.py`) — reads PDF text via `pdfplumber`, sends it to Claude (`claude-opus-4-7`) to parse structured fields (date, amount, currency, counterparty, direction).

2. **Order** (`orderer.py`) — sorts payments by booking date, renames them with sequential receipt numbers (`001_2024-01-15_original.pdf`), copies them to `payments-ordered/`.

3. **Match** (`matcher.py`) — for each payment, asks Claude (with extended thinking) to find the best unmatched invoice from the invoice list, based on company name, amount, direction, and date proximity.

4. **Merge + Journal** (`merger.py`, `journal.py`) — merges each matched invoice+payment into a single PDF in `merged/`; writes a `journal.csv` with gross/net/VAT columns in Austrian bookkeeping format (semicolon-delimited, UTF-8 BOM for Excel).

**Data model** (`models.py`): three dataclasses — `PaymentInfo`, `InvoiceInfo`, `MatchResult` — flow through the whole pipeline.

**AI usage:** Claude is called 3× per document (extract payment, extract invoice, match) with prompt caching on system prompts to reduce costs.

## prepare development environment

    # Build docker image and run container

    docker build -t fibutool-dev .

    MSYS_NO_PATHCONV=1 docker run -it -v "$(pwd -W)":/workspace -w /workspace --name fibutool-dev

## execute the tool

    # Set your Anthropic API key in config.yaml, then run:
    python main.py --last-receipt-number 42

    # With explicit paths
    python main.py --last-receipt-number 42 \
        --payments ./payments \
        --invoices ./invoices \
        --merged ./merged \
        --journal ./journal.csv

    # --journal accepts a directory (journal.csv placed inside) or a full file path
    python main.py --last-receipt-number 42 --journal /archive/2024/bookkeeping.csv

## folder layout

    payments/           ← input: bank payment confirmation PDFs
    invoices/           ← input: invoice PDFs (incoming and outgoing)
    payments-ordered/   ← output: payments renamed NNN_YYYY-MM-DD_<orig>.pdf
    merged/             ← output: merged PDFs (invoice pages first, then payment)
    journal.csv         ← output: journal rows ready for import into Excel
    config.yaml         ← own company names (Jarosoft / Michael Jaros)

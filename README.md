# fibutool

fibutool is a CLI tool that automates bookkeeping preparation: it renames, matches, and merges bank payment receipt PDFs with invoice PDFs, then produces a semicolon-delimited CSV journal ready for import into Excel.

## Architecture

fibutool is a CLI bookkeeping tool that processes bank payment receipts and invoices (PDFs) using Claude as an AI backbone.

**Pipeline (4 steps):**

1. **Extract** (`extractor.py`) — sends each PDF as a base64 document to Claude (`claude-sonnet-4-6`) to parse structured fields (date, amount, currency, counterparty, direction, VAT rate, address).

2. **Order** (`orderer.py`) — sorts payments by booking date, renames them with sequential receipt numbers (`001_2024-01-15_original.pdf`), copies them to `payments-ordered/`.

3. **Match** (`matcher.py`) — sends all payments and all invoices in a single batch call to Claude (`claude-opus-4-7`); returns the best assignment for each payment based on company name, amount, direction, and date proximity.

4. **Merge + Journal** (`merger.py`, `journal.py`) — merges each matched invoice+payment into a single PDF in `merged/`; writes a `journal.csv` in Austrian bookkeeping format (semicolon-delimited, UTF-8 BOM for Excel).

**Data model** (`models.py`): three dataclasses — `PaymentInfo`, `InvoiceInfo`, `MatchResult` — flow through the whole pipeline.

**AI usage:** Claude is called once per payment (extraction), once per invoice (extraction), and once total for matching. System prompts use prompt caching to reduce costs.

**Invoice extraction** returns invoice positions (Rechnungspositionen) and the supplier's country. From these the pipeline derives:
- **detail_category** — assigned by rule (`category_rules` in config, keyword → EÜR category); no LLM classification
- **business_percentage** (Anteil) — assigned by rule (`business_percentage_rules` in config); defaults to 100 %
- **IG** — set when the invoice carries a `vat_rate` of 0 and the supplier country is known and not Austria; domestic VAT-exempt invoices (e.g. insurance, SVS) are not marked IG. **Known gap:** non-EU/EEA suppliers (e.g. Switzerland, UK) whose invoices show 0 % VAT for other reasons could be misclassified as IG; this is only triggered by an incorrectly issued invoice and is not addressed deliberately.
- **AfA** — true when the invoice is for a depreciable asset (net > €1000, or not suitable as GWG)
- **mixed VAT** — when positions carry different VAT rates the journal writes the configured `mixed_vat_label` and fills in the total VAT amount; otherwise the single rate and amount are computed from `effective_base` (payment amount minus any foreign-currency fee)

## Directory model

fibutool separates two concerns:

| Directory | Purpose | Default location |
|-----------|---------|-----------------|
| **App directory** | Shared config; survives across sessions | `%APPDATA%\fibutool\` (Windows) / `~/.config/fibutool/` (other) |
| **Work directory** | Per-session input PDFs, output files, log, and intermediary data | Current working directory |

**App directory** contains:
- `config.yaml` — API key, company names, and matching rules (shared across all sessions)

**Work directory** contains everything that belongs to one bookkeeping session:
- `payments/` and `invoices/` — input PDFs
- `payments-ordered/`, `merged/` — output PDFs
- `journal.csv` — output journal
- `match_results.json` — intermediary: extracted + matched data (written after step 2; required for `--journal-only`)
- `<ISO-datetime>_fibutool.log` — full log of every run (stdout + stderr)

## Installation

**Prerequisites:** Python 3.12+, Git

```bat
:: Clone the repo to a permanent location (e.g. C:\tools\fibutool)
git clone <repo-url> C:\tools\fibutool
cd C:\tools\fibutool

:: Install as an editable package — creates fibutool.exe on your PATH
pip install -e .

:: Verify
fibutool --version
```

Make sure Python's `Scripts` folder is on your PATH (the Python installer offers this option).

**Create the app directory and copy the example config:**

```bat
mkdir "%APPDATA%\fibutool"
copy config.yaml.example "%APPDATA%\fibutool\config.yaml"
:: Then edit %APPDATA%\fibutool\config.yaml and add your Anthropic API key
```

**Switching to a specific version:**

```bat
cd C:\tools\fibutool
git checkout v1.2.0
pip install -e .
fibutool --version    :: should now report 1.2.0
```

**Releasing a new version:**

```bat
git tag v1.2.0
git push origin v1.2.0
pip install -e .      :: reinstall so fibutool --version reflects the new tag
```

## Usage

Prepare a session directory with `payments/` and `invoices/` subfolders, then `cd` into it:

```bat
cd C:\fibu\2025-Q4
mkdir payments payments-ordered invoices merged
:: copy your PDFs into payments\ and invoices\

fibutool --last-receipt-number 108
```

**Common commands:**

```bat
:: Normal run — last receipt was 108, next will be 109:
fibutool -n 108

:: Remove output from a previous run before re-running:
fibutool -n 108 --clean

:: Regenerate journal.csv only (no API calls) — useful after editing journal rules:
fibutool --journal-only

:: Test with a single payment + invoice (3 API calls total):
fibutool -n 108 --clean \
    --only-payment payments\receipt.pdf \
    --only-invoice invoices\invoice.pdf

:: Use a non-default config (e.g. for testing):
fibutool -n 108 --config C:\path\to\other-config.yaml

:: Run in a specific work directory without cd-ing into it:
fibutool -n 108 --workdir C:\fibu\2025-Q4
```

Every run writes a timestamped log file (`<ISO-datetime>_fibutool.log`) to the work directory alongside the other output files.

## Folder layout

```
<work directory>/               ← per-session; default: current directory
  payments/                     ← input: bank payment confirmation PDFs
  invoices/                     ← input: invoice PDFs (incoming and outgoing)
  payments-ordered/             ← output: payments renamed NNN_YYYY-MM-DD_<orig>.pdf
  merged/                       ← output: merged PDFs (invoice pages first, then payment)
  journal.csv                   ← output: journal rows ready for import into Excel
  match_results.json            ← intermediary: extracted + matched data; required for --journal-only
  <ISO-datetime>_fibutool.log   ← log: full stdout + stderr for this run

%APPDATA%\fibutool\             ← app directory; shared across all sessions
  config.yaml                   ← API key, company names, and matching rules
```

## Config reference

Default location: `%APPDATA%\fibutool\config.yaml` (Windows) or `~/.config/fibutool/config.yaml`.  
Override with `--config <path>`.

```yaml
anthropic_api_key: sk-ant-...

own_company_names:              # detect incoming payments where our name appears as counterparty
  - Acme GmbH
  - Max Mustermann

category_rules:                 # keyword (case-insensitive substring of counterparty) → EÜR category
  Acme Telecom: "Telefon/Internet"
  Example Software: "Lizenzgebühren"
  Sozialversicherung: "Pflichversicherungsbeiträge"  # note intentional spelling
  Cloud Provider: "sonstige Betriebsausgaben"
  # unmatched incoming_invoice  → "sonstige Betriebsausgaben"
  # unmatched outgoing_invoice  → "Waren-/Leistungserlöse"
  # invalid values abort at startup with the list of valid categories

business_percentage_rules:      # keyword → Anteil % (1–100); default 100
  Acme Telecom: 66.6667         # use 4 decimal places for precision (e.g. 2/3 = 66.6667)
  "Gemeinde Musterstadt": 9.2154
  Cloud Provider: 50

position_business_rules:        # keyword → list of description keywords that mark a position as business use
  "Gemeinde Musterstadt":       # positions not matching any keyword are treated as private
    business_keywords: ["Kanal", "Grundsteuer", "Abfall"]

mixed_vat_label: "gemischt"    # label written to VAT% column when positions have different rates
decimal_separator: ","          # "," for Austrian/German Excel, "." for English
ig_vat_rate: 20                 # VAT rate used for IG self-assessment (Erwerbsteuer)
```

## Development environment

This project is developed inside a Docker container (Python 3.12 + Node.js + Claude Code CLI). The container is only needed for running the autonomous Claude Code agent safely; the tool itself runs on Windows natively.

**Build and start the dev container (run from the repo root on the host):**

```bash
docker build -t fibutool-dev .

# Windows (Git Bash / MSYS2):
MSYS_NO_PATHCONV=1 docker run -it -v "$(pwd -W)":/workspace -w /workspace --name fibutool-dev fibutool-dev

# Linux / macOS:
docker run -it -v "$(pwd)":/workspace -w /workspace --name fibutool-dev fibutool-dev
```

The host repo is bind-mounted to `/workspace` inside the container, so edits on either side are reflected immediately.

**Install dependencies inside the container:**

```bash
pip install -r requirements.txt
pip install -e .
```

**Run tests:**

```bash
pytest tests/
```

## Splitter (test-data helper)

`splitter.py` reverses the merge step: splits merged PDFs back into separate invoice and payment files. Useful for preparing test data from an existing set of merged PDFs.

```bat
:: Split all PDFs in merged\ into payments\ and invoices\ (current directory):
python splitter.py

:: Or point to a specific work directory:
python splitter.py --workdir C:\fibu\2025-Q4
```

The work directory must contain `merged\`, `payments\`, and `invoices\` subdirectories. `merged\` must be non-empty; `payments\` and `invoices\` must exist and be empty — the tool refuses to overwrite existing files.

Each merged PDF is split as follows: the last page becomes `payments\<stem>_payment.pdf`; all preceding pages become `invoices\<stem>_invoice.pdf`.

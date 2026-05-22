# fibutool

fibutool is a CLI toolset that automates bookkeeping preparation for Austrian Einnahmen-Ausgaben-Rechnung: it fetches invoice PDFs from email and filesystem sources, matches them against bank payment receipts, merges them into archive PDFs, and produces a semicolon-delimited CSV journal ready for import into Excel.

## Architecture

The system has three layers. See `requirements/OVERVIEW.md` for the conceptual overview.

### Acquisition layer — `fetcher.py`

Downloads invoice PDFs from configured sources (Google Workspace email via OAuth, local filesystem paths) into the session `invoices/` directory. De-duplicates across runs via a SHA-256 content registry. Runs standalone or is invoked automatically by the orchestration layer.

### Journal reader — `journal_reader.py`

Reads the last receipt number and latest payment date from the original journal Excel workbook (`.xlsx`). Cross-checks the receipt number against the permanent merged PDF archive to detect inconsistencies before a run starts. Used by the orchestration layer; can also be called standalone.

### Journal updater — `journal_updater.py`
Appends the rows from journal.csv into the original Excel journal workbook. Invoked automatically by the orchestration layer after processing

### Orchestration layer — `run.py`

The normal entry point for a bookkeeping session. 

 * Uses the journal reader to obtain session parameters.
 * Guides the user through the one manual step (downloading bank payment receipts)
 * Runs fetcher and fibutool (`process.py`) in sequence
 * Runs journal updater to update the original journal Excel workbook
 * Copies merged PDFs to the permanent archive

Offers abort / retry / continue at every stage.

### Processing layer — `fibutool-process` (`process.py`)

Core bookkeeping pipeline using Claude as AI backbone.

**Full mode** (no `match_results.json`, or `--clean`):

1. **Extract payments** — one Claude (`claude-sonnet-4-6`) call per PDF in `payments/`; produces structured data (date, amount, counterparty, direction).
2. **Order payments** — sort by booking date, assign sequential receipt numbers, write renamed copies to `payments-ordered/`.
3. **Extract invoices** — one Claude (`claude-sonnet-4-6`) call per PDF in `invoices/`.
4. **Match** — single batch Claude (`claude-opus-4-7`) call across all payments and invoices; assigns best invoice to each payment; saves `match_results.json`.
5. **Merge** — one merged PDF per payment written to `merged/`.
6. **Journal** — writes `journal.csv`.

**Resume mode** (`match_results.json` exists, no `--clean`):

1. Load previous results from `match_results.json`.
2. **Extract new invoices only** — invoices not seen in the previous run.
3. **Re-match unmatched payments only** — payments without an invoice are re-matched against all available invoices; `match_results.json` updated.
4. **Merge** and **Journal** — same as full mode.

**Journal-only mode** (`--journal-only`): loads `match_results.json`, regenerates `journal.csv`, no API calls.

**Data model** (`models.py`): three dataclasses — `PaymentInfo`, `InvoiceInfo`, `MatchResult` — flow through the whole pipeline.

**AI usage (full mode):** Claude is called once per payment (extraction), once per invoice (extraction), and once total for matching. Resume mode skips payment extraction and only calls Claude for new invoices and unmatched payments. System prompts use prompt caching to reduce costs.

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
- `match_results.json` — intermediary: extracted + matched data (written after step 2; required for `--journal-only` and resume mode)
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

Make sure Python's `Scripts` folder is on your PATH (the Python installer offers this option). You can identify the 
correct scripts folder by looking on the output of the installation command above, e.g.
`C:\Users\<username>\AppData\Roaming\Python\Python314\`.

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

### Typical session — via orchestrator

Create a session directory, then run the orchestrator. It reads the journal, prompts for payment receipts, fetches invoices, and processes everything automatically:

```bat
cd C:\fibu\2026-Q2
mkdir payments payments-ordered invoices merged

fibutool --workdir .
```

### Fetcher — standalone

```bat
:: Download invoices from all configured sources since a date:
fetcher --since 2026-03-01

:: Dry run — show what would be downloaded without writing anything:
fetcher --since 2026-03-01 --dry-run

:: Only one source:
fetcher --since 2026-03-01 --only office
```

### Processing layer — standalone

```bat
:: Normal run — last receipt was 108, next will be 109:
fibutool-process -n 108

:: Remove output from a previous run before re-running:
fibutool-process -n 108 --clean

:: Resume after adding missing invoices (no -n required):
fibutool-process

:: Regenerate journal.csv only (no API calls):
fibutool-process --journal-only

:: Test with a single payment + invoice (3 API calls total):
fibutool-process -n 108 --clean --only-payment payments\receipt.pdf --only-invoice invoices\invoice.pdf
```

Every tool writes a timestamped log file to the work directory.

## Folder layout

```
<work directory>/               ← per-session; default: current directory
  payments/                     ← input: bank payment confirmation PDFs (placed manually)
  invoices/                     ← input: invoice PDFs (fetched automatically or placed manually)
  payments-ordered/             ← output: payments renamed YYYY-NNN_YYYY-MM-DD_<orig>.pdf
  merged/                       ← output: merged PDFs (invoice pages first, then payment)
  journal.csv                   ← output: journal rows ready for import into Excel
  match_results.json            ← intermediary: extracted + matched data; required for --journal-only and resume mode
  fetcher_seen.json             ← fetcher state: registry of already-downloaded files (de-duplication)
  <ISO-datetime>_run.log        ← log: complete session transcript when run via fibutool orchestrator
  <ISO-datetime>_fibutool.log   ← log: processing layer transcript (standalone runs or detail)
  <ISO-datetime>_fetcher.log    ← log: fetcher transcript (standalone runs or detail)

<app directory>/                ← shared across all sessions; default: script directory
  config.yaml                   ← all configuration: API keys, rules, sources, journal workbook path

<permanent merged directory>/   ← user-maintained archive of all merged PDFs across sessions
                                   configured in config.yaml; used by journal_reader for cross-check
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

For `fetcher` sources (`gmail_sources`, `filesystem_sources`) and `original_journal` configuration, see the annotated `config.yaml.example` in the repo root.

## Development environment

Enable pre-commit hook in your local repo:
```
git config core.hooksPath .githooks
```

This project is developed inside a Docker container (Python 3.12 + Node.js + Claude Code CLI). The container is only needed for running the autonomous Claude Code agent safely; the tool itself runs on Windows natively.

**Build and start the dev container (run from the repo root on the host):**

```bash
docker build -t fibutool-dev .

# Windows (Git Bash / MSYS2):
MSYS_NO_PATHCONV=1 docker run -it -v "$(pwd -W)":/workspace -w /workspace --name fibutool-dev fibutool-dev

# Linux / macOS:
docker run -it -v "$(pwd)":/workspace -w /workspace --name fibutool-dev fibutool-dev

# Re-attach to existing container later:
docker container ls -a
docker container start <fibutool-dev>
docker container attach <fibutool-dev>
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

**One-time developer setup (git hook — runs unit tests before every commit):**

```bash
git config core.hooksPath .githooks
```

On Windows (outside the container), also install dev dependencies:

```bat
pip install -e ".[dev]"
git config core.hooksPath .githooks
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

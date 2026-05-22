# fibutool — Developer Reference

## Architecture

The system has three layers.

### Acquisition layer — `fetcher.py`

Downloads invoice PDFs from configured sources (Google Workspace email via OAuth, local filesystem paths) into the session `invoices/` directory. De-duplicates across runs via a SHA-256 content registry. Runs standalone or is invoked automatically by the orchestration layer.

### Journal reader — `journal_reader.py`

Reads the last receipt number and latest payment date from the original journal Excel workbook (`.xlsx`). Cross-checks the receipt number against the permanent merged PDF archive to detect inconsistencies before a run starts. Used by the orchestration layer; can also be called standalone.

### Journal updater — `journal_updater.py`

Appends the rows from `journal.csv` into the original Excel journal workbook. Invoked automatically by the orchestration layer after processing.

### Orchestration layer — `run.py`

The normal entry point for a bookkeeping session.

* Uses the journal reader to obtain session parameters.
* Guides the user through the one manual step (downloading bank payment receipts).
* Runs fetcher and fibutool (`process.py`) in sequence.
* Runs journal updater to update the original journal Excel workbook.
* Copies merged PDFs to the permanent archive.

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
- **IG** — set when the invoice carries a `vat_rate` of 0 and the supplier country is known and not Austria; domestic VAT-exempt invoices (e.g. insurance, SVS) are not marked IG.
- **AfA** — true when the invoice is for a depreciable asset (net > €1000, or not suitable as GWG)
- **mixed VAT** — when positions carry different VAT rates the journal writes the configured `mixed_vat_label` and fills in the total VAT amount; otherwise the single rate and amount are computed from `effective_base` (payment amount minus any foreign-currency fee)

---

## Development environment

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

---

## Releasing a new version

```bat
git tag v1.2.0
git push origin v1.2.0
```

GitHub Actions builds the wheel and Windows EXE automatically and attaches both to the release.

To install the new version locally after tagging:

```bat
cd C:\tools\fibutool
git pull
pip install -e .
fibutool --version
```

---

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

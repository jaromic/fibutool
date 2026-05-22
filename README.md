# fibutool

**Automated bookkeeping preparation for Austrian one-person businesses (EPU).**

You download your bank receipts once a month, drop them in a folder, run one command — and get a finished journal ready for your Excel workbook and VAT reporting. fibutool handles the rest: it fetches your invoices from email, matches them to payments using AI, merges them into archive PDFs, and writes every booking to a CSV ready for import.

---

## What it does

- **Fetches invoices** from your email inbox (Gmail / IMAP) or a local folder — automatically, no manual downloading.
- **Matches** each bank payment to the right invoice using Claude AI — by amount, date, and counterparty.
- **Produces archive PDFs** — invoice and payment receipt merged into one file per booking, named and numbered for your records.
- **Writes a journal CSV** — one row per booking with gross, net, VAT, category, business share, and IG flag; ready to import into your Excel journal.
- **Updates your Excel workbook** — appends the new rows directly into your existing `.xlsx` journal file.

---

## What you need

| Requirement | Details |
|-------------|---------|
| Windows 10 or 11 | The tool runs natively on Windows. |
| Austrian E/A Rechnung | Designed for Einnahmen-Ausgaben-Rechnung with IST-Besteuerung. |
| Bank payment receipts as PDF | Downloaded manually from your bank's online portal once a month. |
| Invoices reachable by email or filesystem | Gmail, any IMAP mailbox, or a local folder. |
| An Anthropic API key | Used to power AI extraction and matching. See [API costs](#api-costs) below. |
| An existing Excel journal (`.xlsx`) | fibutool appends to your journal — it does not replace it. The column layout must match the expected format (see [Config reference](#config-reference)). |

---

## Installation

**1. Download `fibutool.exe`**

Go to the [latest release](https://github.com/jaromic/fibutool/releases/latest) and download `fibutool.exe`. Save it somewhere permanent, e.g. `C:\tools\fibutool\fibutool.exe`.

**2. Add it to your PATH** (once)

Open *Start → Settings → System → About → Advanced system settings → Environment Variables*. Under *User variables*, edit `Path` and add `C:\tools\fibutool`.

Open a new Command Prompt and verify:

```bat
fibutool --version
```

**3. Create the config directory and copy the example config**

```bat
mkdir "%APPDATA%\fibutool"
```

Download [`config.yaml.example`](https://github.com/jaromic/fibutool/releases/latest) from the release, save it to `%APPDATA%\fibutool\config.yaml`, and open it in a text editor.

**4. Add your Anthropic API key**

Sign up at [console.anthropic.com](https://console.anthropic.com), create an API key, and paste it into `config.yaml`:

```yaml
anthropic_api_key: sk-ant-...
```

**5. Fill in the rest of `config.yaml`**

At minimum, set your company name and the path to your Excel journal workbook. See [Config reference](#config-reference) for all options.

---

## Monthly workflow

1. **Create a session folder** for the month, e.g. `C:\fibu\2026-05`.

2. **Download payment receipts** from your bank's online portal. Save each PDF into `C:\fibu\2026-05\payments\`.

3. **Run fibutool:**

   ```bat
   fibutool --workdir C:\fibu\2026-05
   ```

   fibutool will:
   - Read your journal to find the last receipt number and the date to fetch invoices from.
   - Fetch invoices from your configured email / folder automatically.
   - Extract, match, merge, and write the journal — showing progress as it goes.
   - Append the new rows to your Excel workbook.
   - Copy the merged archive PDFs to your permanent archive folder.

4. **Review the output.** Check the summary for any warnings (unmatched payments, missing invoices, VAT assumptions). The full log is in `C:\fibu\2026-05\<timestamp>_run.log`.

5. **Open your Excel journal** and verify the new rows look correct.

That's it. A typical month with 5–15 bookings takes under 5 minutes.

---

## API costs

fibutool uses Claude to read and understand your PDFs. The cost depends on the number and size of your documents.

**Rough estimate for a typical EPU month (5–15 bookings):**

| What | Approx. cost |
|------|-------------|
| Payment receipt extraction | ~€0.01 per receipt |
| Invoice extraction | ~€0.02–0.05 per invoice |
| Matching (one call for all) | ~€0.05–0.15 total |
| **Total per month** | **~€0.15–0.80** |

Costs are billed directly by Anthropic in USD. You can set a monthly spend limit in the [Anthropic console](https://console.anthropic.com).

---

## Data & privacy

fibutool processes your documents **locally** — it reads PDFs from your machine, runs them through the Anthropic API for AI-powered extraction, and writes all results back to your local files. The extracted bookkeeping data (journal CSV, match results) never leaves your machine.

The content of your invoice and payment PDFs is transmitted to the Anthropic API during the extraction step. Anthropic does not use API inputs to train their models. See [Anthropic's privacy policy](https://www.anthropic.com/privacy) for details.

---

## Usage reference

### Typical session — via orchestrator

```bat
cd C:\fibu\2026-05
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

---

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

<app directory>/                ← shared across all sessions
  config.yaml                   ← all configuration: API keys, rules, sources, journal workbook path
                                   default: %APPDATA%\fibutool\config.yaml

<permanent merged directory>/   ← user-maintained archive of all merged PDFs across sessions
                                   configured in config.yaml; used by journal_reader for cross-check
```

---

## Config reference

Default location: `%APPDATA%\fibutool\config.yaml`.  
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

For `fetcher` sources (`gmail_sources`, `filesystem_sources`) and `original_journal` configuration, see the annotated `config.yaml.example` in the repo root or in the release download.

---

## Developer documentation

See [DEVELOPER.md](DEVELOPER.md) for architecture, development environment, testing, and release instructions.

# Generalization Gap Analysis
*Generated 2026-05-22 — what needs to change for other Austrian businesses to use this tool*

## Context
Target users: Austrian small businesses using E/A Rechnung + IST-Besteuerung,
with different journal formats, different banks, different VAT rates, different transactions.

---

## 1. JOURNAL/WORKBOOK FORMAT

| Finding | File + Line | Category | Configurable? | Impact |
|---------|------------|----------|--------------|--------|
| Column header names | `journal_reader.py:40-42`, `journal_updater.py:100-101` | SCHEMA_SPECIFIC | PARTIAL — names configurable in YAML | trivial |
| Sheet name | `journal_reader.py:37`, `journal_updater.py:99` | SCHEMA_SPECIFIC | YES — in config | trivial |
| Workbook path format | `journal_reader.py:36` | SCHEMA_SPECIFIC | YES — in config | trivial |
| Excel lock file detection (`~$filename`) | `journal_updater.py:111-116` | BANK_SPECIFIC | NO | moderate |
| Receipt numbering scheme (integers only, `{year:04d}-{receipt_num:03d}`) | `orderer.py:17`, `journal.py:131` | FORMAT_ASSUMPTION | NO | moderate |
| First non-empty row assumed to be header | `journal_reader.py:61-64` | FORMAT_ASSUMPTION | NO | trivial |
| Permanent merged directory filename pattern | `journal_reader.py:153` | FORMAT_ASSUMPTION | NO | trivial |
| Year-receipt consistency check | `journal_reader.py:128-133` | FORMAT_ASSUMPTION | NO | moderate |
| CSV column positions (23 rigid columns) | `journal_updater.py:43-67` | SCHEMA_SPECIFIC | NO | **major** |
| CSV decimal separator | `journal_updater.py:25, 29` | SCHEMA_SPECIFIC | PARTIAL | trivial |

---

## 2. BANK/PAYMENT RECEIPT FORMAT

| Finding | File + Line | Category | Configurable? | Impact |
|---------|------------|----------|--------------|--------|
| PDF file format only | `process.py:167-169`, `fetcher.py:181` | FORMAT_ASSUMPTION | NO | **major** |
| Bank receipt structure (Buchungsdatum, sign conventions) | `extractor.py:14-30` | BANK_SPECIFIC | NO | **major** |
| Forex fee extraction (`Fremdwährungsentgelt`) | `extractor.py:28-29`, `models.py:29` | BANK_SPECIFIC | NO | moderate |
| Amount sign interpretation (minus=outgoing) | `extractor.py:24-28` | BANK_SPECIFIC | NO | **major** |
| Booking date format | `extractor.py:19`, `models.py:20` | FORMAT_ASSUMPTION | NO | moderate |

---

## 3. VAT & TAX LOGIC

| Finding | File + Line | Category | Configurable? | Impact |
|---------|------------|----------|--------------|--------|
| Austrian VAT quarterly deadlines (Q1→15 May, Q2→15 Aug, Q3→15 Nov, Q4→15 Feb) | `journal.py:18-25` | HARDCODED_VALUE | NO | **major** |
| Default VAT rate: 20% | `journal.py:105-106` | HARDCODED_VALUE | PARTIAL (ig_vat_rate only) | moderate |
| IG VAT rate (default 20%) | `journal.py:98, 105, 120-122` | HARDCODED_VALUE | YES — in config | trivial |
| Mixed VAT label "gemischt" | `journal.py:31-32, 91` | HARDCODED_VALUE | YES — in config | trivial |
| VAT tolerance: 0.10 EUR | `extractor.py:196` | HARDCODED_VALUE | NO | trivial |
| Position gross tolerance: 0.05 EUR | `extractor.py:236` | HARDCODED_VALUE | NO | trivial |
| Position arithmetic tolerance: 0.02 EUR | `extractor.py:228` | HARDCODED_VALUE | NO | trivial |
| Reverse-charge suppresses IG for mixed VAT (known gap G1) | `journal.py:89-93, 254` | HARDCODED_LOGIC | NO | **major** |

---

## 4. INVOICE EXTRACTION (LLM Prompts & Categories)

| Finding | File + Line | Category | Configurable? | Impact |
|---------|------------|----------|--------------|--------|
| Fixed 26-item German detail categories list | `extractor.py:32-59` | HARDCODED_VALUE | PARTIAL (rules configurable, list is not) | **major** |
| Category rule matching (substring only) | `extractor.py:118-131` | HARDCODED_LOGIC | NO | trivial |
| Default Ausgaben category | `extractor.py:129-131` | HARDCODED_VALUE | YES — in config | trivial |
| Default Einnahmen category | `extractor.py:131` | HARDCODED_VALUE | YES — in config | trivial |
| Invoice type classification (issuer/recipient detection) | `extractor.py:79-88, 389-401` | HARDCODED_LOGIC | PARTIAL — own_company_names configurable | moderate |
| VAT rate extraction: "dominant rate" | `extractor.py:94, 100-101` | HARDCODED_LOGIC | NO | moderate |
| Austrian "davon X% USt" position splitting | `extractor.py:100-103` | HARDCODED_LOGIC | NO | **major** |
| Country names in German | `extractor.py:93` | HARDCODED_LOGIC | NO | moderate |
| AfA threshold €1000 (Austrian) | `extractor.py:111` | HARDCODED_VALUE | NO | **major** |
| GWG concept (Austrian tax term) | `extractor.py:110-112` | HARDCODED_LOGIC | NO | moderate |
| LLM model: claude-sonnet-4-6 | `extractor.py:337` | HARDCODED_VALUE | NO | trivial |
| LLM model: claude-opus-4-7 | `matcher.py:88` | HARDCODED_VALUE | NO | trivial |
| Max tokens (extraction/matching) | `extractor.py:329, 399`, `matcher.py:89` | HARDCODED_VALUE | NO | trivial |
| Retry delays: 60/180/300/600s | `api.py:5` | HARDCODED_VALUE | NO | trivial |

---

## 5. MATCHING LOGIC

| Finding | File + Line | Category | Configurable? | Impact |
|---------|------------|----------|--------------|--------|
| Date window: 0–21 days before booking | `matcher.py:19` | HARDCODED_VALUE | NO | moderate |
| Amount tolerance: < 1 EUR | `matcher.py:20-21` | HARDCODED_VALUE | NO | moderate |
| No forex rate conversion | `matcher.py:20-21`, `journal.py:75` | HARDCODED_LOGIC | NO | **major** |
| Direction rules (outgoing→incoming only, etc.) | `matcher.py:22-24` | HARDCODED_LOGIC | NO | moderate |
| Invoice deduplication: first-wins, no warning | `matcher.py:134-135` | HARDCODED_LOGIC | NO | trivial |

---

## 6. BUSINESS PERCENTAGE & CLASSIFICATION

| Finding | File + Line | Category | Configurable? | Impact |
|---------|------------|----------|--------------|--------|
| Default business percentage: 100% | `models.py:57`, `process.py:282-284` | HARDCODED_VALUE | YES — in config | trivial |
| Business percentage range 0–100 (strict >0) | `extractor.py:164` | HARDCODED_VALUE | NO | trivial |
| All-or-nothing position classification per counterparty | `extractor.py:142-160` | HARDCODED_LOGIC | PARTIAL | moderate |
| Position keyword matching: substring only | `extractor.py:155-157` | HARDCODED_LOGIC | NO | trivial |

---

## 7. FETCHING & DOCUMENT SOURCES

| Finding | File + Line | Category | Configurable? | Impact |
|---------|------------|----------|--------------|--------|
| Gmail read-only scope hardcoded | `fetcher.py:34` | HARDCODED_VALUE | NO | trivial |
| Gmail pagination: 500 results | `fetcher.py:164` | HARDCODED_VALUE | NO | trivial |
| IMAP month abbreviations (English) | `fetcher.py:36-37` | HARDCODED_VALUE | NO | trivial |
| IMAP SSL port default: 993 | `config.yaml.example:69` | HARDCODED_VALUE | PARTIAL | trivial |
| Filename collision marker: `_fetched` | `fetcher.py:204-207` | HARDCODED_VALUE | NO | trivial |
| Filter combination: AND logic only | `fetcher.py:195-201` | HARDCODED_LOGIC | NO | trivial |
| Filesystem filter: mtime-based | `fetcher.py:673-680` | HARDCODED_LOGIC | NO | trivial |

---

## 8. INFRASTRUCTURE & DIRECTORY STRUCTURE

| Finding | File + Line | Category | Configurable? | Impact |
|---------|------------|----------|--------------|--------|
| Directory names: `payments/`, `invoices/`, `payments-ordered/`, `merged/` | `process.py:384-388` | HARDCODED_VALUE | NO | moderate |
| Journal CSV filename: `journal.csv` | `process.py:388` | HARDCODED_VALUE | NO | moderate |
| Match cache filename: `match_results.json` | `process.py:372` | HARDCODED_VALUE | NO | moderate |
| Fetcher seen registry: `fetcher_seen.json` | `run.py:186` | HARDCODED_VALUE | NO | moderate |
| Log file naming pattern | `shared.py:34-35` | HARDCODED_VALUE | NO | trivial |
| Config default location: same dir as script | `shared.py:8-10` | HARDCODED_VALUE | PARTIAL (`--config` flag) | trivial |

---

## 9. PDF HANDLING & MERGING

| Finding | File + Line | Category | Configurable? | Impact |
|---------|------------|----------|--------------|--------|
| Page order: invoice → overview → payment | `merger.py:14-26` | HARDCODED_LOGIC | NO | moderate |
| Overview only for mixed business/private | `merger.py:19-23` | HARDCODED_LOGIC | NO | trivial |
| Overview title: German ("Auflistung der abzugsfähigen Positionen") | `overview.py:38` | HARDCODED_VALUE | NO | trivial |
| Overview column headers: German | `overview.py:55` | HARDCODED_VALUE | NO | trivial |
| Overview labels: "abzugsfähig" / "privat" | `overview.py:63` | HARDCODED_VALUE | NO | trivial |
| Overview layout: A4, fixed column widths | `overview.py:52-53` | HARDCODED_VALUE | NO | trivial |
| Color scheme: hardcoded hex values | `overview.py:74, 85` | HARDCODED_VALUE | NO | trivial |
| Splitter: last page assumed to be payment | `splitter.py:42-45` | HARDCODED_LOGIC | NO | moderate |

---

## 10. OUTPUT & REPORTING

| Finding | File + Line | Category | Configurable? | Impact |
|---------|------------|----------|--------------|--------|
| CSV delimiter: semicolon `;` | `journal.py:38-39` | HARDCODED_VALUE | NO | moderate |
| CSV encoding: UTF-8 with BOM | `journal.py:38` | HARDCODED_VALUE | NO | trivial |
| CSV columns: 23 rigid, fixed order | `journal.py:128-153` | HARDCODED_VALUE | NO | **major** |
| Category names: "Einnahmen" / "Ausgaben" | `journal.py:52, 59` | HARDCODED_VALUE | NO | trivial |
| Boolean format: Python True/False (not Excel) | `journal.py:138` | HARDCODED_VALUE | NO | trivial |

---

## 11. KNOWN REQUIREMENTS GAPS

From `requirements/fibu.md`:

| Gap | Description | Impact |
|-----|-------------|--------|
| G1 | IG suppressed for mixed-VAT reverse-charge invoices | **major** |
| G2 | Foreign-currency invoice with partial business use produces wrong EUR amounts | **major** |
| G3 | `invoice.matched` field written but never read (dead code) | trivial |

---

## Summary

### What IS already configurable
- `own_company_names`, `category_rules`, `business_percentage_rules`, `position_business_rules`
- `mixed_vat_label`, `decimal_separator`, `ig_vat_rate`
- `default_einnahmen_category`, `default_ausgaben_category`
- Excel journal: path, sheet name, column header names
- Fetcher: Gmail labels/folders, IMAP host/port/user, filesystem paths, since_days

### Critical Barriers (block adoption completely)
1. 26 German detail categories hardcoded in Python — cannot be changed via config
2. Austrian VAT quarterly deadlines (wrong for any non-AT accounting period)
3. CSV structure: 23 rigid German-named columns — different journal = unusable
4. Austrian invoice format assumptions in LLM prompts (davon USt, AfA €1000, GWG)
5. Bank receipt parsing coupled to Austrian sign conventions and field names
6. Receipt number max 999/year (wraps at 1000)
7. No forex rate conversion — multi-currency businesses blocked
8. IG suppressed for mixed-VAT reverse-charge (G1)

### Moderate Barriers (config + small code changes)
- Matching date window and amount tolerance hardcoded
- Directory structure hardcoded
- Excel lock file detection (Windows-only pattern)
- Rounding tolerances hardcoded
- All-or-nothing position classification

### Trivial Barriers (one-liners)
- German text in overview PDF, CSV column names, log messages
- LLM model names, max tokens, retry delays
- CSV delimiter, encoding
- Keyring service name, filename markers

# fibutool — System Overview

This document orients new developers. Individual requirements files cover each component in detail.

---

## What the system does

fibutool automates the bookkeeping preparation work for an Austrian Einnahmen-Ausgaben-Rechnung. Given a set of bank payment receipts and supplier invoices (all PDFs), it:

1. Retrieves invoice documents automatically from email and local filesystem sources
2. Extracts structured fields from each PDF using Claude (date, amount, counterparty, VAT, etc.)
3. Matches each bank payment to its corresponding invoice
4. Merges matched pairs into a single archive PDF per transaction
5. Produces a semicolon-delimited CSV journal ready for import into Excel

---

## Layers

The system is split into three layers that can be used independently or together.

### 1. Acquisition layer

Retrieves invoice PDFs from configured sources and deposits them into the session work directory. Sources include Google Workspace email accounts and local filesystem paths; further source types (IMAP, web portals) are planned.

De-duplication is handled via a persistent seen registry so re-runs never produce duplicate files.

### 2. Processing layer

The core bookkeeping pipeline. Takes bank payment receipts (placed manually by the user) and invoice PDFs (from the acquisition layer or placed manually) and runs the extract → order → match → merge → journal steps. Produces ordered payment copies, merged PDFs, and the CSV journal.

The processing layer requires the user to know the last receipt number used in the previous session. This is read automatically from the original journal workbook when the orchestration layer is used.

### 3. Orchestration layer

A thin wrapper that ties the layers together for the common case: reads the last receipt number and latest payment date from the original journal Excel workbook, prompts the user to manually download bank payment receipts, then runs the acquisition layer followed by the processing layer. Provides abort / retry / continue recovery at each stage.

---

## Shared concepts

**Work directory** — a per-session folder the user creates for each bookkeeping run. Contains all input PDFs, output files, and intermediary data for that session. Both the acquisition and processing layers operate within the same work directory.

**App directory** — shared across all sessions. Contains the single config file. By default this is the directory containing the scripts themselves; it can be overridden with `--config`.

**Config file** (`config.yaml`) — one file covers all three layers: API keys, matching rules, email source credentials, filesystem source paths, and the original journal workbook location.

**Original journal** — an Excel workbook maintained by the user that records all past bookkeeping entries. The orchestration layer reads from it; it is never written to by the system (writing back is a planned future feature).

**Permanent merged directory** — a user-maintained archive of all merged PDFs across all sessions. Used by the orchestration layer to cross-check the last receipt number against the original journal before each run.

---

## Typical workflow

```
[once per session]

1. Orchestration layer reads original journal
   → determines last receipt number N and latest payment date D

2. User downloads bank payment receipts since D
   → places them in the work directory manually (bank portal, not automatable)

3. Acquisition layer runs automatically
   → fetches invoice PDFs from email and filesystem sources

4. Processing layer runs automatically
   → extracts, matches, merges, writes journal.csv
```

Each layer can also be invoked standalone for partial runs, single-source fetches, or journal regeneration.

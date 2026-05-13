# run — Requirements

`run.py` is the session orchestrator. It ties the acquisition and processing layers together for the common case, eliminating the manual steps of looking up the last receipt number and latest payment date before each run.

---

## Responsibilities

- Read last receipt number and latest payment date from the original journal (via `journal_reader`)
- Compute the fetcher since date as `latest_payment_date - since_offset_days`
- Guide the user through the one manual step (downloading bank payment receipts)
- Run the acquisition layer (fetcher) and processing layer (fibutool) as subprocesses in sequence
- Offer abort / retry / continue recovery at every failing stage

---

## Stages

### Stage 1 — Read journal

- **R1.1** Call `read_journal_state(config)` to obtain `(last_receipt_number, latest_payment_date)`. See the journal_reader requirements for the reading and cross-check logic.
- **R1.2** Compute `since_date = latest_payment_date - since_offset_days` (configured in `original_journal.since_offset_days`; default 14 days).
- **R1.3** Display the three values (last receipt number, latest payment date, computed since date) before proceeding.
- **R1.4** On failure: prompt **[a]bort / [r]etry / [c]ontinue**.
  - Abort: exit.
  - Retry: re-read the journal (useful if the user updates the workbook).
  - Continue: prompt the user to enter `last_receipt_number` (integer) and `since_date` (YYYY-MM-DD) manually. Re-prompt on invalid input for each field; only Ctrl+C aborts.

### Stage 2 — User downloads payment receipts

- **R2.1** Display `since_date` and the full path of the `payments/` directory.
- **R2.2** Wait for the user to press Enter.
- **R2.3** After confirmation: verify that `payments/` exists and contains at least one PDF file (case-insensitive: `*.pdf` and `*.PDF`). If either check fails, display a specific message and re-prompt — do not proceed to Stage 3 with an empty payments directory.

### Stage 3 — Acquisition (fetcher)

- **R3.1** Run the acquisition layer with `--since since_date --workdir <workdir> --config <config>`.
- **R3.2** On non-zero exit: prompt **[a]bort / [r]etry / [c]ontinue**.
  - Abort: exit.
  - Retry: re-run fetcher.
  - Continue: proceed to Stage 4 with whatever invoices were collected.

### Stage 4 — Processing (fibutool)

- **R4.1** Run the processing layer with `-n last_receipt_number --workdir <workdir> --config <config>`.
- **R4.2** On non-zero exit: prompt **[a]bort / [r]etry / [c]ontinue**.
  - Abort: exit.
  - Retry: re-run fibutool.
  - Continue: accept the partial result and exit.

---

## CLI flags

- `--workdir / -w`: work directory for this session (default: current directory)
- `--config / -c`: config file override (default: `config.yaml` in the script directory)

---

## Error handling notes

- Subprocess failures are currently reported by exit code only. Improving error surfacing (capturing stderr, displaying structured failure detail) is tracked in BACKLOG.
- On Ctrl+C at any interactive prompt, run.py exits immediately.

---

## Known gaps and future work

See BACKLOG for:
- Resume mode: detect existing `match_results.json` and offer to resume the processing layer instead of a full run
- Improved subprocess error reporting

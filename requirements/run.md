# run — Requirements

`run.py` is the session orchestrator. It ties the acquisition and processing layers together for the common case, eliminating the manual steps of looking up the last receipt number and latest payment date before each run.

---

## Responsibilities

- Read last receipt number and latest payment date from the original journal (via `journal_reader`)
- Compute the fetcher since date as `latest_payment_date - since_offset_days`
- Guide the user through the one manual step (downloading bank payment receipts)
- Run the acquisition layer (fetcher) and processing layer (fibutool) as subprocesses in sequence, streaming their output through the orchestrator's own Tee so all output is captured in a single session log
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
- **R3.2** Stream stdout and stderr of the subprocess through the orchestrator's Tee (merged into a single stream). The exit code is reported on non-zero exit.
- **R3.3** On non-zero exit: prompt **[a]bort / [r]etry / [c]ontinue**.
  - Abort: exit.
  - Retry: re-run fetcher.
  - Continue: proceed to Stage 4 with whatever invoices were collected.

### Stage 4 — Processing (fibutool)

- **R4.1** If `match_results.json` exists in the work directory and `--clean` was not passed: invoke the processing layer **without** `-n` (resume mode — the receipt number is already in the cache). Print a notice to the user.
- **R4.2** Otherwise (no `match_results.json`, or `--clean` passed): invoke with `-n last_receipt_number` for a full run. If `--clean` was passed, also forward `--clean` to the processing layer.
- **R4.3** Stream stdout and stderr of the subprocess through the orchestrator's Tee (merged). The exit code is reported on non-zero exit.
- **R4.4** On non-zero exit: prompt **[a]bort / [r]etry / [c]ontinue**.
  - Abort: exit.
  - Retry: re-run fibutool.
  - Continue: accept the partial result and exit.

---

## CLI flags

- `--workdir / -w`: work directory for this session (default: current directory)
- `--config / -c`: config file override (default: `config.yaml` in the script directory)
- `--clean`: remove previous processing output and force a full run; forwarded to `fibutool-process`

---

## Logging

- **R5.1** On startup (after workdir is known), open `<ISO-datetime>_run.log` in the work directory. Mirror all output (stdout and stderr) to this file via a `_Tee`.
- **R5.2** Subprocess output is streamed through the orchestrator's `sys.stdout` Tee, so it appears in both the terminal and `_run.log`. The child processes may also write their own per-tool log files (`_fetcher.log`, `_fibutool.log`) when run standalone or for additional detail.

---

## Error handling notes

- On Ctrl+C at any interactive prompt, run.py exits immediately.

---

## Known gaps and future work

See BACKLOG for remaining items.

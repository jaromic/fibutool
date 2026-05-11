# fetcher — Requirements

fetcher downloads invoice documents from Google Workspace email accounts and deposits them as PDF files into the fibutool `invoices/` directory, eliminating manual download work between bookkeeping runs.

---

## Glossary

| Term | Meaning |
|---|---|
| Source | A configured Google Workspace account to search for invoice PDFs |
| Seen registry | A persistent record of already-downloaded files, used for de-duplication |
| Since date | The earliest Gmail message received date to include; older messages are skipped |

---

## Directory model

fetcher uses the same work directory as fibutool.

```
<workdir>/
  invoices/                output — downloaded invoice document PDFs land here
  fetcher_seen.json        state  — registry of already-downloaded files (de-duplication)
  <timestamp>_fetcher.log  output — full transcript for this run
```

Configuration lives in the shared app-directory config file (`config.yaml`) in the same directory as `fetcher.py`.

---

## Configuration (config.yaml additions)

```yaml
fetcher:
  since: "2026-01-01"          # skip messages received before this date (Gmail received date, ISO, overridable via CLI)

  gmail_sources:
    - label: "office"           # human-readable name for logs
      username: office@example.com
      client_secret_file: "~/.config/fibutool/client_secret_office.json"  # downloaded from Google Cloud Console
      token_file: "~/.config/fibutool/token_office.json"                  # created by fetcher on first run
      folders:                  # Gmail labels/folders to search (default: INBOX)
        - INBOX
      filters:                  # all filters are AND-combined; omit a list to match any value
        senders:                # match any of these sender addresses (substring, case-insensitive)
          - "@supplier.com"
        subject_keywords:       # match any of these subject substrings (case-insensitive)
          - "Rechnung"
          - "Invoice"
```

---

## Authentication — Google Workspace OAuth 2.0

fetcher uses the Gmail API with OAuth 2.0 and the `readonly` scope (`https://www.googleapis.com/auth/gmail.readonly`).

- **F0.1** A Google Cloud project with the Gmail API enabled and an OAuth 2.0 client ID (desktop app type) must be created once per Google Workspace account by the user.
- **F0.2** On first run for a source, fetcher opens a browser for the OAuth consent flow and saves the resulting token to the configured `token_file` file.
- **F0.3** On subsequent runs, fetcher loads the token from the credentials file and refreshes it automatically if expired.
- **F0.4** The credentials file must not be committed to version control (add to `.gitignore`).

---

## Step 1 — Gmail source processing

One pass per configured Gmail source.

- **F1.1** Authenticate using the OAuth 2.0 credentials file for the source.
- **F1.2** For each configured folder: search for messages received on or after the `since` date using the Gmail API.
- **F1.3** Apply sender and subject filters; a message must satisfy at least one sender match AND at least one subject keyword match (if both lists are non-empty). If a filter list is omitted, all values are accepted for that criterion.
- **F1.4** For each matching message: collect all PDF attachments.
- **F1.5** Skip any attachment whose canonical key (`<source label>/<gmail message-id>/<attachment filename>`) is already in the seen registry.
- **F1.6** Save new PDFs to `invoices/` using the original attachment filename; append a numeric suffix before the extension if a filename collision occurs (`Rechnung_2.pdf`).
- **F1.7** Record the canonical key in the seen registry after a successful save.
- **F1.8** Access mailboxes read-only. Do not modify messages, labels, or read status.

---

## Operation modes

| Mode | Trigger | Behaviour |
|---|---|---|
| **Full** | Default | Process all configured sources for the `since` date |
| **Source filter** | `--only <label>` | Process only the named source |
| **Dry run** | `--dry-run` | List what would be downloaded; do not write files or update registry |

**Flags:**
- `--since YYYY-MM-DD`: override the `since` date from config.
- `--workdir <path>`: work directory (default: current directory).
- `--config <path>`: config file override.
- `--only <label>`: process only the named source.
- `--dry-run`: report without downloading.

---

## Error handling

- Authentication failures for a source emit a warning and skip that source; other sources continue.
- All console output is mirrored to a timestamped log file.
- A summary of downloaded files and warnings is printed at the end.

---

## Known gaps

**G1 — Attachment filename collisions**
If two sources deliver a file named `Rechnung.pdf`, the second file is saved as `Rechnung_2.pdf`. The numeric suffix may be non-descriptive but is unambiguous and keeps the original name intact for the common case.

---

## Prospect — future source types

The following source types are out of scope for the MVP but are the natural next steps.

### Web portals

Each recurring supplier portal (e.g. Hetzner, Google Cloud, AWS) would be implemented as a separate Python module under `fetcher/portals/<label>.py` with a fixed interface:

```python
def fetch(config: dict, since: date, invoices_dir: Path, seen: SeenRegistry) -> list[str]:
    """Download new invoices. Returns list of saved filenames."""
```

The portal module is responsible for authentication (typically a stored API key or session cookie), navigation, and download. De-duplication uses the same seen registry with a canonical key of `<label>/<portal-internal-document-id>`.

### Filesystem sources

For invoices that are already downloaded to a local folder (e.g. a Downloads directory or a shared drive), a filesystem source would watch a configured path and copy new PDFs matching a filename pattern into `invoices/`, de-duplicating by canonical key `local_fs/<absolute path>`.

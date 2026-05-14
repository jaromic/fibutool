# fetcher — Requirements

fetcher downloads invoice documents from configured sources (Google Workspace email accounts, generic IMAP accounts, local filesystem paths) and deposits them as PDF files into the fibutool `invoices/` directory, eliminating manual download work between bookkeeping runs.

---

## Glossary

| Term | Meaning |
|---|---|
| Source | A configured input — a Google Workspace account, a generic IMAP account, or a local filesystem path |
| Seen registry | A persistent record of already-downloaded files, used for de-duplication |
| Since date | The earliest date to include; derived per source from `since_days`; for email: message date; for filesystem: file mtime |
| `since_days` | Number of days to look back from today; configured per source or overridden via `--since-days` |
| Canonical key | A stable identifier for a downloaded file stored in the seen registry |

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
  gmail_sources:
    - label: "office"           # human-readable name for logs
      username: office@example.com
      since_days: 21            # look back 21 days from today
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

  filesystem_sources:
    - label: "outgoing"         # human-readable name for logs and --only filter
      path: "~/Documents/invoices/outgoing"
      since_days: 45            # look back 45 days from today (longer cycle for credit notes)
      recursive: false          # recurse into subdirectories (default: false)
      filename_patterns:        # glob patterns; default: ["*.pdf"]
        - "*.pdf"

  imap_sources:
    - label: "mail"             # human-readable name for logs and --only filter
      host: mail.example.com    # IMAP server hostname
      port: 993                 # IMAP SSL port (default: 993)
      username: user@example.com
      since_days: 21            # look back 21 days from today
      # password stored in OS keyring; fetcher prompts on first run
      folders:
        - INBOX
      filters:                  # all filters are AND-combined; omit a list to match any value
        senders:                # match any of these sender substrings (case-insensitive, client-side)
          - "@supplier.com"
        subject_keywords:       # match any of these subject substrings (case-insensitive)
          - "Rechnung"
          - "Invoice"
```

---

## Authentication — IMAP password (OS keyring)

fetcher stores IMAP passwords in the OS keyring (via the `keyring` library). The keyring service name is `"fibutool-fetcher"`. The keyring key is `"<label>:<username>"`.

- **F0.5** On first run for an IMAP source, fetcher looks up the password in the OS keyring. If absent, it prompts the user interactively.
- **F0.6** After a successful login, fetcher stores the password in the keyring so subsequent runs are non-interactive.
- **F0.7** If the login fails, fetcher prompts for a new password and retries once. If the second attempt also fails, fetcher raises an error.
- **F0.8** The password is stored only after a successful login, never after a failed attempt.

---

## Authentication — Google Workspace OAuth 2.0

fetcher uses the Gmail API with OAuth 2.0 and the `readonly` scope (`https://www.googleapis.com/auth/gmail.readonly`).

- **F0.1** A Google Cloud project with the Gmail API enabled and an OAuth 2.0 client ID (desktop app type) must be created once per Google Workspace account by the user.
- **F0.2** On first run for a source, fetcher opens a browser for the OAuth consent flow and saves the resulting token to the configured `token_file` file.
- **F0.3** On subsequent runs, fetcher loads the token from the credentials file and refreshes it automatically if expired.
- **F0.4** The credentials file must not be committed to version control (add to `.gitignore`).

---

## Source types overview

fetcher supports three source types. At least one source of any type must be configured.

| Type | Config key | De-duplication key |
|---|---|---|
| Gmail | `gmail_sources` | `<label>/<gmail-message-id>/<filename>` |
| IMAP | `imap_sources` | `<label>/<message-id-header>/<filename>` |
| Filesystem | `filesystem_sources` | `local_fs/<sha256-of-file-content>` |

The filesystem source uses a SHA-256 content hash as its canonical key. This means:
- A file that is renamed or moved is still recognised as already downloaded.
- Two filesystem sources containing the same file content will not produce duplicate downloads.

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

## Step 2 — IMAP source processing

One pass per configured IMAP source.

- **F2.1** Authenticate using the OS keyring; see F0.5–F0.8.
- **F2.2** For each configured folder: issue an IMAP `UID SEARCH SINCE <DD-Mon-YYYY>` command against the server.
- **F2.3** Apply sender and subject filters client-side: a message must satisfy at least one sender match AND at least one subject keyword match (if both lists are non-empty). If a filter list is omitted, all values are accepted for that criterion.
- **F2.4** For each matching message: parse the raw message bytes (RFC 2822) and collect all PDF attachments (content type `application/pdf` or filename ending `.pdf`).
- **F2.5** Skip any attachment whose canonical key (`<source label>/<Message-ID header>/<filename>`) is already in the seen registry.
- **F2.6** Save new PDFs to `invoices/` using the original attachment filename; append a numeric suffix before the extension if a filename collision occurs.
- **F2.7** Record the canonical key in the seen registry after a successful save.
- **F2.8** Access mailboxes read-only (`EXAMINE` / `readonly=True`). Do not modify messages, flags, or read status.
- **F2.9** Call `LOGOUT` on the connection when done, even if an error occurred.

---

## Step 3 — Filesystem source processing

One pass per configured filesystem source.

- **F3.1** Resolve the configured `path` (expanding `~`). Emit a warning and skip the source if the path does not exist.
- **F3.2** Collect files: non-recursive by default; recurse into subdirectories if `recursive: true`.
- **F3.3** Apply filename pattern filter (glob): a file must match at least one pattern in `filename_patterns` (default: `["*.pdf"]`).
- **F3.4** Skip files whose mtime is before the since date (derived from the source's `since_days`).
- **F3.5** For each candidate: compute the SHA-256 hash of the file contents. The canonical key is `local_fs/<sha256>`.
- **F3.6** Skip any file whose canonical key is already in the seen registry.
- **F3.7** Copy new files to `invoices/` using the original filename; append a numeric suffix before the extension if a filename collision occurs.
- **F3.8** Record the canonical key in the seen registry after a successful copy.
- **F3.9** Do not modify, move, or delete the source files.

---

## Operation modes

| Mode | Trigger | Behaviour |
|---|---|---|
| **Full** | Default | Process all configured sources, each using its own `since_days` |
| **Source filter** | `--only <label>` | Process only the named source |
| **Dry run** | `--dry-run` | List what would be downloaded; do not write files or update registry |

**Flags:**
- `--since-days N` *(optional)*: override the per-source `since_days` for all sources — look back N days from today. Intended for manual one-off runs; when omitted, each source uses its configured `since_days`.
- `--workdir <path>`: work directory (default: current directory).
- `--config <path>`: config file override.
- `--only <label>`: process only the named source.
- `--dry-run`: report without downloading.

**Per-source config key:**
- `since_days` *(required unless `--since-days` is passed)*: integer number of days to look back from today. Each source type uses this to derive its cutoff date: email sources filter by message date; filesystem sources filter by file mtime.

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

### Web portals

Each recurring supplier portal (e.g. Hetzner, Google Cloud, AWS) would be implemented as a separate Python module under `fetcher/portals/<label>.py` with a fixed interface:

```python
def fetch(config: dict, since: date, invoices_dir: Path, seen: SeenRegistry) -> list[str]:
    """Download new invoices. Returns list of saved filenames."""
```

The portal module is responsible for authentication (typically a stored API key or session cookie), navigation, and download. De-duplication uses the same seen registry with a canonical key of `<label>/<portal-internal-document-id>`.

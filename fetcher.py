"""fetcher — Gmail invoice downloader for fibutool.

Downloads PDF attachments from configured Google Workspace accounts and
deposits them into the fibutool invoices/ directory.

Authentication
--------------
Uses Gmail API with OAuth 2.0 (readonly scope). On first run for a source,
opens a browser for the consent flow and saves the token to token_file.
Subsequent runs load and auto-refresh the token automatically.
"""

import argparse
import base64
import json
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


# ── Seen registry ─────────────────────────────────────────────────────────────

class SeenRegistry:
    """Persistent set of canonical keys for already-downloaded attachments."""

    def __init__(self, path: Path):
        self._path = path
        self._keys: set[str] = set()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self._keys = set(data.get("seen", []))

    def contains(self, key: str) -> bool:
        return key in self._keys

    def add(self, key: str) -> None:
        self._keys.add(key)

    def save(self) -> None:
        self._path.write_text(
            json.dumps({"seen": sorted(self._keys)}, indent=2),
            encoding="utf-8",
        )


# ── Shared utilities (mirrors main.py) ───────────────────────────────────────

def _default_config_path() -> Path:
    """Return the default config path: config.yaml in the same directory as this script."""
    return Path(__file__).parent / "config.yaml"


class _Tee:
    def __init__(self, *streams):
        self._streams = streams

    def write(self, text):
        for s in self._streams:
            s.write(text)

    def flush(self):
        for s in self._streams:
            s.flush()


def _setup_logging(workdir: Path) -> None:
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    log_path = workdir / f"{ts}_fetcher.log"
    try:
        log_file = open(log_path, "w", encoding="utf-8")
        sys.stdout = _Tee(sys.__stdout__, log_file)
        sys.stderr = _Tee(sys.__stderr__, log_file)
    except OSError as e:
        print(f"fetcher: warning — could not open log file {log_path}: {e}", file=sys.stderr)


# ── Argument parsing and configuration ───────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fetcher",
        description="fetcher — Gmail invoice downloader for fibutool",
    )
    parser.add_argument(
        "--since", metavar="YYYY-MM-DD", default=None,
        help="Download attachments from messages received on or after this date (overrides config)",
    )
    parser.add_argument(
        "--workdir", "-w", type=Path, default=Path("."), metavar="DIR",
        help="Work directory containing the invoices/ folder (default: current directory)",
    )
    parser.add_argument(
        "--config", "-c", type=Path, default=None, metavar="FILE",
        help=f"Config file (default: {_default_config_path()})",
    )
    parser.add_argument(
        "--only", metavar="LABEL", default=None,
        help="Process only the source with this label",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List what would be downloaded without writing files or updating the seen registry",
    )
    return parser.parse_args()


def _load_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def pl_load_fetcher_config(config: dict) -> dict:
    fetcher_cfg = config.get("fetcher")
    if not fetcher_cfg:
        print("fetcher: config error — no 'fetcher' section found in config.yaml", file=sys.stderr)
        sys.exit(1)
    if not fetcher_cfg.get("gmail_sources"):
        print("fetcher: config error — 'fetcher.gmail_sources' is empty or missing", file=sys.stderr)
        sys.exit(1)
    return fetcher_cfg


# ── Gmail helpers ─────────────────────────────────────────────────────────────

def _authenticate_gmail(client_secret_file: Path, token_file: Path):
    """Return an authenticated Gmail API service object.

    On first run opens a browser for the OAuth consent flow and saves the
    token to token_file. On subsequent runs loads and refreshes it.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_secret_file.exists():
                raise FileNotFoundError(
                    f"Client secret file not found: {client_secret_file}\n"
                    "Download it from Google Cloud Console (APIs & Services > Credentials)\n"
                    "and save it to the path configured as 'client_secret_file'."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), GMAIL_SCOPES)
            try:
                creds = flow.run_local_server(port=0)
            except Exception as e:
                raise RuntimeError(
                    f"Could not open browser for OAuth flow ({e}).\n"
                    "Run fetcher.py on a machine with a browser to complete the one-time authorisation.\n"
                    "The saved token file can then be copied to any headless environment."
                ) from e

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def _list_messages(service, folder: str, query: str) -> list[dict]:
    """Return all message stubs matching query in folder, handling pagination."""
    results = []
    page_token = None
    while True:
        kwargs: dict = dict(userId="me", q=f"in:{folder} {query}", maxResults=500)
        if page_token:
            kwargs["pageToken"] = page_token
        response = service.users().messages().list(**kwargs).execute()
        results.extend(response.get("messages", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return results


def _find_pdf_parts(payload: dict) -> list[dict]:
    """Recursively find all PDF attachment parts in a Gmail message payload."""
    results = []
    filename = payload.get("filename", "")
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})
    if (filename.lower().endswith(".pdf") or mime_type == "application/pdf") and (
        body.get("attachmentId") or body.get("data")
    ):
        results.append(payload)
    for part in payload.get("parts", []):
        results.extend(_find_pdf_parts(part))
    return results


def _matches_filters(
    from_header: str,
    subject_header: str,
    senders: list[str],
    subject_keywords: list[str],
) -> bool:
    """Return True if the message passes the sender and subject filters."""
    if senders and not any(s.lower() in from_header.lower() for s in senders):
        return False
    if subject_keywords and not any(kw.lower() in subject_header.lower() for kw in subject_keywords):
        return False
    return True


def _safe_filename(invoices_dir: Path, name: str) -> Path:
    """Return a collision-free path in invoices_dir for the given filename."""
    stem = Path(name).stem
    suffix = Path(name).suffix or ".pdf"
    candidate = invoices_dir / name
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = invoices_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


# ── Source processing ─────────────────────────────────────────────────────────

def _process_gmail_source(
    source: dict,
    since: date,
    invoices_dir: Path,
    seen: SeenRegistry,
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    label = source.get("label", "?")
    username = source.get("username", "?")
    client_secret_file = Path(source["client_secret_file"]).expanduser()
    token_file = Path(source["token_file"]).expanduser()
    senders: list[str] = source.get("filters", {}).get("senders", [])
    subject_keywords: list[str] = source.get("filters", {}).get("subject_keywords", [])
    folders: list[str] = source.get("folders", ["INBOX"])

    print(f"\nSource [{label}] ({username})")

    try:
        service = _authenticate_gmail(client_secret_file, token_file)
    except Exception as e:
        return [], [f"[fetcher/{label}] authentication failed: {e}"]

    saved_files: list[str] = []
    warnings: list[str] = []
    date_query = f"after:{since.strftime('%Y/%m/%d')}"

    for folder in folders:
        query = date_query
        if senders:
            sender_q = " OR ".join(f"from:{s}" for s in senders)
            query += f" ({sender_q})"

        print(f"  [{folder}] query: {query}")

        try:
            messages = _list_messages(service, folder, query)
        except Exception as e:
            warnings.append(f"[fetcher/{label}] failed to search {folder}: {e}")
            continue

        print(f"  {len(messages)} message(s) returned")

        for msg_stub in messages:
            msg_id = msg_stub["id"]

            try:
                meta = service.users().messages().get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["From", "Subject"],
                ).execute()
            except Exception as e:
                warnings.append(f"[fetcher/{label}] failed to fetch metadata for {msg_id}: {e}")
                continue

            headers = {
                h["name"]: h["value"]
                for h in meta.get("payload", {}).get("headers", [])
            }
            from_header = headers.get("From", "")
            subject_header = headers.get("Subject", "")

            if not _matches_filters(from_header, subject_header, senders, subject_keywords):
                continue

            try:
                full_msg = service.users().messages().get(
                    userId="me", id=msg_id, format="full",
                ).execute()
            except Exception as e:
                warnings.append(f"[fetcher/{label}] failed to fetch message {msg_id}: {e}")
                continue

            pdf_parts = _find_pdf_parts(full_msg.get("payload", {}))

            for part in pdf_parts:
                filename = part.get("filename") or "attachment.pdf"
                attachment_id = part.get("body", {}).get("attachmentId")
                inline_data = part.get("body", {}).get("data")

                canonical_key = f"{label}/{msg_id}/{filename}"
                if seen.contains(canonical_key):
                    continue

                if dry_run:
                    print(f"  [dry-run] would save: {filename}  (from: {from_header})")
                    saved_files.append(filename)
                    continue

                if attachment_id:
                    try:
                        att = service.users().messages().attachments().get(
                            userId="me", messageId=msg_id, id=attachment_id,
                        ).execute()
                        raw_data = att.get("data", "")
                    except Exception as e:
                        warnings.append(
                            f"[fetcher/{label}] failed to download {filename} from {msg_id}: {e}"
                        )
                        continue
                else:
                    raw_data = inline_data or ""

                if not raw_data:
                    warnings.append(f"[fetcher/{label}] empty attachment {filename} in {msg_id}")
                    continue

                pdf_bytes = base64.urlsafe_b64decode(raw_data + "==")
                out_path = _safe_filename(invoices_dir, filename)
                out_path.write_bytes(pdf_bytes)
                seen.add(canonical_key)
                saved_files.append(out_path.name)
                print(f"  saved: {out_path.name}")

    return saved_files, warnings


# ── Summary ───────────────────────────────────────────────────────────────────

def _print_summary(saved: list[str], warnings: list[str], dry_run: bool) -> None:
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  ⚠  {w}")
    if dry_run:
        print(f"\nfetcher done — dry run, {len(saved)} file(s) would be saved.")
    else:
        print(f"\nfetcher done — {len(saved)} file(s) saved, {len(warnings)} warning(s).")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = _parse_args()
    workdir = args.workdir

    _setup_logging(workdir)

    config_path = args.config if args.config is not None else _default_config_path()
    print(f"fetcher  |  config: {config_path}  |  workdir: {workdir.resolve()}")

    config = _load_config(config_path)
    fetcher_cfg = pl_load_fetcher_config(config)

    since_str = args.since or fetcher_cfg.get("since")
    if not since_str:
        print("fetcher: error — 'since' date is required (set in config or via --since)", file=sys.stderr)
        sys.exit(1)
    try:
        since = date.fromisoformat(since_str)
    except ValueError:
        print(f"fetcher: error — invalid since date '{since_str}' (expected YYYY-MM-DD)", file=sys.stderr)
        sys.exit(1)

    invoices_dir = workdir / "invoices"
    invoices_dir.mkdir(parents=True, exist_ok=True)

    seen = SeenRegistry(workdir / "fetcher_seen.json")

    sources: list[dict] = fetcher_cfg.get("gmail_sources", [])
    if args.only:
        sources = [s for s in sources if s.get("label") == args.only]
        if not sources:
            print(f"fetcher: error — no source with label '{args.only}' found in config", file=sys.stderr)
            sys.exit(1)

    all_saved: list[str] = []
    all_warnings: list[str] = []

    for source in sources:
        saved, warnings = _process_gmail_source(source, since, invoices_dir, seen, args.dry_run)
        all_saved.extend(saved)
        all_warnings.extend(warnings)

    if not args.dry_run:
        seen.save()

    _print_summary(all_saved, all_warnings, args.dry_run)


if __name__ == "__main__":
    main()

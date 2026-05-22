"""fetcher — invoice document downloader for fibutool.

Downloads PDF attachments from configured sources (Gmail, IMAP, local filesystem)
and deposits them into the fibutool invoices/ directory.

Authentication
--------------
Gmail:  OAuth 2.0 (readonly scope). On first run opens a browser for the consent
        flow and saves the token to token_file. Subsequent runs auto-refresh.
IMAP:   Password stored in the OS keyring (via the keyring library). On first run
        prompts the user; stores the password only after a successful login.
"""

import argparse
import base64
import email
import email.header
import fnmatch
import getpass
import hashlib
import imaplib
import json
import os.path
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import keyring
import yaml

from shared import default_config_path, setup_logging

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
IMAP_KEYRING_SERVICE = "fibutool-fetcher"
_IMAP_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


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


# ── Argument parsing and configuration ───────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetcher",
        description="fetcher — Gmail invoice downloader for fibutool",
    )
    parser.add_argument(
        "--since-days", metavar="N", type=int, default=None,
        help="Override per-source since_days: look back N days from anchor-date (or today) across all sources",
    )
    parser.add_argument(
        "--anchor-date", metavar="DATE", type=date.fromisoformat, default=None,
        help="Anchor date for since_days calculation (ISO format: YYYY-MM-DD); defaults to today",
    )
    parser.add_argument(
        "--workdir", "-w", type=Path, default=Path("."), metavar="DIR",
        help="Work directory containing the invoices/ folder (default: current directory)",
    )
    parser.add_argument(
        "--config", "-c", type=Path, default=None, metavar="FILE",
        help=f"Config file (default: {default_config_path()})",
    )
    parser.add_argument(
        "--only", metavar="LABEL", default=None,
        help="Process only the source with this label",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List what would be downloaded without writing files or updating the seen registry",
    )
    return parser


def _parse_args() -> argparse.Namespace:
    return build_parser().parse_args()


def _load_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def pl_load_fetcher_config(config: dict) -> dict:
    fetcher_cfg = config.get("fetcher")
    if fetcher_cfg is None:
        print("fetcher: config error — no 'fetcher' section found in config.yaml", file=sys.stderr)
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
        os.chmod(token_file, 0o600)

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


def _fetched_name(filename: str) -> str:
    """Append _fetched before the extension so fetched files are identifiable."""
    p = Path(filename)
    return f"{p.stem}_fetched{p.suffix}"


def _safe_filename(invoices_dir: Path, name: str, content: bytes) -> Path | None:
    """Return a collision-free path in invoices_dir for the given filename and content.

    Returns None if identical content already exists under any candidate path
    (duplicate — caller should skip the save).
    """
    stem = Path(name).stem
    suffix = Path(name).suffix or ".pdf"
    content_hash = hashlib.sha256(content).digest()
    counter = 2
    candidate = invoices_dir / name
    if not candidate.resolve().is_relative_to(invoices_dir.resolve()):
        raise ValueError(f"Unsafe attachment filename rejected: {name!r}")
    while True:
        if not candidate.exists():
            return candidate
        if hashlib.sha256(candidate.read_bytes()).digest() == content_hash:
            return None  # identical content already saved
        candidate = invoices_dir / f"{stem}_{counter}{suffix}"
        counter += 1


# ── Filesystem helpers ────────────────────────────────────────────────────────

def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── IMAP helpers ──────────────────────────────────────────────────────────────

def _imap_date(d: date) -> str:
    """Format a date as DD-Mon-YYYY for IMAP SINCE criterion."""
    return f"{d.day:02d}-{_IMAP_MONTHS[d.month - 1]}-{d.year}"


def _authenticate_imap(source: dict) -> imaplib.IMAP4_SSL:
    """Connect and log in to an IMAP server.

    Looks up the password in the OS keyring. If absent, prompts the user.
    Tries once; if the login fails, prompts again for a new password and retries
    once more. Stores the password in the keyring only after a successful login.
    """
    host: str = source["host"]
    port: int = source.get("port", 993)
    username: str = source["username"]
    label: str = source.get("label", host)
    keyring_key = f"{label}:{username}"

    password = keyring.get_password(IMAP_KEYRING_SERVICE, keyring_key)

    for attempt in range(2):
        if password is None:
            password = getpass.getpass(
                f"IMAP password for {username}@{host} (source [{label}]): "
            )
        try:
            conn = imaplib.IMAP4_SSL(host, port)
            conn.login(username, password)
            keyring.set_password(IMAP_KEYRING_SERVICE, keyring_key, password)
            return conn
        except imaplib.IMAP4.error:
            print(f"  authentication failed for {username}@{host} (attempt {attempt + 1})")
            password = None  # force re-prompt on next iteration

    raise RuntimeError(f"[fetcher/{label}] IMAP authentication failed after 2 attempts")


def _imap_pdf_attachments(raw_bytes: bytes) -> list[tuple[str, bytes]]:
    """Parse a raw RFC 2822 message and return (filename, data) for every PDF attachment."""
    msg = email.message_from_bytes(raw_bytes)
    results: list[tuple[str, bytes]] = []
    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = part.get("Content-Disposition", "")
        if content_type != "application/pdf" and not part.get_filename("").lower().endswith(".pdf"):
            continue
        if "attachment" not in disposition.lower() and "inline" not in disposition.lower():
            # also accept parts with no explicit disposition when they look like PDFs
            if content_type != "application/pdf":
                continue
        raw_filename = part.get_filename("")
        if raw_filename:
            decoded_parts = email.header.decode_header(raw_filename)
            filename = "".join(
                fragment.decode(enc or "utf-8") if isinstance(fragment, bytes) else fragment
                for fragment, enc in decoded_parts
            )
        else:
            filename = "attachment.pdf"
        data = part.get_payload(decode=True)
        if data:
            results.append((filename, data))
    return results


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

        filter_skipped = 0
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
                filter_skipped += 1
                continue

            try:
                full_msg = service.users().messages().get(
                    userId="me", id=msg_id, format="full",
                ).execute()
            except Exception as e:
                warnings.append(f"[fetcher/{label}] failed to fetch message {msg_id}: {e}")
                continue

            pdf_parts = _find_pdf_parts(full_msg.get("payload", {}))

            if not pdf_parts:
                print(f"  skipped (no PDF attachments): \"{subject_header}\"  (from: {from_header})")
                continue

            for part in pdf_parts:
                filename = part.get("filename") or "attachment.pdf"
                attachment_id = part.get("body", {}).get("attachmentId")
                inline_data = part.get("body", {}).get("data")

                canonical_key = f"{label}/{msg_id}/{filename}"
                if seen.contains(canonical_key):
                    print(f"  skipped (already downloaded): {filename}  (from: {from_header})")
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
                out_path = _safe_filename(invoices_dir, _fetched_name(filename), pdf_bytes)
                if out_path is None:
                    print(f"  skipped (duplicate): {filename}")
                    continue
                out_path.write_bytes(pdf_bytes)
                seen.add(canonical_key)
                saved_files.append(out_path.name)
                print(f"  saved: {out_path.name}")

        if filter_skipped:
            print(f"  {filter_skipped} message(s) skipped by filter")

    return saved_files, warnings


def _process_filesystem_source(
    source: dict,
    since: date,
    invoices_dir: Path,
    seen: SeenRegistry,
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    label = source.get("label", "?")
    src_path = Path(source["path"]).expanduser()
    recursive: bool = source.get("recursive", False)
    patterns: list[str] = source.get("filename_patterns", ["*.pdf"])

    print(f"\nSource [{label}] (filesystem: {src_path})")

    if not src_path.exists():
        return [], [f"[fetcher/{label}] path does not exist: {src_path}"]

    candidates = list(src_path.rglob("*") if recursive else src_path.iterdir())
    since_ts = datetime.combine(since, time()).timestamp()
    matching = [
        f for f in candidates
        if f.is_file() and any(fnmatch.fnmatch(f.name, p) for p in patterns)
        and f.stat().st_mtime >= since_ts
    ]

    print(f"  {len(matching)} file(s) matched")

    saved_files: list[str] = []
    warnings: list[str] = []

    for src_file in sorted(matching):
        try:
            sha256 = _sha256_of_file(src_file)
        except OSError as e:
            warnings.append(f"[fetcher/{label}] could not read {src_file.name}: {e}")
            continue

        canonical_key = f"local_fs/{sha256}"
        if seen.contains(canonical_key):
            print(f"  skipped (already downloaded): {src_file.name}")
            continue

        if dry_run:
            print(f"  [dry-run] would save: {src_file.name}")
            saved_files.append(src_file.name)
            continue

        file_bytes = src_file.read_bytes()
        out_path = _safe_filename(invoices_dir, _fetched_name(src_file.name), file_bytes)
        if out_path is None:
            print(f"  skipped (duplicate): {src_file.name}")
            continue
        out_path.write_bytes(file_bytes)
        seen.add(canonical_key)
        saved_files.append(out_path.name)
        print(f"  saved: {out_path.name}")

    return saved_files, warnings


def _process_imap_source(
    source: dict,
    since: date,
    invoices_dir: Path,
    seen: SeenRegistry,
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    label = source.get("label", "?")
    username = source.get("username", "?")
    senders: list[str] = source.get("filters", {}).get("senders", [])
    subject_keywords: list[str] = source.get("filters", {}).get("subject_keywords", [])
    folders: list[str] = source.get("folders", ["INBOX"])

    print(f"\nSource [{label}] ({username})")

    try:
        conn = _authenticate_imap(source)
    except Exception as e:
        return [], [f"[fetcher/{label}] authentication failed: {e}"]

    saved_files: list[str] = []
    warnings: list[str] = []
    since_str = _imap_date(since)

    try:
        for folder in folders:
            try:
                status, _ = conn.select(folder, readonly=True)
                if status != "OK":
                    warnings.append(f"[fetcher/{label}] could not select folder '{folder}'")
                    continue
            except imaplib.IMAP4.error as e:
                warnings.append(f"[fetcher/{label}] error selecting folder '{folder}': {e}")
                continue

            print(f"  [{folder}] SEARCH SINCE {since_str}")

            try:
                status, data = conn.uid("SEARCH", None, f"SINCE {since_str}")
                if status != "OK":
                    warnings.append(f"[fetcher/{label}] SEARCH failed in '{folder}'")
                    continue
            except imaplib.IMAP4.error as e:
                warnings.append(f"[fetcher/{label}] SEARCH error in '{folder}': {e}")
                continue

            uids = data[0].split() if data[0] else []
            print(f"  {len(uids)} message(s) returned")

            filter_skipped = 0
            for uid in uids:
                try:
                    status, msg_data = conn.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)])")
                    if status != "OK" or not msg_data or not msg_data[0]:
                        warnings.append(f"[fetcher/{label}] failed to fetch headers for UID {uid.decode()}")
                        continue
                except imaplib.IMAP4.error as e:
                    warnings.append(f"[fetcher/{label}] error fetching headers for UID {uid.decode()}: {e}")
                    continue

                raw_headers = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
                header_msg = email.message_from_bytes(raw_headers)
                from_header = header_msg.get("From", "")
                subject_raw = header_msg.get("Subject", "")
                message_id = header_msg.get("Message-ID", uid.decode())

                # Decode encoded subject header
                decoded_subject_parts = email.header.decode_header(subject_raw)
                subject_header = "".join(
                    fragment.decode(enc or "utf-8") if isinstance(fragment, bytes) else fragment
                    for fragment, enc in decoded_subject_parts
                )

                if not _matches_filters(from_header, subject_header, senders, subject_keywords):
                    filter_skipped += 1
                    continue

                try:
                    status, msg_data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                    if status != "OK" or not msg_data or not msg_data[0]:
                        warnings.append(f"[fetcher/{label}] failed to fetch message UID {uid.decode()}")
                        continue
                except imaplib.IMAP4.error as e:
                    warnings.append(f"[fetcher/{label}] error fetching message UID {uid.decode()}: {e}")
                    continue

                raw_bytes = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
                attachments = _imap_pdf_attachments(raw_bytes)

                if not attachments:
                    print(f"  skipped (no PDF attachments): \"{subject_header}\"  (from: {from_header})")
                    continue

                for filename, pdf_bytes in attachments:
                    canonical_key = f"{label}/{message_id}/{filename}"
                    if seen.contains(canonical_key):
                        print(f"  skipped (already downloaded): {filename}  (from: {from_header})")
                        continue

                    if dry_run:
                        print(f"  [dry-run] would save: {filename}  (from: {from_header})")
                        saved_files.append(filename)
                        continue

                    out_path = _safe_filename(invoices_dir, _fetched_name(filename), pdf_bytes)
                    if out_path is None:
                        print(f"  skipped (duplicate): {filename}  (from: {from_header})")
                        continue
                    out_path.write_bytes(pdf_bytes)
                    seen.add(canonical_key)
                    saved_files.append(out_path.name)
                    print(f"  saved: {out_path.name}")

            if filter_skipped:
                print(f"  {filter_skipped} message(s) skipped by filter")
    finally:
        try:
            conn.logout()
        except Exception:
            pass

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

    setup_logging(workdir, "fetcher")

    config_path = args.config if args.config is not None else default_config_path()
    print(f"fetcher  |  config: {config_path}  |  workdir: {workdir.resolve()}")

    config = _load_config(config_path)
    fetcher_cfg = pl_load_fetcher_config(config)

    invoices_dir = workdir / "invoices"
    if not os.path.exists(invoices_dir):
        print(f"  Directory {invoices_dir}/ does not exist — please create it.")
        sys.exit(1)

    seen = SeenRegistry(workdir / "fetcher_seen.json")

    all_sources: list[tuple[str, dict]] = (
        [("gmail", s) for s in fetcher_cfg.get("gmail_sources", [])] +
        [("filesystem", s) for s in fetcher_cfg.get("filesystem_sources", [])] +
        [("imap", s) for s in fetcher_cfg.get("imap_sources", [])]
    )

    if args.only:
        all_sources = [(t, s) for t, s in all_sources if s.get("label") == args.only]
        if not all_sources:
            print(f"fetcher: error — no source with label '{args.only}' found in config", file=sys.stderr)
            sys.exit(1)

    if not all_sources:
        print("fetcher: config error — no sources configured (add gmail_sources, filesystem_sources, or imap_sources)", file=sys.stderr)
        sys.exit(1)

    all_saved: list[str] = []
    all_warnings: list[str] = []

    for source_type, source in all_sources:
        label = source.get("label", "?")
        since_days = args.since_days if args.since_days is not None else source.get("since_days")
        if since_days is None:
            print(f"fetcher: error — source [{label}] has no since_days configured and --since-days was not provided", file=sys.stderr)
            all_warnings.append(f"[fetcher/{label}] skipped — no since_days configured")
            continue
        anchor = args.anchor_date or date.today()
        since = anchor - timedelta(days=since_days)
        print(f"  since: {since}  ({since_days} days before {anchor})")

        if source_type == "gmail":
            saved, warnings = _process_gmail_source(source, since, invoices_dir, seen, args.dry_run)
        elif source_type == "imap":
            saved, warnings = _process_imap_source(source, since, invoices_dir, seen, args.dry_run)
        else:
            saved, warnings = _process_filesystem_source(source, since, invoices_dir, seen, args.dry_run)
        all_saved.extend(saved)
        all_warnings.extend(warnings)

    if not args.dry_run:
        seen.save()

    _print_summary(all_saved, all_warnings, args.dry_run)


if __name__ == "__main__":
    main()

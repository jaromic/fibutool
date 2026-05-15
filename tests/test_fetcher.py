import base64
import email.encoders
import email.mime.base
import email.mime.multipart
import email.mime.text
import imaplib
import json
import time
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from fetcher import (
    SeenRegistry,
    _authenticate_imap,
    _fetched_name,
    _find_pdf_parts,
    _imap_date,
    _imap_pdf_attachments,
    _matches_filters,
    _process_filesystem_source,
    _process_gmail_source,
    _process_imap_source,
    _safe_filename,
    _sha256_of_file,
    pl_load_fetcher_config,
)

PDF_BYTES = b"%PDF-1.4 test content"
PDF_B64 = base64.urlsafe_b64encode(PDF_BYTES).decode().rstrip("=")


# ── SeenRegistry ──────────────────────────────────────────────────────────────

class TestSeenRegistry:
    def test_empty_on_new_path(self, tmp_path):
        reg = SeenRegistry(tmp_path / "seen.json")
        assert not reg.contains("office/msg1/invoice.pdf")

    def test_add_and_contains(self, tmp_path):
        reg = SeenRegistry(tmp_path / "seen.json")
        reg.add("office/msg1/invoice.pdf")
        assert reg.contains("office/msg1/invoice.pdf")
        assert not reg.contains("office/msg2/invoice.pdf")

    def test_round_trip(self, tmp_path):
        path = tmp_path / "seen.json"
        reg = SeenRegistry(path)
        reg.add("a/b/c.pdf")
        reg.add("x/y/z.pdf")
        reg.save()

        reg2 = SeenRegistry(path)
        assert reg2.contains("a/b/c.pdf")
        assert reg2.contains("x/y/z.pdf")
        assert not reg2.contains("missing")

    def test_keys_sorted_on_save(self, tmp_path):
        path = tmp_path / "seen.json"
        reg = SeenRegistry(path)
        reg.add("z/last")
        reg.add("a/first")
        reg.save()
        data = json.loads(path.read_text())
        assert data["seen"] == ["a/first", "z/last"]

    def test_load_from_existing_file(self, tmp_path):
        path = tmp_path / "seen.json"
        path.write_text(json.dumps({"seen": ["existing/key"]}), encoding="utf-8")
        reg = SeenRegistry(path)
        assert reg.contains("existing/key")


# ── _safe_filename ────────────────────────────────────────────────────────────

class TestFetchedName:
    def test_adds_fetched_suffix(self):
        assert _fetched_name("invoice.pdf") == "invoice_fetched.pdf"

    def test_preserves_extension_case(self):
        assert _fetched_name("doc.PDF") == "doc_fetched.PDF"

    def test_no_extension(self):
        assert _fetched_name("invoice") == "invoice_fetched"


class TestSafeFilename:
    def test_no_collision(self, tmp_path):
        assert _safe_filename(tmp_path, "invoice.pdf", b"data") == tmp_path / "invoice.pdf"

    def test_one_collision_different_content(self, tmp_path):
        (tmp_path / "invoice.pdf").write_bytes(b"x")
        assert _safe_filename(tmp_path, "invoice.pdf", b"y") == tmp_path / "invoice_2.pdf"

    def test_multiple_collisions_different_content(self, tmp_path):
        (tmp_path / "invoice.pdf").write_bytes(b"x")
        (tmp_path / "invoice_2.pdf").write_bytes(b"y")
        assert _safe_filename(tmp_path, "invoice.pdf", b"z") == tmp_path / "invoice_3.pdf"

    def test_preserves_suffix(self, tmp_path):
        (tmp_path / "doc.PDF").write_bytes(b"x")
        result = _safe_filename(tmp_path, "other.PDF", b"y")
        assert result.suffix == ".PDF"

    def test_duplicate_content_returns_none(self, tmp_path):
        (tmp_path / "invoice.pdf").write_bytes(b"same")
        assert _safe_filename(tmp_path, "invoice.pdf", b"same") is None

    def test_duplicate_content_under_numbered_name_returns_none(self, tmp_path):
        (tmp_path / "invoice.pdf").write_bytes(b"x")
        (tmp_path / "invoice_2.pdf").write_bytes(b"same")
        assert _safe_filename(tmp_path, "invoice.pdf", b"same") is None


# ── _matches_filters ──────────────────────────────────────────────────────────

class TestMatchesFilters:
    def test_no_filters_always_matches(self):
        assert _matches_filters("anyone@example.com", "Hello", [], [])

    def test_sender_substring_match(self):
        assert _matches_filters("billing@supplier.com", "Hi", ["@supplier.com"], [])

    def test_sender_no_match(self):
        assert not _matches_filters("other@example.com", "Hi", ["@supplier.com"], [])

    def test_subject_case_insensitive(self):
        assert _matches_filters("a@b.com", "Ihre RECHNUNG März", [], ["rechnung"])

    def test_subject_no_match(self):
        assert not _matches_filters("a@b.com", "Hello there", [], ["Rechnung", "Invoice"])

    def test_both_conditions_required(self):
        assert _matches_filters("b@supplier.com", "Rechnung #1", ["@supplier.com"], ["Rechnung"])
        assert not _matches_filters("b@supplier.com", "Hello", ["@supplier.com"], ["Rechnung"])
        assert not _matches_filters("other@x.com", "Rechnung #1", ["@supplier.com"], ["Rechnung"])

    def test_any_sender_in_list_matches(self):
        assert _matches_filters("a@one.com", "ok", ["@one.com", "@two.com"], [])
        assert _matches_filters("b@two.com", "ok", ["@one.com", "@two.com"], [])

    def test_any_keyword_in_list_matches(self):
        assert _matches_filters("a@b.com", "Invoice #42", [], ["Rechnung", "Invoice"])


# ── _find_pdf_parts ───────────────────────────────────────────────────────────

class TestFindPdfParts:
    def test_flat_pdf_attachment(self):
        payload = {
            "mimeType": "application/pdf",
            "filename": "invoice.pdf",
            "body": {"attachmentId": "abc123"},
        }
        parts = _find_pdf_parts(payload)
        assert len(parts) == 1 and parts[0]["filename"] == "invoice.pdf"

    def test_pdf_nested_in_multipart(self):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "text/plain", "filename": "", "body": {"data": "aGk="}},
                {"mimeType": "application/pdf", "filename": "receipt.pdf",
                 "body": {"attachmentId": "xyz"}},
            ],
        }
        parts = _find_pdf_parts(payload)
        assert len(parts) == 1 and parts[0]["filename"] == "receipt.pdf"

    def test_no_pdfs(self):
        payload = {"mimeType": "text/plain", "filename": "", "body": {"data": "aGk="}}
        assert _find_pdf_parts(payload) == []

    def test_multiple_pdfs(self):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "application/pdf", "filename": "a.pdf", "body": {"attachmentId": "1"}},
                {"mimeType": "application/pdf", "filename": "b.pdf", "body": {"attachmentId": "2"}},
            ],
        }
        assert len(_find_pdf_parts(payload)) == 2

    def test_detected_by_filename_extension(self):
        payload = {
            "mimeType": "application/octet-stream",
            "filename": "document.pdf",
            "body": {"attachmentId": "zzz"},
        }
        assert len(_find_pdf_parts(payload)) == 1

    def test_pdf_without_body_data_excluded(self):
        # Part has pdf mime type but no attachmentId or inline data — not downloadable
        payload = {"mimeType": "application/pdf", "filename": "empty.pdf", "body": {}}
        assert _find_pdf_parts(payload) == []

    def test_inline_pdf_data_included(self):
        payload = {
            "mimeType": "application/pdf",
            "filename": "inline.pdf",
            "body": {"data": PDF_B64},
        }
        assert len(_find_pdf_parts(payload)) == 1


# ── pl_load_fetcher_config ──────────────────────────────────────────────────────

class TestLoadFetcherConfig:
    def test_missing_fetcher_section_exits(self):
        with pytest.raises(SystemExit):
            pl_load_fetcher_config({})

    def test_valid_gmail_config_returns_fetcher_section(self):
        config = {"fetcher": {"gmail_sources": [{"label": "office"}]}}
        result = pl_load_fetcher_config(config)
        assert result["gmail_sources"][0]["label"] == "office"

    def test_valid_filesystem_only_config_returns_fetcher_section(self):
        config = {"fetcher": {"filesystem_sources": [{"label": "outgoing", "path": "/tmp"}]}}
        result = pl_load_fetcher_config(config)
        assert result["filesystem_sources"][0]["label"] == "outgoing"

    def test_empty_fetcher_section_returns_dict(self):
        result = pl_load_fetcher_config({"fetcher": {}})
        assert result == {}


# ── _process_gmail_source ─────────────────────────────────────────────────────

def _make_source(tmp_path: Path, **overrides) -> dict:
    base = {
        "label": "test",
        "username": "test@example.com",
        "client_secret_file": str(tmp_path / "secret.json"),
        "token_file": str(tmp_path / "token.json"),
        "folders": ["INBOX"],
    }
    base.update(overrides)
    return base


def _make_service(messages: list[dict], attachments: dict | None = None) -> MagicMock:
    """Build a minimal mock Gmail API service.

    messages: list of dicts with keys: id, from, subject, payload
    attachments: {attachmentId: {"data": base64_str}}
    """
    service = MagicMock()

    # messages.list — always returns the full list (no pagination in tests)
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": m["id"]} for m in messages],
    }

    messages_by_id = {m["id"]: m for m in messages}

    def get_side_effect(userId, id, format, metadataHeaders=None):
        msg = messages_by_id.get(id, {})
        result = MagicMock()
        if format == "metadata":
            result.execute.return_value = {
                "payload": {"headers": [
                    {"name": "From", "value": msg.get("from", "")},
                    {"name": "Subject", "value": msg.get("subject", "")},
                ]}
            }
        else:
            result.execute.return_value = {"payload": msg.get("payload", {})}
        return result

    service.users.return_value.messages.return_value.get.side_effect = get_side_effect

    if attachments:
        def att_side_effect(userId, messageId, id):
            result = MagicMock()
            result.execute.return_value = attachments.get(id, {})
            return result
        service.users.return_value.messages.return_value.attachments.return_value.get.side_effect = (
            att_side_effect
        )

    return service


class TestProcessGmailSource:
    def test_downloads_pdf_attachment(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        service = _make_service(
            messages=[{
                "id": "msg1", "from": "billing@supplier.com", "subject": "Rechnung",
                "payload": {
                    "mimeType": "application/pdf", "filename": "invoice.pdf",
                    "body": {"attachmentId": "att1"},
                },
            }],
            attachments={"att1": {"data": PDF_B64}},
        )

        with patch("fetcher._authenticate_gmail", return_value=service):
            saved, warnings = _process_gmail_source(
                _make_source(tmp_path), date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == ["invoice_fetched.pdf"]
        assert (invoices_dir / "invoice_fetched.pdf").read_bytes() == PDF_BYTES
        assert seen.contains("test/msg1/invoice.pdf")
        assert warnings == []

    def test_dry_run_does_not_write_files(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        service = _make_service(messages=[{
            "id": "msg1", "from": "b@s.com", "subject": "Invoice",
            "payload": {
                "mimeType": "application/pdf", "filename": "inv.pdf",
                "body": {"attachmentId": "att1"},
            },
        }])

        with patch("fetcher._authenticate_gmail", return_value=service):
            saved, _ = _process_gmail_source(
                _make_source(tmp_path), date(2026, 1, 1), invoices_dir, seen, dry_run=True
            )

        assert "inv.pdf" in saved
        assert not (invoices_dir / "inv.pdf").exists()
        assert not seen.contains("test/msg1/inv.pdf")

    def test_skips_already_seen(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")
        seen.add("test/msg1/invoice.pdf")

        service = _make_service(messages=[{
            "id": "msg1", "from": "b@s.com", "subject": "Invoice",
            "payload": {
                "mimeType": "application/pdf", "filename": "invoice.pdf",
                "body": {"attachmentId": "att1"},
            },
        }])

        with patch("fetcher._authenticate_gmail", return_value=service):
            saved, warnings = _process_gmail_source(
                _make_source(tmp_path), date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == []
        assert not (invoices_dir / "invoice.pdf").exists()

    def test_subject_filter_skips_non_matching(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        service = _make_service(messages=[{
            "id": "msg1", "from": "b@s.com", "subject": "Newsletter",
            "payload": {
                "mimeType": "application/pdf", "filename": "news.pdf",
                "body": {"attachmentId": "att1"},
            },
        }])

        source = _make_source(tmp_path, filters={"subject_keywords": ["Rechnung", "Invoice"]})
        with patch("fetcher._authenticate_gmail", return_value=service):
            saved, _ = _process_gmail_source(
                source, date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == []

    def test_filter_skips_shown_as_summary_count(self, tmp_path, capsys):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        service = _make_service(messages=[
            {"id": "m1", "from": "a@b.com", "subject": "Newsletter",
             "payload": {"mimeType": "text/plain", "filename": "", "body": {}}},
            {"id": "m2", "from": "a@b.com", "subject": "Promo",
             "payload": {"mimeType": "text/plain", "filename": "", "body": {}}},
        ])

        source = _make_source(tmp_path, filters={"subject_keywords": ["Rechnung"]})
        with patch("fetcher._authenticate_gmail", return_value=service):
            _process_gmail_source(source, date(2026, 1, 1), invoices_dir, seen, dry_run=False)

        out = capsys.readouterr().out
        assert "2 message(s) skipped by filter" in out
        assert "skipped (subject filter)" not in out

    def test_filename_collision_appends_counter(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        (invoices_dir / "invoice_fetched.pdf").write_bytes(b"existing")
        seen = SeenRegistry(tmp_path / "seen.json")

        service = _make_service(
            messages=[{
                "id": "msg1", "from": "b@s.com", "subject": "Invoice",
                "payload": {
                    "mimeType": "application/pdf", "filename": "invoice.pdf",
                    "body": {"attachmentId": "att1"},
                },
            }],
            attachments={"att1": {"data": PDF_B64}},
        )

        with patch("fetcher._authenticate_gmail", return_value=service):
            saved, _ = _process_gmail_source(
                _make_source(tmp_path), date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == ["invoice_fetched_2.pdf"]
        assert (invoices_dir / "invoice_fetched_2.pdf").read_bytes() == PDF_BYTES

    def test_auth_failure_returns_warning(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        with patch("fetcher._authenticate_gmail", side_effect=FileNotFoundError("no secret")):
            saved, warnings = _process_gmail_source(
                _make_source(tmp_path), date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == []
        assert any("authentication failed" in w for w in warnings)

    def test_search_failure_returns_warning(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        service = MagicMock()
        service.users.return_value.messages.return_value.list.return_value.execute.side_effect = (
            Exception("network error")
        )

        with patch("fetcher._authenticate_gmail", return_value=service):
            saved, warnings = _process_gmail_source(
                _make_source(tmp_path), date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == []
        assert any("failed to search" in w for w in warnings)


# ── _sha256_of_file ───────────────────────────────────────────────────────────

class TestSha256OfFile:
    def test_known_content(self, tmp_path):
        import hashlib
        f = tmp_path / "test.pdf"
        f.write_bytes(PDF_BYTES)
        assert _sha256_of_file(f) == hashlib.sha256(PDF_BYTES).hexdigest()

    def test_different_content_different_hash(self, tmp_path):
        a = tmp_path / "a.pdf"
        b = tmp_path / "b.pdf"
        a.write_bytes(b"content A")
        b.write_bytes(b"content B")
        assert _sha256_of_file(a) != _sha256_of_file(b)


# ── _process_filesystem_source ────────────────────────────────────────────────

def _make_fs_source(src_path: Path, label: str = "outgoing", **overrides) -> dict:
    base = {"label": label, "path": str(src_path)}
    base.update(overrides)
    return base


def _write_pdf(path: Path, content: bytes = PDF_BYTES) -> Path:
    path.write_bytes(content)
    return path


class TestProcessFilesystemSource:
    def test_copies_matching_pdf(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        _write_pdf(src / "invoice.pdf")
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        saved, warnings = _process_filesystem_source(
            _make_fs_source(src),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        assert saved == ["invoice_fetched.pdf"]
        assert (invoices_dir / "invoice_fetched.pdf").read_bytes() == PDF_BYTES
        assert warnings == []

    def test_canonical_key_is_content_hash(self, tmp_path):
        import hashlib
        src = tmp_path / "src"
        src.mkdir()
        _write_pdf(src / "invoice.pdf")
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        _process_filesystem_source(
            _make_fs_source(src),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        expected_key = f"local_fs/{hashlib.sha256(PDF_BYTES).hexdigest()}"
        assert seen.contains(expected_key)

    def test_skips_already_seen_by_content_hash(self, tmp_path):
        import hashlib
        src = tmp_path / "src"
        src.mkdir()
        _write_pdf(src / "invoice.pdf")
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")
        seen.add(f"local_fs/{hashlib.sha256(PDF_BYTES).hexdigest()}")

        saved, warnings = _process_filesystem_source(
            _make_fs_source(src),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        assert saved == []
        assert not (invoices_dir / "invoice.pdf").exists()

    def test_deduplicates_identical_content_across_names(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        _write_pdf(src / "invoice_a.pdf", b"same content")
        _write_pdf(src / "invoice_b.pdf", b"same content")
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        saved, warnings = _process_filesystem_source(
            _make_fs_source(src),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        assert len(saved) == 1

    def test_dry_run_does_not_write_or_register(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        _write_pdf(src / "invoice.pdf")
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        saved, _ = _process_filesystem_source(
            _make_fs_source(src),
            date(2026, 1, 1), invoices_dir, seen, dry_run=True,
        )

        assert "invoice.pdf" in saved
        assert not (invoices_dir / "invoice.pdf").exists()
        assert len(seen._keys) == 0

    def test_nonexistent_path_returns_warning(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        saved, warnings = _process_filesystem_source(
            _make_fs_source(tmp_path / "does_not_exist"),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        assert saved == []
        assert any("does not exist" in w for w in warnings)

    def test_filename_collision_appends_counter(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        _write_pdf(src / "invoice.pdf")
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        (invoices_dir / "invoice_fetched.pdf").write_bytes(b"existing")
        seen = SeenRegistry(tmp_path / "seen.json")

        saved, _ = _process_filesystem_source(
            _make_fs_source(src),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        assert saved == ["invoice_fetched_2.pdf"]
        assert (invoices_dir / "invoice_fetched_2.pdf").read_bytes() == PDF_BYTES

    def test_filters_by_filename_pattern(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        _write_pdf(src / "invoice.pdf")
        (src / "notes.txt").write_bytes(b"text")
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        saved, _ = _process_filesystem_source(
            _make_fs_source(src),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        assert saved == ["invoice_fetched.pdf"]

    def test_recursive_walks_subdirectories(self, tmp_path):
        src = tmp_path / "src"
        sub = src / "2026"
        sub.mkdir(parents=True)
        _write_pdf(sub / "deep_invoice.pdf")
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        saved, _ = _process_filesystem_source(
            _make_fs_source(src, recursive=True),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        assert saved == ["deep_invoice_fetched.pdf"]

    def test_non_recursive_ignores_subdirectories(self, tmp_path):
        src = tmp_path / "src"
        sub = src / "2026"
        sub.mkdir(parents=True)
        _write_pdf(sub / "deep_invoice.pdf")
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        saved, _ = _process_filesystem_source(
            _make_fs_source(src),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        assert saved == []

    def test_mtime_excludes_old_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        old_file = src / "old_invoice.pdf"
        _write_pdf(old_file)
        # set mtime to well before since date
        past_ts = date(2025, 1, 1).timetuple()
        import calendar
        past_epoch = calendar.timegm(past_ts)
        import os
        os.utime(old_file, (past_epoch, past_epoch))

        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        saved, _ = _process_filesystem_source(
            _make_fs_source(src),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        assert saved == []

    def test_mtime_includes_recent_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        new_file = src / "new_invoice.pdf"
        _write_pdf(new_file)
        # mtime defaults to now, which is after any reasonable since date

        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        saved, _ = _process_filesystem_source(
            _make_fs_source(src),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        assert saved == ["new_invoice_fetched.pdf"]

    def test_custom_filename_patterns(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        _write_pdf(src / "Rechnung_001.pdf")
        _write_pdf(src / "other.pdf", b"other content")
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        saved, _ = _process_filesystem_source(
            _make_fs_source(src, filename_patterns=["Rechnung_*.pdf"]),
            date(2026, 1, 1), invoices_dir, seen, dry_run=False,
        )

        assert saved == ["Rechnung_001_fetched.pdf"]


# ── anchor-date since calculation ────────────────────────────────────────────

class TestAnchorDateSince:
    """Verify that since_days is counted from anchor_date, not from today."""

    def _set_mtime(self, path: Path, d: date) -> None:
        import calendar, os
        ts = calendar.timegm(d.timetuple())
        os.utime(path, (ts, ts))

    def test_anchor_date_extends_lookback(self, tmp_path):
        # File is 50 days old — excluded by today-21 but included by anchor-21
        # when anchor is 40 days ago (anchor-21 = 61 days ago < file age 50 days).
        from datetime import date, timedelta
        src = tmp_path / "src"
        src.mkdir()
        old_file = src / "old_invoice.pdf"
        _write_pdf(old_file)
        self._set_mtime(old_file, date.today() - timedelta(days=50))

        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        since_with_today = date.today() - timedelta(days=21)
        saved_no_anchor, _ = _process_filesystem_source(
            _make_fs_source(src), since_with_today, invoices_dir, seen, dry_run=False,
        )
        assert saved_no_anchor == [], "file should be excluded when anchored to today"

        anchor = date.today() - timedelta(days=40)
        since_with_anchor = anchor - timedelta(days=21)
        saved_with_anchor, _ = _process_filesystem_source(
            _make_fs_source(src), since_with_anchor, invoices_dir, seen, dry_run=False,
        )
        assert saved_with_anchor == ["old_invoice_fetched.pdf"], "file should be included when anchored to last payment date"

    def test_anchor_date_parsed_from_iso_string(self):
        from fetcher import build_parser
        args = build_parser().parse_args(["--anchor-date", "2026-03-01"])
        assert args.anchor_date == date(2026, 3, 1)

    def test_anchor_date_defaults_to_none(self):
        from fetcher import build_parser
        args = build_parser().parse_args([])
        assert args.anchor_date is None


# ── _imap_date ────────────────────────────────────────────────────────────────

class TestImapDate:
    def test_january_first(self):
        assert _imap_date(date(2026, 1, 1)) == "01-Jan-2026"

    def test_december_thirty_first(self):
        assert _imap_date(date(2025, 12, 31)) == "31-Dec-2025"

    def test_mid_year_date(self):
        assert _imap_date(date(2026, 6, 15)) == "15-Jun-2026"

    def test_single_digit_day_zero_padded(self):
        assert _imap_date(date(2026, 3, 5)) == "05-Mar-2026"


# ── _imap_pdf_attachments ─────────────────────────────────────────────────────

def _make_raw_imap_email(
    subject: str = "Test",
    from_addr: str = "sender@example.com",
    message_id: str = "<test@example.com>",
    attachments: list[tuple[str, bytes]] | None = None,
) -> bytes:
    msg = email.mime.multipart.MIMEMultipart()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg.attach(email.mime.text.MIMEText("Body text"))
    for filename, data in (attachments or []):
        part = email.mime.base.MIMEBase("application", "pdf")
        part.set_payload(data)
        email.encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
    return msg.as_bytes()


class TestImapPdfAttachments:
    def test_single_pdf_attachment(self):
        raw = _make_raw_imap_email(attachments=[("invoice.pdf", PDF_BYTES)])
        results = _imap_pdf_attachments(raw)
        assert len(results) == 1
        assert results[0][0] == "invoice.pdf"
        assert results[0][1] == PDF_BYTES

    def test_no_attachments_returns_empty(self):
        raw = _make_raw_imap_email()
        assert _imap_pdf_attachments(raw) == []

    def test_multiple_pdf_attachments(self):
        raw = _make_raw_imap_email(attachments=[
            ("invoice.pdf", PDF_BYTES),
            ("receipt.pdf", b"%PDF-receipt"),
        ])
        results = _imap_pdf_attachments(raw)
        assert len(results) == 2
        names = {r[0] for r in results}
        assert names == {"invoice.pdf", "receipt.pdf"}

    def test_non_pdf_attachment_ignored(self):
        msg = email.mime.multipart.MIMEMultipart()
        msg["From"] = "a@b.com"
        part = email.mime.base.MIMEBase("application", "zip")
        part.set_payload(b"zipdata")
        email.encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="archive.zip")
        msg.attach(part)
        assert _imap_pdf_attachments(msg.as_bytes()) == []


# ── _authenticate_imap ────────────────────────────────────────────────────────

def _make_imap_source(**overrides) -> dict:
    base = {
        "label": "mail",
        "host": "mail.example.com",
        "port": 993,
        "username": "user@example.com",
    }
    base.update(overrides)
    return base


class TestAuthenticateImap:
    def test_uses_keyring_password(self):
        with (
            patch("fetcher.keyring.get_password", return_value="secret") as mock_get,
            patch("fetcher.keyring.set_password") as mock_set,
            patch("fetcher.imaplib.IMAP4_SSL") as mock_ssl,
        ):
            mock_conn = MagicMock()
            mock_ssl.return_value = mock_conn
            result = _authenticate_imap(_make_imap_source())

        mock_get.assert_called_once_with("fibutool-fetcher", "mail:user@example.com")
        mock_conn.login.assert_called_once_with("user@example.com", "secret")
        mock_set.assert_called_once_with("fibutool-fetcher", "mail:user@example.com", "secret")
        assert result is mock_conn

    def test_prompts_when_no_keyring_password(self):
        with (
            patch("fetcher.keyring.get_password", return_value=None),
            patch("fetcher.keyring.set_password"),
            patch("fetcher.imaplib.IMAP4_SSL") as mock_ssl,
            patch("fetcher.getpass.getpass", return_value="typed") as mock_prompt,
        ):
            mock_ssl.return_value = MagicMock()
            _authenticate_imap(_make_imap_source())

        mock_prompt.assert_called_once()

    def test_retries_once_on_auth_failure(self):
        mock_conn = MagicMock()
        mock_conn.login.side_effect = [
            imaplib.IMAP4.error("auth failed"),
            None,
        ]
        with (
            patch("fetcher.keyring.get_password", return_value="bad"),
            patch("fetcher.keyring.set_password"),
            patch("fetcher.imaplib.IMAP4_SSL", return_value=mock_conn),
            patch("fetcher.getpass.getpass", return_value="good"),
        ):
            _authenticate_imap(_make_imap_source())

        assert mock_conn.login.call_count == 2

    def test_raises_after_two_failures(self):
        mock_conn = MagicMock()
        mock_conn.login.side_effect = imaplib.IMAP4.error("bad creds")
        with (
            patch("fetcher.keyring.get_password", return_value="bad"),
            patch("fetcher.keyring.set_password"),
            patch("fetcher.imaplib.IMAP4_SSL", return_value=mock_conn),
            patch("fetcher.getpass.getpass", return_value="still_bad"),
        ):
            with pytest.raises(RuntimeError, match="authentication failed after 2 attempts"):
                _authenticate_imap(_make_imap_source())

    def test_stores_password_only_after_success(self):
        mock_conn = MagicMock()
        mock_conn.login.side_effect = [imaplib.IMAP4.error("bad"), None]
        with (
            patch("fetcher.keyring.get_password", return_value="wrong"),
            patch("fetcher.keyring.set_password") as mock_set,
            patch("fetcher.imaplib.IMAP4_SSL", return_value=mock_conn),
            patch("fetcher.getpass.getpass", return_value="correct"),
        ):
            _authenticate_imap(_make_imap_source())

        mock_set.assert_called_once_with("fibutool-fetcher", "mail:user@example.com", "correct")


# ── _process_imap_source ──────────────────────────────────────────────────────

def _make_imap_conn(
    folder_status: str = "OK",
    search_uids: list[bytes] | None = None,
    header_responses: dict | None = None,
    full_responses: dict | None = None,
) -> MagicMock:
    """Build a mock IMAP connection.

    search_uids: list of UID bytes, e.g. [b"1", b"2"]
    header_responses: {uid_bytes: (from_str, subject_str, message_id_str)}
    full_responses: {uid_bytes: raw_email_bytes}
    """
    if search_uids is None:
        search_uids = []
    header_responses = header_responses or {}
    full_responses = full_responses or {}

    conn = MagicMock()
    conn.select.return_value = (folder_status, [b"1"])

    uid_data = b" ".join(search_uids) if search_uids else b""

    def uid_side_effect(command, *args):
        if command == "SEARCH":
            return ("OK", [uid_data])
        if command == "FETCH":
            uid_arg = args[0]
            fetch_spec = args[1] if len(args) > 1 else ""
            if "HEADER.FIELDS" in fetch_spec:
                resp = header_responses.get(uid_arg)
                if resp is None:
                    return ("NO", [None])
                from_val, subj_val, msgid_val = resp
                raw = f"From: {from_val}\r\nSubject: {subj_val}\r\nMessage-ID: {msgid_val}\r\n\r\n".encode()
                return ("OK", [(b"literal", raw)])
            else:
                raw = full_responses.get(uid_arg, b"")
                return ("OK", [(b"literal", raw)])
        return ("NO", [None])

    conn.uid.side_effect = uid_side_effect
    return conn


def _make_imap_source_cfg(**overrides) -> dict:
    base = {
        "label": "mail",
        "host": "mail.example.com",
        "port": 993,
        "username": "user@example.com",
        "folders": ["INBOX"],
    }
    base.update(overrides)
    return base


class TestProcessImapSource:
    def test_downloads_pdf_attachment(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")
        raw_email = _make_raw_imap_email(
            subject="Rechnung",
            from_addr="billing@supplier.com",
            message_id="<msg1@example.com>",
            attachments=[("invoice.pdf", PDF_BYTES)],
        )
        conn = _make_imap_conn(
            search_uids=[b"1"],
            header_responses={b"1": ("billing@supplier.com", "Rechnung", "<msg1@example.com>")},
            full_responses={b"1": raw_email},
        )

        with patch("fetcher._authenticate_imap", return_value=conn):
            saved, warnings = _process_imap_source(
                _make_imap_source_cfg(), date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == ["invoice_fetched.pdf"]
        assert (invoices_dir / "invoice_fetched.pdf").read_bytes() == PDF_BYTES
        assert seen.contains("mail/<msg1@example.com>/invoice.pdf")
        assert warnings == []

    def test_dry_run_does_not_write_files(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")
        raw_email = _make_raw_imap_email(
            message_id="<m1@x.com>",
            attachments=[("inv.pdf", PDF_BYTES)],
        )
        conn = _make_imap_conn(
            search_uids=[b"1"],
            header_responses={b"1": ("a@b.com", "Invoice", "<m1@x.com>")},
            full_responses={b"1": raw_email},
        )

        with patch("fetcher._authenticate_imap", return_value=conn):
            saved, _ = _process_imap_source(
                _make_imap_source_cfg(), date(2026, 1, 1), invoices_dir, seen, dry_run=True
            )

        assert "inv.pdf" in saved
        assert not (invoices_dir / "inv.pdf").exists()
        assert len(seen._keys) == 0

    def test_skips_already_seen(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")
        seen.add("mail/<m1@x.com>/invoice.pdf")

        raw_email = _make_raw_imap_email(
            message_id="<m1@x.com>",
            attachments=[("invoice.pdf", PDF_BYTES)],
        )
        conn = _make_imap_conn(
            search_uids=[b"1"],
            header_responses={b"1": ("a@b.com", "Rechnung", "<m1@x.com>")},
            full_responses={b"1": raw_email},
        )

        with patch("fetcher._authenticate_imap", return_value=conn):
            saved, _ = _process_imap_source(
                _make_imap_source_cfg(), date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == []
        assert not (invoices_dir / "invoice.pdf").exists()

    def test_subject_filter_skips_non_matching(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")
        conn = _make_imap_conn(
            search_uids=[b"1"],
            header_responses={b"1": ("a@b.com", "Newsletter", "<m1@x.com>")},
        )

        source = _make_imap_source_cfg(filters={"subject_keywords": ["Rechnung", "Invoice"]})
        with patch("fetcher._authenticate_imap", return_value=conn):
            saved, _ = _process_imap_source(
                source, date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == []

    def test_filter_skips_shown_as_summary_count(self, tmp_path, capsys):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")
        conn = _make_imap_conn(
            search_uids=[b"1", b"2"],
            header_responses={
                b"1": ("a@b.com", "Newsletter", "<m1@x.com>"),
                b"2": ("a@b.com", "Promo", "<m2@x.com>"),
            },
        )

        source = _make_imap_source_cfg(filters={"subject_keywords": ["Rechnung"]})
        with patch("fetcher._authenticate_imap", return_value=conn):
            _process_imap_source(source, date(2026, 1, 1), invoices_dir, seen, dry_run=False)

        out = capsys.readouterr().out
        assert "2 message(s) skipped by filter" in out
        assert "skipped (subject filter)" not in out

    def test_auth_failure_returns_warning(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        with patch("fetcher._authenticate_imap", side_effect=RuntimeError("bad creds")):
            saved, warnings = _process_imap_source(
                _make_imap_source_cfg(), date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == []
        assert any("authentication failed" in w for w in warnings)

    def test_search_failure_returns_warning(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        conn = MagicMock()
        conn.select.return_value = ("OK", [b"1"])
        conn.uid.side_effect = imaplib.IMAP4.error("search failed")

        with patch("fetcher._authenticate_imap", return_value=conn):
            saved, warnings = _process_imap_source(
                _make_imap_source_cfg(), date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == []
        assert any("SEARCH error" in w for w in warnings)

    def test_no_messages_returns_empty(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        conn = _make_imap_conn(search_uids=[])
        with patch("fetcher._authenticate_imap", return_value=conn):
            saved, warnings = _process_imap_source(
                _make_imap_source_cfg(), date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        assert saved == []
        assert warnings == []

    def test_logout_called_after_run(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        conn = _make_imap_conn(search_uids=[])
        with patch("fetcher._authenticate_imap", return_value=conn):
            _process_imap_source(
                _make_imap_source_cfg(), date(2026, 1, 1), invoices_dir, seen, dry_run=False
            )

        conn.logout.assert_called_once()

    def test_logout_called_even_on_error(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        conn = MagicMock()
        conn.select.side_effect = Exception("unexpected")
        with patch("fetcher._authenticate_imap", return_value=conn):
            with pytest.raises(Exception):
                _process_imap_source(
                    _make_imap_source_cfg(), date(2026, 1, 1), invoices_dir, seen, dry_run=False
                )

        conn.logout.assert_called_once()

    def test_since_date_passed_to_search(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        seen = SeenRegistry(tmp_path / "seen.json")

        conn = _make_imap_conn(search_uids=[])
        with patch("fetcher._authenticate_imap", return_value=conn):
            _process_imap_source(
                _make_imap_source_cfg(), date(2026, 3, 15), invoices_dir, seen, dry_run=False
            )

        uid_calls = conn.uid.call_args_list
        search_call = next(c for c in uid_calls if c.args[0] == "SEARCH")
        assert "SINCE 15-Mar-2026" in search_call.args

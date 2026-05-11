import base64
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fetcher import (
    SeenRegistry,
    _find_pdf_parts,
    _matches_filters,
    _process_gmail_source,
    _safe_filename,
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

class TestSafeFilename:
    def test_no_collision(self, tmp_path):
        assert _safe_filename(tmp_path, "invoice.pdf") == tmp_path / "invoice.pdf"

    def test_one_collision(self, tmp_path):
        (tmp_path / "invoice.pdf").write_bytes(b"x")
        assert _safe_filename(tmp_path, "invoice.pdf") == tmp_path / "invoice_2.pdf"

    def test_multiple_collisions(self, tmp_path):
        (tmp_path / "invoice.pdf").write_bytes(b"x")
        (tmp_path / "invoice_2.pdf").write_bytes(b"x")
        assert _safe_filename(tmp_path, "invoice.pdf") == tmp_path / "invoice_3.pdf"

    def test_preserves_suffix(self, tmp_path):
        (tmp_path / "doc.PDF").write_bytes(b"x")
        result = _safe_filename(tmp_path, "other.PDF")
        assert result.suffix == ".PDF"


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

    def test_empty_gmail_sources_exits(self):
        with pytest.raises(SystemExit):
            pl_load_fetcher_config({"fetcher": {"gmail_sources": []}})

    def test_missing_gmail_sources_exits(self):
        with pytest.raises(SystemExit):
            pl_load_fetcher_config({"fetcher": {}})

    def test_valid_config_returns_fetcher_section(self):
        config = {"fetcher": {"gmail_sources": [{"label": "office"}]}}
        result = pl_load_fetcher_config(config)
        assert result["gmail_sources"][0]["label"] == "office"


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

        assert saved == ["invoice.pdf"]
        assert (invoices_dir / "invoice.pdf").read_bytes() == PDF_BYTES
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

    def test_filename_collision_appends_counter(self, tmp_path):
        invoices_dir = tmp_path / "invoices"
        invoices_dir.mkdir()
        (invoices_dir / "invoice.pdf").write_bytes(b"existing")
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

        assert saved == ["invoice_2.pdf"]
        assert (invoices_dir / "invoice_2.pdf").read_bytes() == PDF_BYTES

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

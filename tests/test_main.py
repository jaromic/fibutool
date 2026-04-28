import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import _preflight


def _make_dirs(tmp_path):
    merged = tmp_path / "merged"
    ordered = tmp_path / "payments-ordered"
    merged.mkdir()
    ordered.mkdir()
    csv = tmp_path / "journal.csv"
    return merged, ordered, csv


class TestPreflightMissingDirs:
    def test_missing_merged(self, tmp_path):
        merged = tmp_path / "merged"
        ordered = tmp_path / "payments-ordered"
        ordered.mkdir()
        csv = tmp_path / "journal.csv"
        with pytest.raises(SystemExit):
            _preflight(merged, ordered, csv, clean=False)

    def test_missing_ordered(self, tmp_path):
        merged = tmp_path / "merged"
        ordered = tmp_path / "payments-ordered"
        merged.mkdir()
        csv = tmp_path / "journal.csv"
        with pytest.raises(SystemExit):
            _preflight(merged, ordered, csv, clean=False)

    def test_missing_journal_parent(self, tmp_path):
        merged, ordered, _ = _make_dirs(tmp_path)
        csv = tmp_path / "nonexistent" / "journal.csv"
        with pytest.raises(SystemExit):
            _preflight(merged, ordered, csv, clean=False)


class TestPreflightConflicts:
    def test_nonempty_merged_blocks(self, tmp_path):
        merged, ordered, csv = _make_dirs(tmp_path)
        (merged / "file.pdf").write_bytes(b"x")
        with pytest.raises(SystemExit):
            _preflight(merged, ordered, csv, clean=False)

    def test_nonempty_ordered_blocks(self, tmp_path):
        merged, ordered, csv = _make_dirs(tmp_path)
        (ordered / "file.pdf").write_bytes(b"x")
        with pytest.raises(SystemExit):
            _preflight(merged, ordered, csv, clean=False)

    def test_existing_journal_blocks(self, tmp_path):
        merged, ordered, csv = _make_dirs(tmp_path)
        csv.write_text("data")
        with pytest.raises(SystemExit):
            _preflight(merged, ordered, csv, clean=False)

    def test_all_empty_passes(self, tmp_path):
        merged, ordered, csv = _make_dirs(tmp_path)
        _preflight(merged, ordered, csv, clean=False)  # must not raise


class TestPreflightClean:
    def test_clean_removes_files_from_dirs(self, tmp_path):
        merged, ordered, csv = _make_dirs(tmp_path)
        (merged / "a.pdf").write_bytes(b"x")
        (ordered / "b.pdf").write_bytes(b"x")
        _preflight(merged, ordered, csv, clean=True)
        assert list(merged.iterdir()) == []
        assert list(ordered.iterdir()) == []

    def test_clean_removes_journal(self, tmp_path):
        merged, ordered, csv = _make_dirs(tmp_path)
        csv.write_text("data")
        _preflight(merged, ordered, csv, clean=True)
        assert not csv.exists()

    def test_clean_keeps_dirs(self, tmp_path):
        merged, ordered, csv = _make_dirs(tmp_path)
        (merged / "a.pdf").write_bytes(b"x")
        _preflight(merged, ordered, csv, clean=True)
        assert merged.exists()
        assert ordered.exists()

    def test_clean_without_journal_passes(self, tmp_path):
        merged, ordered, csv = _make_dirs(tmp_path)
        _preflight(merged, ordered, csv, clean=True)  # csv doesn't exist, must not raise

    def test_clean_missing_dir_still_errors(self, tmp_path):
        merged = tmp_path / "merged"
        ordered = tmp_path / "payments-ordered"
        ordered.mkdir()
        csv = tmp_path / "journal.csv"
        with pytest.raises(SystemExit):
            _preflight(merged, ordered, csv, clean=True)

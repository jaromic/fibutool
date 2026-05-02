import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from splitter import _strip_prefix


class TestStripPrefix:
    def test_numeric_prefix(self):
        assert _strip_prefix("001_2024-01-15_receipt") == "receipt"

    def test_year_receipt_prefix(self):
        assert _strip_prefix("2025-130_2025-03-21_receipt") == "receipt"

    def test_original_name_with_underscores(self):
        assert _strip_prefix("001_2024-01-15_my_bank_receipt") == "my_bank_receipt"

    def test_no_prefix(self):
        assert _strip_prefix("receipt") == "receipt"

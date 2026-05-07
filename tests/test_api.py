import httpx
import pytest
from unittest.mock import MagicMock, patch

import anthropic

from api import call_with_retry


def _rate_limit_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    return anthropic.RateLimitError("rate limit", response=response, body=None)


class TestCallWithRetry:
    def test_success_on_first_attempt(self):
        fn = MagicMock(return_value="ok")
        assert call_with_retry(fn, delays=()) == "ok"
        assert fn.call_count == 1

    def test_success_after_one_retry(self):
        fn = MagicMock(side_effect=[_rate_limit_error(), "ok"])
        with patch("api.time.sleep"):
            result = call_with_retry(fn, delays=(0,))
        assert result == "ok"
        assert fn.call_count == 2

    def test_success_after_multiple_retries(self):
        fn = MagicMock(side_effect=[_rate_limit_error(), _rate_limit_error(), "ok"])
        with patch("api.time.sleep"):
            result = call_with_retry(fn, delays=(0, 0))
        assert result == "ok"
        assert fn.call_count == 3

    def test_reraises_after_all_delays_exhausted(self):
        # 2 delays → 3 attempts total; need 3 errors in the list
        fn = MagicMock(side_effect=[_rate_limit_error(), _rate_limit_error(), _rate_limit_error()])
        with patch("api.time.sleep"):
            with pytest.raises(anthropic.RateLimitError):
                call_with_retry(fn, delays=(0, 0))
        assert fn.call_count == 3

    def test_non_rate_limit_error_propagates_immediately(self):
        fn = MagicMock(side_effect=ValueError("bad input"))
        with patch("api.time.sleep"):
            with pytest.raises(ValueError):
                call_with_retry(fn, delays=(0, 0, 0))
        assert fn.call_count == 1

    def test_sleep_called_with_correct_delays(self):
        fn = MagicMock(side_effect=[_rate_limit_error(), _rate_limit_error(), "ok"])
        with patch("api.time.sleep") as mock_sleep:
            call_with_retry(fn, delays=(30, 90))
        assert mock_sleep.call_args_list[0][0][0] == 30
        assert mock_sleep.call_args_list[1][0][0] == 90

import time

import anthropic

_RETRY_DELAYS = (60, 180, 300, 600)


def call_with_retry(fn, delays=_RETRY_DELAYS):
    """Call fn(); on RateLimitError wait and retry for each delay, then make one final attempt."""
    for attempt, delay in enumerate(delays, start=1):
        try:
            return fn()
        except anthropic.RateLimitError:
            print(f"  ⏳ rate limit — retrying in {delay}s (attempt {attempt}/{len(delays)})...")
            time.sleep(delay)
    return fn()

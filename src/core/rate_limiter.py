import time
from collections import defaultdict
from typing import Optional

class RateLimiter:
    def __init__(self, max_requests: int = 5, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list] = defaultdict(list)

    def check(self, key: str) -> tuple[bool, Optional[int]]:
        now = time.time()
        timestamps = self._requests[key]
        timestamps[:] = [t for t in timestamps if now - t < self.window_seconds]
        if len(timestamps) >= self.max_requests:
            retry_after = int(self.window_seconds - (now - timestamps[0]))
            return False, retry_after
        timestamps.append(now)
        return True, None

    def reset(self, key: str = None):
        if key:
            self._requests.pop(key, None)
        else:
            self._requests.clear()


_report_limiter = RateLimiter(max_requests=5, window_seconds=3600)

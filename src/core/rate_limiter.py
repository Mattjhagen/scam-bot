import logging
import time
from collections import defaultdict
from typing import Optional

logger = logging.getLogger("scambot")

try:
    import redis as redis_lib

    _HAS_REDIS = True
except ImportError:  # pragma: no cover
    redis_lib = None  # type: ignore[assignment]
    _HAS_REDIS = False


class RateLimiter:
    def __init__(self, max_requests: int = 5, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list] = defaultdict(list)
        self._redis = None
        if _HAS_REDIS:
            try:
                from ..config import settings

                self._redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
                self._redis.ping()
            except Exception as exc:  # fall back to in-memory limiter
                logger.warning("Redis rate limiter unavailable, using in-memory: %s", exc)
                self._redis = None

    def _redis_key(self, key: str) -> str:
        return f"scambot:rate_limit:{key}"

    def check(self, key: str) -> tuple[bool, Optional[int]]:
        if self._redis is not None:
            return self._check_redis(key)
        return self._check_local(key)

    def _check_redis(self, key: str) -> tuple[bool, Optional[int]]:
        now = time.time()
        redis_key = self._redis_key(key)
        pipeline = self._redis.pipeline()
        pipeline.zremrangebyscore(redis_key, 0, now - self.window_seconds)
        pipeline.zcard(redis_key)
        pipeline.expire(redis_key, self.window_seconds)
        results = pipeline.execute()
        current_count = results[1]
        if current_count >= self.max_requests:
            earliest = self._redis.zrange(redis_key, 0, 0, withscores=True)
            if earliest:
                retry_after = int(self.window_seconds - (now - float(earliest[0][1])))
                return False, max(retry_after, 1)
            return False, self.window_seconds
        pipeline.zadd(redis_key, {str(now): now})
        pipeline.execute()
        return True, None

    def _check_local(self, key: str) -> tuple[bool, Optional[int]]:
        now = time.time()
        timestamps = self._requests[key]
        timestamps[:] = [t for t in timestamps if now - t < self.window_seconds]
        if len(timestamps) >= self.max_requests:
            retry_after = int(self.window_seconds - (now - timestamps[0]))
            return False, retry_after
        timestamps.append(now)
        return True, None

    def reset(self, key: str = None):
        if self._redis is not None:
            if key:
                self._redis.delete(self._redis_key(key))
            else:
                for k in self._redis.keys("scambot:rate_limit:*"):
                    self._redis.delete(k)
            return
        if key:
            self._requests.pop(key, None)
        else:
            self._requests.clear()


_report_limiter = RateLimiter(max_requests=5, window_seconds=3600)

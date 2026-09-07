from collections import defaultdict, deque
from time import time

from redis import Redis
from redis.exceptions import RedisError

from app.config import settings


RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_ATTEMPTS = 5

_attempts: dict[str, deque[float]] = defaultdict(deque)
_redis_client: Redis | None = None


def get_redis_client() -> Redis | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.redis_url:
        return None
    try:
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        return _redis_client
    except RedisError:
        return None


def reset_rate_limit_state() -> None:
    _attempts.clear()
    global _redis_client
    _redis_client = None


def is_rate_limited(key: str) -> bool:
    redis_client = get_redis_client()
    if redis_client is not None:
        try:
            current = redis_client.incr(key)
            if current == 1:
                redis_client.expire(key, RATE_LIMIT_WINDOW_SECONDS)
            return current > RATE_LIMIT_MAX_ATTEMPTS
        except RedisError:
            pass

    now = time()
    bucket = _attempts[key]

    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT_MAX_ATTEMPTS:
        return True

    bucket.append(now)
    return False

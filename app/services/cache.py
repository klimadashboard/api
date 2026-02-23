import json
import logging
from typing import Any

import redis.asyncio as redis

logger = logging.getLogger(__name__)

_redis: redis.Redis | None = None


async def init_redis(url: str) -> None:
    global _redis
    _redis = redis.from_url(url, decode_responses=True)
    try:
        await _redis.ping()
        logger.info("Redis connected")
    except Exception:
        logger.warning("Redis unavailable — running without cache")
        _redis = None


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


async def get_cached(key: str) -> Any | None:
    if not _redis:
        return None
    try:
        raw = await _redis.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        logger.warning("Cache read failed for %s", key)
    return None


async def set_cached(key: str, value: Any, ttl: int) -> None:
    if not _redis:
        return
    try:
        await _redis.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception:
        logger.warning("Cache write failed for %s", key)

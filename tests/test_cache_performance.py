"""
Cache performance test for the Klimadashboard API.

Measures response time for cold (uncached) vs warm (cached) requests
and reports the speedup from Redis caching.

Usage:
    python -m tests.test_cache_performance [--url URL] [--dataset ID] [--n N]

Requires Redis to be running for meaningful results.
"""

import argparse
import statistics
import time

import httpx
import redis

DEFAULT_URL = "http://localhost:8000"
DEFAULT_DATASET = "emissions_data"
DEFAULT_N = 20
DEFAULT_REDIS_URL = "redis://localhost:6379"


def flush_cache_keys(redis_url: str, pattern: str = "data:*") -> int:
    """Delete all cached data keys from Redis. Returns count deleted."""
    r = redis.from_url(redis_url, decode_responses=True)
    try:
        r.ping()
    except redis.ConnectionError:
        print("  Redis not reachable — cache flush skipped")
        return 0
    keys = r.keys(pattern)
    if keys:
        r.delete(*keys)
    r.close()
    return len(keys)


def run_test(
    base_url: str,
    dataset_id: str,
    n: int,
    redis_url: str,
) -> dict:
    endpoint = f"{base_url}/v0/data/{dataset_id}/records?limit=100"

    print(f"\n{'='*50}")
    print(f"Cache Performance Test")
    print(f"{'='*50}")
    print(f"Endpoint: {endpoint}")
    print(f"Warm iterations: {n}")

    # 1. Flush cache
    print(f"\n--- Flushing Redis cache ---")
    deleted = flush_cache_keys(redis_url)
    print(f"  Deleted {deleted} cached keys")

    # 2. Cold request (no cache)
    print(f"\n--- Cold request (uncached) ---")
    start = time.perf_counter()
    resp = httpx.get(endpoint)
    cold_time = time.perf_counter() - start
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    record_count = len(data.get("data", []))
    print(f"  {cold_time*1000:.1f} ms  ({record_count} records)")

    # 3. Warm requests (cached)
    print(f"\n--- Warm requests (cached, {n} iterations) ---")
    warm_times = []
    for i in range(n):
        start = time.perf_counter()
        resp = httpx.get(endpoint)
        elapsed = time.perf_counter() - start
        warm_times.append(elapsed)
        assert resp.status_code == 200

    warm_avg = statistics.mean(warm_times)
    warm_p50 = statistics.median(warm_times)
    warm_sorted = sorted(warm_times)
    warm_p95 = warm_sorted[min(int(0.95 * len(warm_sorted)), len(warm_sorted) - 1)]
    warm_min = warm_sorted[0]
    warm_max = warm_sorted[-1]
    speedup = cold_time / warm_avg if warm_avg > 0 else float("inf")

    # 4. Report
    print(f"\n{'='*50}")
    print(f"Results")
    print(f"{'='*50}")
    print(f"Cold (uncached):  {cold_time*1000:>8.1f} ms")
    print(f"Warm average:     {warm_avg*1000:>8.1f} ms")
    print(f"Warm median (p50):{warm_p50*1000:>8.1f} ms")
    print(f"Warm p95:         {warm_p95*1000:>8.1f} ms")
    print(f"Warm min:         {warm_min*1000:>8.1f} ms")
    print(f"Warm max:         {warm_max*1000:>8.1f} ms")
    print(f"Speedup:          {speedup:>8.1f}x")
    print(f"{'='*50}")

    return {
        "cold_ms": cold_time * 1000,
        "warm_avg_ms": warm_avg * 1000,
        "warm_p50_ms": warm_p50 * 1000,
        "warm_p95_ms": warm_p95 * 1000,
        "speedup": speedup,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cache performance test")
    parser.add_argument("--url", default=DEFAULT_URL, help="API base URL")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Dataset ID to test")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="Number of warm iterations")
    parser.add_argument("--redis-url", default=DEFAULT_REDIS_URL, help="Redis URL")
    args = parser.parse_args()
    run_test(args.url, args.dataset, args.n, args.redis_url)

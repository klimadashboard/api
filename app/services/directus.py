import httpx
import logging

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_base_url: str = ""


def init_directus(base_url: str) -> None:
    global _client, _base_url
    _base_url = base_url.rstrip("/")
    _client = httpx.AsyncClient(base_url=_base_url, timeout=30.0)
    logger.info("Directus client configured for %s", _base_url)


async def close_directus() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


async def fetch_items(
    collection: str,
    limit: int = 100,
    offset: int = 0,
    sort: str | None = None,
    fields: str | None = None,
    filters: dict | None = None,
) -> dict:
    """Fetch items from a Directus collection. Returns {"data": [...], "meta": {...}}."""
    params: dict = {
        "limit": limit,
        "offset": offset,
        "meta": "total_count,filter_count",
    }
    if sort:
        params["sort"] = sort
    if fields:
        params["fields"] = fields
    if filters:
        for key, value in filters.items():
            params[key] = value

    resp = await _client.get(f"/items/{collection}", params=params)
    resp.raise_for_status()
    return resp.json()

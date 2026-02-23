import csv
import io
import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from app.datasets import DATASETS
from app.services import cache, directus

router = APIRouter()

MAX_LIMIT = 10000
DEFAULT_LIMIT = 100


def _build_cache_key(dataset_id: str, params: dict) -> str:
    raw = json.dumps({"dataset": dataset_id, **params}, sort_keys=True)
    return f"data:{hashlib.md5(raw.encode()).hexdigest()}"


def _parse_filters(query_params: dict) -> dict:
    """Extract Directus-style filter params from the query string.

    Accepts: filter[field][operator]=value
    Passes them through to Directus as-is.
    """
    filters = {}
    for key, value in query_params.items():
        if key.startswith("filter["):
            filters[key] = value
    return filters


def _to_csv(data: list[dict]) -> str:
    if not data:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
    return output.getvalue()


async def _fetch_records(
    request: Request,
    dataset_id: str,
    limit: int,
    offset: int,
    sort: str | None,
    fields: str | None,
) -> JSONResponse:
    """Shared implementation for fetching dataset records as JSON."""
    if dataset_id not in DATASETS:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")

    meta = DATASETS[dataset_id]
    filters = _parse_filters(dict(request.query_params))

    params = {
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "fields": fields,
        "filters": filters,
    }

    cache_key = _build_cache_key(dataset_id, params)
    cached = await cache.get_cached(cache_key)
    if cached:
        return JSONResponse(
            content=cached,
            headers={
                "X-License": meta["license"],
                "Cache-Control": f"public, max-age={meta['cache_ttl']}",
            },
        )

    result = await directus.fetch_items(
        collection=dataset_id,
        limit=limit,
        offset=offset,
        sort=sort,
        fields=fields,
        filters=filters,
    )

    response_body = {
        "dataset": dataset_id,
        "data": result.get("data", []),
        "meta": {
            "total": result.get("meta", {}).get("total_count"),
            "filtered": result.get("meta", {}).get("filter_count"),
            "limit": limit,
            "offset": offset,
        },
        "license": meta["license"],
    }

    await cache.set_cached(cache_key, response_body, meta["cache_ttl"])
    return JSONResponse(
        content=response_body,
        headers={
            "X-License": meta["license"],
            "Cache-Control": f"public, max-age={meta['cache_ttl']}",
        },
    )


async def _fetch_records_csv(
    request: Request,
    dataset_id: str,
    limit: int,
    offset: int,
    sort: str | None,
    fields: str | None,
) -> Response:
    """Shared implementation for fetching dataset records as CSV."""
    if dataset_id not in DATASETS:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")

    meta = DATASETS[dataset_id]
    filters = _parse_filters(dict(request.query_params))

    result = await directus.fetch_items(
        collection=dataset_id,
        limit=limit,
        offset=offset,
        sort=sort,
        fields=fields,
        filters=filters,
    )

    csv_content = _to_csv(result.get("data", []))
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{dataset_id}.csv"',
            "X-License": meta["license"],
        },
    )


# ---------------------------------------------------------------------------
# Generate explicit, documented routes per dataset
# ---------------------------------------------------------------------------

QUERY_DESC_LIMIT = "Number of records to return (default: 100, max: 10,000)."
QUERY_DESC_OFFSET = "Number of records to skip for pagination (default: 0)."
QUERY_DESC_SORT = (
    "Sort field. Prefix with `-` for descending order. "
    "Example: `sort=-year` for newest first."
)
QUERY_DESC_FIELDS = (
    "Comma-separated list of fields to include in the response. "
    "Example: `fields=year,value,category` to return only those columns."
)


def _make_json_handler(dataset_id: str):
    async def handler(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description=QUERY_DESC_LIMIT)] = DEFAULT_LIMIT,
        offset: Annotated[int, Query(ge=0, description=QUERY_DESC_OFFSET)] = 0,
        sort: Annotated[str | None, Query(description=QUERY_DESC_SORT)] = None,
        fields: Annotated[str | None, Query(description=QUERY_DESC_FIELDS)] = None,
    ):
        return await _fetch_records(request, dataset_id, limit, offset, sort, fields)
    return handler


def _make_csv_handler(dataset_id: str):
    async def handler(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description=QUERY_DESC_LIMIT)] = DEFAULT_LIMIT,
        offset: Annotated[int, Query(ge=0, description=QUERY_DESC_OFFSET)] = 0,
        sort: Annotated[str | None, Query(description=QUERY_DESC_SORT)] = None,
        fields: Annotated[str | None, Query(description=QUERY_DESC_FIELDS)] = None,
    ):
        return await _fetch_records_csv(request, dataset_id, limit, offset, sort, fields)
    return handler


for _dataset_id, _meta in DATASETS.items():
    _fields_doc = "\n".join(
        f"- **{fname}**: {fdesc}" for fname, fdesc in _meta["fields"].items()
    )
    _examples_doc = "\n".join(
        f"- `{ex}`" for ex in _meta.get("example_queries", [])
    )
    _description = (
        f"{_meta['description']}\n\n"
        f"**Source:** {_meta['source']}\n\n"
        f"**License:** {_meta['license']}\n\n"
        f"**Update frequency:** {_meta['update_frequency']}\n\n"
        f"### Fields\n{_fields_doc}\n\n"
        f"### Example queries\n{_examples_doc}\n\n"
        f"### Filtering\n"
        f"Use `filter[field][operator]=value` query parameters. "
        f"Supported operators: `_eq`, `_neq`, `_gt`, `_gte`, `_lt`, `_lte`, "
        f"`_in`, `_nin`, `_contains`, `_ncontains`, `_null`.\n\n"
        f"Example: `?filter[year][_gte]=2020&filter[category][_eq]=ksg_energy`"
    )

    _example_response = {
        "dataset": _dataset_id,
        "data": [_meta.get("example_record", {})],
        "meta": {"total": 1000, "filtered": 1000, "limit": 100, "offset": 0},
        "license": _meta["license"],
    }

    router.add_api_route(
        f"/data/{_dataset_id}/records",
        _make_json_handler(_dataset_id),
        methods=["GET"],
        summary=f"{_meta['title']}",
        description=_description,
        tags=[_meta["title"]],
        responses={
            200: {
                "description": "Paginated dataset records",
                "content": {
                    "application/json": {"example": _example_response},
                },
            },
            404: {"description": "Dataset not found"},
        },
    )

    router.add_api_route(
        f"/data/{_dataset_id}/records.csv",
        _make_csv_handler(_dataset_id),
        methods=["GET"],
        summary=f"{_meta['title']} (CSV)",
        description=f"Download {_meta['title']} data as a CSV file.",
        tags=[_meta["title"]],
        response_class=Response,
    )


# ---------------------------------------------------------------------------
# Generic fallback (not shown in docs) for forward-compatibility
# ---------------------------------------------------------------------------

@router.get("/data/{dataset_id}/records", include_in_schema=False)
async def get_records_generic(
    request: Request,
    dataset_id: str,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: str | None = None,
    fields: str | None = None,
):
    return await _fetch_records(request, dataset_id, limit, offset, sort, fields)


@router.get("/data/{dataset_id}/records.csv", include_in_schema=False, response_class=Response)
async def get_records_csv_generic(
    request: Request,
    dataset_id: str,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: str | None = None,
    fields: str | None = None,
):
    return await _fetch_records_csv(request, dataset_id, limit, offset, sort, fields)

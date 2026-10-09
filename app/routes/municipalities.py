import csv
import hashlib
import io
import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from app.services import cache, directus

router = APIRouter()

CLIMATE_INDICES_LICENSE = "CC-BY-4.0"
CLIMATE_INDICES_COVERAGE_YEARS = [1961, 2022]

CLIMATE_INDICES_META = {
    "source": "GeoSphere Austria SPARTACUS-v2 (1km gridded daily temperature)",
    "methodology": (
        "Population-weighted zonal statistic: the annual threshold-day count is "
        "computed per SPARTACUS grid cell first, then averaged across the cells "
        "intersecting the municipality, weighted by population (GHS-POP 2020, "
        "100m). Grid cells whose elevation deviates by more than 300m from the "
        "municipality's population-weighted mean elevation are excluded, to avoid "
        "population-grid registration artifacts in uninhabited high-alpine terrain."
    ),
    "population_grid": "GHS-POP 2020, 100m (JRC/Copernicus)",
    "elevation_filter_m": 300,
    "unit": "days/year",
    "coverage_years": CLIMATE_INDICES_COVERAGE_YEARS,
    "license": CLIMATE_INDICES_LICENSE,
}

REGION_FIELDS = "id,code,code_short,name,name_short,slug,country,layer"


async def _resolve_municipality(code: str) -> dict:
    result = await directus.fetch_items(
        collection="regions",
        limit=1,
        fields=REGION_FIELDS,
        filters={
            "filter[_or][0][code][_eq]": code,
            "filter[_or][1][code_short][_eq]": code,
            "filter[layer][_eq]": "municipality",
        },
    )
    data = result.get("data", [])
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"No municipality found for Gemeindeschlüssel '{code}'",
        )
    return data[0]


def _parse_categories(category: str | None) -> list[str] | None:
    if not category:
        return None
    return [c.strip() for c in category.split(",") if c.strip()]


async def _fetch_indices(
    region_id: str,
    categories: list[str] | None,
    year_from: int | None,
    year_to: int | None,
) -> list[dict]:
    filters: dict = {"filter[region][_eq]": region_id}
    if categories:
        filters["filter[category][_in]"] = ",".join(categories)
    if year_from is not None:
        filters["filter[year][_gte]"] = str(year_from)
    if year_to is not None:
        filters["filter[year][_lte]"] = str(year_to)

    result = await directus.fetch_items(
        collection="climate_indices",
        limit=-1,
        sort="year,category",
        fields="year,category,value,value_min,value_max",
        filters=filters,
    )
    return result.get("data", [])


def _build_cache_key(code: str, category: str | None, year_from: int | None, year_to: int | None) -> str:
    raw = json.dumps(
        {"endpoint": "municipality_climate_indices", "code": code, "category": category, "year_from": year_from, "year_to": year_to},
        sort_keys=True,
    )
    return f"data:{hashlib.md5(raw.encode()).hexdigest()}"


QUERY_DESC_CATEGORY = (
    "Comma-separated list of index categories to include, e.g. "
    "`heat_days,frost_days`. One of `heat_days`, `summer_days`, "
    "`tropical_nights`, `frost_days`. Default: all four."
)
QUERY_DESC_YEAR_FROM = "First year to include (default: earliest available, 1961)."
QUERY_DESC_YEAR_TO = "Last year to include (default: latest available)."

ENDPOINT_DESCRIPTION = (
    "Look up population-weighted climate indices for a single Austrian "
    "municipality by its Gemeindeschlüssel (matched against the `code` or "
    "`code_short` field of the `regions` dataset).\n\n"
    f"**Methodology:** {CLIMATE_INDICES_META['methodology']}\n\n"
    f"**Source:** {CLIMATE_INDICES_META['source']}\n\n"
    "For bulk access across many municipalities at once (e.g. one year for "
    "all of Austria), use `/v0/data/climate_indices/records` instead — this "
    "endpoint is a convenience wrapper around the same underlying data for "
    "the single-municipality lookup case."
)


EXAMPLE_RESPONSE = {
    "region": {
        "id": "b7e1c2a0-1234-4abc-9def-000000000001",
        "code": "70101",
        "code_short": "70101",
        "name": "Innsbruck",
        "name_short": None,
        "slug": "innsbruck",
        "country": "AT",
        "layer": "municipality",
    },
    "data": [
        {"year": 2021, "category": "heat_days", "value": 21, "value_min": 3, "value_max": 29},
        {"year": 2022, "category": "heat_days", "value": 30, "value_min": 5, "value_max": 38},
        {"year": 2022, "category": "summer_days", "value": 78, "value_min": 40, "value_max": 95},
        {"year": 2022, "category": "tropical_nights", "value": 9, "value_min": 0, "value_max": 14},
        {"year": 2022, "category": "frost_days", "value": 85, "value_min": 70, "value_max": 140},
    ],
    "meta": CLIMATE_INDICES_META,
}


@router.get(
    "/municipalities/{code}/climate-indices",
    summary="Climate indices for a municipality",
    description=ENDPOINT_DESCRIPTION,
    tags=["Municipalities"],
    responses={
        200: {
            "description": "Yearly index values for the municipality (example values are illustrative)",
            "content": {"application/json": {"example": EXAMPLE_RESPONSE}},
        },
        404: {
            "description": "No municipality found for the given code",
            "content": {
                "application/json": {
                    "example": {"detail": "No municipality found for Gemeindeschlüssel '99999'"}
                }
            },
        },
    },
)
async def get_municipality_climate_indices(
    request: Request,
    code: str,
    category: Annotated[str | None, Query(description=QUERY_DESC_CATEGORY)] = None,
    year_from: Annotated[int | None, Query(description=QUERY_DESC_YEAR_FROM)] = None,
    year_to: Annotated[int | None, Query(description=QUERY_DESC_YEAR_TO)] = None,
):
    region = await _resolve_municipality(code)
    categories = _parse_categories(category)

    cache_key = _build_cache_key(code, category, year_from, year_to)
    cached = await cache.get_cached(cache_key)
    if cached:
        return JSONResponse(
            content=cached,
            headers={"X-License": CLIMATE_INDICES_LICENSE, "Cache-Control": "public, max-age=86400"},
        )

    data = await _fetch_indices(region["id"], categories, year_from, year_to)
    response_body = {"region": region, "data": data, "meta": CLIMATE_INDICES_META}

    await cache.set_cached(cache_key, response_body, 86400)
    return JSONResponse(
        content=response_body,
        headers={"X-License": CLIMATE_INDICES_LICENSE, "Cache-Control": "public, max-age=86400"},
    )


@router.get(
    "/municipalities/{code}/climate-indices.csv",
    summary="Climate indices for a municipality (CSV)",
    tags=["Municipalities"],
    response_class=Response,
)
async def get_municipality_climate_indices_csv(
    request: Request,
    code: str,
    category: Annotated[str | None, Query(description=QUERY_DESC_CATEGORY)] = None,
    year_from: Annotated[int | None, Query(description=QUERY_DESC_YEAR_FROM)] = None,
    year_to: Annotated[int | None, Query(description=QUERY_DESC_YEAR_TO)] = None,
):
    region = await _resolve_municipality(code)
    categories = _parse_categories(category)
    data = await _fetch_indices(region["id"], categories, year_from, year_to)

    output = io.StringIO()
    if data:
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{code}_climate_indices.csv"',
            "X-License": CLIMATE_INDICES_LICENSE,
        },
    )

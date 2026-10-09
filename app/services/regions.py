"""Region lookup helpers shared by the per-region endpoints.

Regions are identified by their UUID, their `code` (AT: Gemeindekennziffer,
DE: 12-digit Regionalschlüssel) or their `code_short` (DE: 8-digit
Gemeindeschlüssel/AGS). District and state codes work the same way.
"""

import re

from fastapi import HTTPException

from app.services import cache, directus

REGION_FIELDS = "id,code,code_short,name,name_short,slug,country,layer,layer_label,population,area,parents"
SUPPORTED_COUNTRIES = ("AT", "DE")
SUPPORTED_LAYERS = ("municipality", "district", "state", "country")

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_CHILDREN_TTL = 86400


def public_region(region: dict) -> dict:
    """The subset of region fields echoed back in responses."""
    return {
        k: region.get(k)
        for k in ("id", "code", "code_short", "name", "country", "layer", "layer_label", "population", "area")
    }


def region_codes(region: dict) -> list[str]:
    """All codes a region may be stored under in data tables."""
    return [c for c in dict.fromkeys([region.get("code"), region.get("code_short")]) if c]


async def resolve_region(code: str, country: str | None = None) -> dict:
    """Look up a single AT/DE region by UUID, `code` or `code_short`."""
    filters: dict = {
        "filter[layer][_in]": ",".join(SUPPORTED_LAYERS),
        "filter[country][_in]": country.upper() if country else ",".join(SUPPORTED_COUNTRIES),
    }
    if _UUID_RE.match(code):
        filters["filter[id][_eq]"] = code
    else:
        filters["filter[_or][0][code][_eq]"] = code
        filters["filter[_or][1][code_short][_eq]"] = code

    result = await directus.fetch_items(collection="regions", limit=10, fields=REGION_FIELDS, filters=filters)
    matches = result.get("data", [])
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No region found for code '{code}'. Use a Gemeindeschlüssel/Gemeindekennziffer, "
                "district or state code, or region UUID (see /v0/data/regions/records)."
            ),
        )
    if len(matches) > 1:
        candidates = ", ".join(f"{m['name']} ({m['country']}, {m['layer']})" for m in matches)
        raise HTTPException(
            status_code=409,
            detail=f"Code '{code}' is ambiguous: {candidates}. Add `?country=AT` or `?country=DE`.",
        )
    return matches[0]


def require_country(region: dict, countries: tuple[str, ...], dataset_label: str) -> None:
    if region["country"] not in countries:
        raise HTTPException(
            status_code=404,
            detail=f"{dataset_label} is only available for: {', '.join(countries)}.",
        )


def require_layer(region: dict, layers: tuple[str, ...]) -> None:
    if region["layer"] not in layers:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This endpoint supports the layers {', '.join(layers)}; "
                f"'{region['name']}' is a {region['layer']}. For national figures use the bulk "
                "`/v0/data/...` endpoints."
            ),
        )


async def _country_municipalities(country: str) -> list[dict]:
    cache_key = f"data:municipalities:{country}"
    cached = await cache.get_cached(cache_key)
    if cached is not None:
        return cached
    result = await directus.fetch_items(
        collection="regions",
        limit=-1,
        fields="id,code,code_short,name,population,area,parents",
        filters={"filter[layer][_eq]": "municipality", "filter[country][_eq]": country},
    )
    data = result.get("data", [])
    await cache.set_cached(cache_key, data, _CHILDREN_TTL)
    return data


async def child_municipalities(region: dict) -> list[dict]:
    """Municipalities that list `region` as a parent.

    Municipalities named exactly like their parent are skipped: these are
    aggregate entries (e.g. Wien 90001 under the state of Vienna) and would
    double-count the actual districts.
    """
    parent_name = (region.get("name") or "").strip().lower()
    return [
        m
        for m in await _country_municipalities(region["country"])
        if any(p.get("id") == region["id"] for p in (m.get("parents") or []))
        and (m.get("name") or "").strip().lower() != parent_name
    ]


def parent_of_layer(region: dict, layer: str) -> str | None:
    """UUID of the region's parent on the given layer, if any."""
    for p in region.get("parents") or []:
        if p.get("layer") == layer:
            return p.get("id")
    return None

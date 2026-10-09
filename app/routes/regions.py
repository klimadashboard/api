"""Per-region endpoints: look up one municipality, district or state in
Germany or Austria and get a ready-to-use time series for one topic.

Every endpoint is also available as CSV by appending `.csv` to the path.
"""

import csv
import hashlib
import io
import json
from collections import defaultdict
from typing import Annotated, Awaitable, Callable, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from app.services import cache, directus
from app.services.regions import (
    child_municipalities,
    parent_of_layer,
    public_region,
    region_codes,
    require_country,
    require_layer,
    resolve_region,
)

router = APIRouter()

LICENSE = "CC-BY-4.0"
TAG = "Regions"

QUERY_DESC_COUNTRY = (
    "Only needed if a code exists in both countries: `AT` or `DE`."
)
QUERY_DESC_GROUP = "Time resolution: `year` (default) or `month`."

CODE_DOC = (
    "`code` is a region's Gemeindeschlüssel (DE, 8-digit AGS such as `08115003`, or the "
    "12-digit ARS), Gemeindekennziffer (AT, e.g. `70101`), a district or state code "
    "(e.g. `08115`, `411`), or a region UUID. Look codes up in "
    "`/v0/data/regions/records?filter[name][_eq]=Böblingen`.\n\n"
    "Append `.csv` to the path for a CSV download of the `data` array."
)


# ---------------------------------------------------------------------------
# Shared response plumbing
# ---------------------------------------------------------------------------

def _to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    fieldnames = list(dict.fromkeys(k for row in rows for k in row))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


async def _respond(
    request: Request,
    endpoint: str,
    code: str,
    country: str | None,
    params: dict,
    ttl: int,
    build: Callable[[dict], Awaitable[dict]],
) -> Response:
    """Resolve the region, build (or load from cache) the body, and return it
    as JSON, or as CSV when the request path ends in `.csv`."""
    as_csv = request.url.path.endswith(".csv")
    raw_key = json.dumps({"endpoint": endpoint, "code": code, "country": country, **params}, sort_keys=True)
    cache_key = f"data:{hashlib.md5(raw_key.encode()).hexdigest()}"

    body = await cache.get_cached(cache_key)
    if body is None:
        region = await resolve_region(code, country)
        body = {"region": public_region(region), **(await build(region))}
        await cache.set_cached(cache_key, body, ttl)

    if as_csv:
        return Response(
            content=_to_csv(body["data"]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{code}_{endpoint}.csv"',
                "X-License": LICENSE,
            },
        )
    return JSONResponse(
        content=body,
        headers={"X-License": LICENSE, "Cache-Control": f"public, max-age={ttl}"},
    )


def _route(path: str, summary: str, description: str, example: dict | None = None):
    """Register a handler for both `path` and `path.csv`."""
    responses = {
        404: {"description": "Region not found, or no data for this region"},
        409: {"description": "Code matches regions in both countries — pass `country`"},
    }
    if example:
        responses[200] = {"description": summary, "content": {"application/json": {"example": example}}}

    def decorator(fn):
        router.add_api_route(
            path, fn, methods=["GET"], summary=summary,
            description=f"{description}\n\n{CODE_DOC}", tags=[TAG], responses=responses,
        )
        router.add_api_route(
            f"{path}.csv", fn, methods=["GET"], summary=f"{summary} (CSV)",
            description=f"{summary} as CSV (the `data` array).", tags=[TAG], response_class=Response,
        )
        return fn
    return decorator


def _pct(part: float | None, total: float | None) -> float | None:
    if part is None or not total:
        return None
    return round(part / total * 100, 2)


# ---------------------------------------------------------------------------
# Solar PV (Marktstammdatenregister, DE only)
# ---------------------------------------------------------------------------

MASTR_SOURCE = "Marktstammdatenregister (Bundesnetzagentur)"
MASTR_TTL = 6 * 3600

# MaStR "Lage der Einheit" codes used in energy_solar_units.type
SOLAR_TYPES = {
    "853": ("building", "Gebäudeanlagen (Dach, Fassade)"),
    "852": ("ground_mounted", "Freiflächenanlagen"),
    "2961": ("plug_in", "Steckerfertige Anlagen (Balkonkraftwerke)"),
    "2484": ("other_structure", "Sonstige bauliche Anlagen"),
    "3058": ("parking_lot", "Großparkplatz"),
    "3002": ("water", "Gewässer"),
}
SOLAR_TYPE_KEYS = {key: code for code, (key, _) in SOLAR_TYPES.items()}


def _solar_type_row(code: str, values: dict, total_power: float) -> dict:
    key, label = SOLAR_TYPES.get(code, ("unknown", "Unbekannt"))
    return {
        "type": key,
        "type_code": None if code == "Unbekannt" else code,
        "label": label,
        "power_kw": values.get("power_kw"),
        "units": values.get("units"),
        "share_of_power_pct": _pct(values.get("power_kw"), total_power),
        "added_power_kw_this_year": values.get("added_power_kw_this_year"),
        "added_units_this_year": values.get("added_units_this_year"),
    }


async def _solar_growth(region: dict, group: str, type_code: str | None = None) -> dict:
    require_country(region, ("DE",), "Solar PV data (Marktstammdatenregister)")
    params = {"table": "energy_solar_units", "group": group, "country": "DE"}
    if region["layer"] != "country":
        params["region"] = region["id"]
    if type_code:
        params["type"] = type_code
    return await directus.fetch_endpoint("/get-renewables-growth", params)


@_route(
    "/regions/{code}/solar",
    "Solar PV expansion",
    "Installed solar PV capacity and number of units for a German municipality, district, "
    "state or Germany as a whole, per year (from 2000) or month (from 2010). "
    "`added_*` counts units commissioned in the period, `removed_*` units shut down, "
    "`cumulative_*` the stock at the end of the period (earlier units are included in the "
    "first row's cumulative values). Capacity is net power in kW.\n\n"
    "Filter by installation type with `type` (see `/regions/{code}/solar-types`).\n\n"
    f"**Source:** {MASTR_SOURCE}, updated daily. Germany only.",
)
async def get_region_solar(
    request: Request,
    code: str,
    group: Annotated[Literal["year", "month"], Query(description=QUERY_DESC_GROUP)] = "year",
    type: Annotated[
        str | None,
        Query(description="Only one installation type: " + ", ".join(f"`{k}`" for k in SOLAR_TYPE_KEYS)),
    ] = None,
    country: Annotated[str | None, Query(description=QUERY_DESC_COUNTRY)] = None,
):
    if type and type not in SOLAR_TYPE_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown type '{type}'. Use one of: {', '.join(SOLAR_TYPE_KEYS)}")

    async def build(region: dict) -> dict:
        result = await _solar_growth(region, group, SOLAR_TYPE_KEYS.get(type) if type else None)
        return {
            "data": result.get("by_year") or result.get("by_month") or [],
            "meta": {
                "source": MASTR_SOURCE,
                "unit": "kW (net power), units = number of installations",
                "group": group,
                "type": type,
                "update_date": result.get("update_date"),
                "grid_operator_checked_share_pct": result.get("grid_operator_checked_ratio"),
                "license": LICENSE,
            },
        }

    return await _respond(request, "solar", code, country, {"group": group, "type": type}, MASTR_TTL, build)


@_route(
    "/regions/{code}/solar-types",
    "Solar PV by installation type",
    "Current solar PV stock split by installation type — rooftop/building, ground-mounted, "
    "plug-in (balcony) systems and others — with capacity, number of units, share of total "
    "capacity, and additions in the current year.\n\n"
    f"**Source:** {MASTR_SOURCE}, updated daily. Germany only.",
)
async def get_region_solar_types(
    request: Request,
    code: str,
    country: Annotated[str | None, Query(description=QUERY_DESC_COUNTRY)] = None,
):
    async def build(region: dict) -> dict:
        result = await _solar_growth(region, "year")
        by_type = result.get("current_by_type") or {}
        total_power = sum(v.get("power_kw") or 0 for v in by_type.values())
        rows = sorted(
            (_solar_type_row(type_code, values, total_power) for type_code, values in by_type.items()),
            key=lambda r: -(r["power_kw"] or 0),
        )
        return {
            "data": rows,
            "meta": {
                "source": MASTR_SOURCE,
                "unit": "kW (net power), units = number of installations",
                "update_date": result.get("update_date"),
                "license": LICENSE,
            },
        }

    return await _respond(request, "solar_types", code, country, {}, MASTR_TTL, build)


# ---------------------------------------------------------------------------
# Battery storage (Marktstammdatenregister, DE only)
# ---------------------------------------------------------------------------

BATTERY_CATEGORIES = {"Heimspeicher", "Gewerbespeicher", "Grossspeicher"}
STORAGE_METRICS = (
    "added_power_kw", "added_capacity_kwh", "added_units",
    "cumulative_power_kw", "cumulative_capacity_kwh", "cumulative_units",
)


def _storage_prefix(category: str) -> str:
    # Mirrors the column prefix the get-storage-growth extension builds
    return category.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")


def _storage_rows(by_period: list[dict], categories: list[str]) -> list[dict]:
    rows = []
    for entry in by_period:
        battery_total = dict.fromkeys(STORAGE_METRICS, 0)
        period_rows = []
        for category in categories:
            prefix = _storage_prefix(category)
            values = {m: entry.get(f"{prefix}_{m}", 0) for m in STORAGE_METRICS}
            is_battery = category in BATTERY_CATEGORIES
            if is_battery:
                for m in STORAGE_METRICS:
                    battery_total[m] += values[m]
            period_rows.append({"period": entry["period"], "category": category, "is_battery": is_battery, **values})
        rows.append({"period": entry["period"], "category": "battery_total", "is_battery": True, **battery_total})
        rows.extend(period_rows)
    for row in rows:
        # The extension reports additions net of shutdowns
        for m in ("power_kw", "capacity_kwh", "units"):
            row[f"net_added_{m}"] = row.pop(f"added_{m}")
    return rows


@_route(
    "/regions/{code}/battery-storage",
    "Battery storage expansion",
    "Installed storage power (kW), usable capacity (kWh) and number of units per year "
    "(from 2000) or month, split by storage category. Battery categories are "
    "`Heimspeicher` (home), `Gewerbespeicher` (commercial) and `Grossspeicher` (utility-scale); "
    "rows with `category=battery_total` sum these three. Non-battery storage "
    "(pumped hydro, compressed air, hydrogen, flywheel) is included with `is_battery=false`.\n\n"
    "`net_added_*` is commissioned minus decommissioned in the period; `cumulative_*` is the "
    "stock at the end of the period.\n\n"
    f"**Source:** {MASTR_SOURCE}, updated daily. Germany only.",
)
async def get_region_battery_storage(
    request: Request,
    code: str,
    group: Annotated[Literal["year", "month"], Query(description=QUERY_DESC_GROUP)] = "year",
    country: Annotated[str | None, Query(description=QUERY_DESC_COUNTRY)] = None,
):
    async def build(region: dict) -> dict:
        require_country(region, ("DE",), "Storage data (Marktstammdatenregister)")
        params = {"group": group, "country": "DE"}
        if region["layer"] != "country":
            params["region"] = region["id"]
        result = await directus.fetch_endpoint("/get-storage-growth", params)
        return {
            "data": _storage_rows(result.get("by_period", []), result.get("categories", [])),
            "meta": {
                "source": MASTR_SOURCE,
                "unit": "kW (power), kWh (usable capacity), units = number of installations",
                "group": group,
                "battery_categories": sorted(BATTERY_CATEGORIES),
                "update_date": result.get("update_date"),
                "license": LICENSE,
            },
        }

    return await _respond(request, "battery_storage", code, country, {"group": group}, MASTR_TTL, build)


# ---------------------------------------------------------------------------
# Cars (KBA / DESTATIS / Statistik Austria)
# ---------------------------------------------------------------------------

CARS_TTL = 86400
CARS_LAYERS = ("municipality", "district", "state")
CAR_OWNER_CATEGORIES = {"Insgesamt", "Privat", "Firmen"}
SQM_PER_CAR = 11.5
FOOTBALL_PITCH_SQM = 105 * 68


async def _car_rows(region: dict) -> tuple[list[dict], int | None]:
    """mobility_cars rows for a region. Regions without own figures are summed
    from their municipalities; returns the number of municipalities used (or None)."""
    fields = ["region", "period", "category", "value", "source"]
    result = await directus.search_items("mobility_cars", {
        "filter": {"region": {"_in": region_codes(region)}, "country": {"_eq": region["country"]}},
        "fields": fields, "limit": -1,
    })
    rows = result.get("data", [])
    if rows or region["layer"] == "municipality":
        return rows, None

    children = await child_municipalities(region)
    codes = [c for m in children for c in region_codes(m)]
    if not codes:
        return [], None
    result = await directus.search_items("mobility_cars", {
        "filter": {"region": {"_in": codes}, "country": {"_eq": region["country"]}},
        "fields": fields, "limit": -1,
    })
    rows = result.get("data", [])
    return rows, len({r["region"] for r in rows}) or None


def _cars_by_period(rows: list[dict]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r.get("value") is not None:
            out[str(r["period"])][r["category"]] += r["value"]
    return {p: dict(v) for p, v in sorted(out.items())}


def _cars_meta(rows: list[dict], aggregated_from: int | None) -> dict:
    return {
        "source": ", ".join(sorted({r["source"] for r in rows if r.get("source")})),
        "aggregated_from_municipalities": aggregated_from,
        "license": LICENSE,
    }


async def _cars(region: dict) -> tuple[dict[str, dict[str, float]], dict]:
    require_layer(region, CARS_LAYERS)
    rows, aggregated_from = await _car_rows(region)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No car registration data for '{region['name']}'.")
    return _cars_by_period(rows), _cars_meta(rows, aggregated_from)


@_route(
    "/regions/{code}/car-density",
    "Car density",
    "Registered passenger cars per period: total, privately vs. company-owned, cars per 1,000 "
    "inhabitants, and — where published — a breakdown by fuel type (`by_fuel_type`). "
    "Districts and states without their own figures are summed from their municipalities.\n\n"
    "`cars_per_1000_inhabitants` uses the region's current population for every period.\n\n"
    "**Sources:** DE: Kraftfahrt-Bundesamt (FZ 3, municipalities), DESTATIS (districts, with fuel "
    "types); AT: Statistik Austria Kfz-Bestand (municipalities, with fuel types).",
)
async def get_region_car_density(
    request: Request,
    code: str,
    country: Annotated[str | None, Query(description=QUERY_DESC_COUNTRY)] = None,
):
    async def build(region: dict) -> dict:
        by_period, meta = await _cars(region)
        population = region.get("population")
        data, by_fuel = [], []
        for period, cats in by_period.items():
            total = cats.get("Insgesamt")
            data.append({
                "period": period,
                "cars_total": total,
                "cars_private": cats.get("Privat"),
                "cars_company": cats.get("Firmen"),
                "private_share_pct": _pct(cats.get("Privat"), total),
                "population": population,
                "cars_per_1000_inhabitants": round(total / population * 1000, 1) if total and population else None,
            })
            by_fuel += [
                {"period": period, "fuel_type": cat, "cars": value, "share_pct": _pct(value, total)}
                for cat, value in cats.items() if cat not in CAR_OWNER_CATEGORIES
            ]
        return {"data": data, "by_fuel_type": by_fuel, "meta": {**meta, "unit": "passenger cars"}}

    return await _respond(request, "car_density", code, country, {}, CARS_TTL, build)


@_route(
    "/regions/{code}/car-land-use",
    "Land used by parked cars",
    f"Estimated area needed to park every registered passenger car, assuming {SQM_PER_CAR} m² "
    "per parking space, expressed in m², hectares, football pitches (105 × 68 m) and as a "
    "share of the region's total area.\n\n"
    "Car counts come from the same sources as `/regions/{code}/car-density`.",
)
async def get_region_car_land_use(
    request: Request,
    code: str,
    country: Annotated[str | None, Query(description=QUERY_DESC_COUNTRY)] = None,
):
    async def build(region: dict) -> dict:
        by_period, meta = await _cars(region)
        area_sqm = (region.get("area") or 0) * 1_000_000
        population = region.get("population")
        data = []
        for period, cats in by_period.items():
            total = cats.get("Insgesamt")
            parking = total * SQM_PER_CAR if total else None
            data.append({
                "period": period,
                "cars_total": total,
                "parking_area_m2": round(parking) if parking else None,
                "parking_area_ha": round(parking / 10_000, 1) if parking else None,
                "football_pitches": round(parking / FOOTBALL_PITCH_SQM, 1) if parking else None,
                "share_of_region_area_pct": _pct(parking, area_sqm),
                "parking_area_m2_per_inhabitant": round(parking / population, 1) if parking and population else None,
            })
        return {
            "data": data,
            "meta": {
                **meta,
                "assumption_m2_per_car": SQM_PER_CAR,
                "football_pitch_m2": FOOTBALL_PITCH_SQM,
                "region_area_km2": region.get("area"),
            },
        }

    return await _respond(request, "car_land_use", code, country, {}, CARS_TTL, build)


# ---------------------------------------------------------------------------
# Heating systems (Zensus 2022 / Mikrozensus)
# ---------------------------------------------------------------------------

HEATING_TTL = 86400
HEATING_SOURCES = {
    "DE": {
        "key": "zensus-federal-statistical-office",
        "label": "Statistische Ämter des Bundes und der Länder, Zensus 2022",
        "unit": "dwellings (Wohnungen) by main heating energy source",
    },
    "AT": {
        "key": "mikrozensus-statistik-austria",
        "label": "Statistik Austria, Mikrozensus Energieeinsatz der Haushalte",
        "unit": "households by main heating energy source",
    },
}


async def _heating_rows(region_ids: list[str], source: str) -> list[dict]:
    filt = {"region": {"_in": region_ids}, "source": {"_eq": source}}
    if source == HEATING_SOURCES["AT"]["key"]:
        filt["unit"] = {"_eq": "absolute"}
    result = await directus.search_items("energy_heating_systems", {
        "filter": filt, "fields": ["region", "period", "category", "value"], "limit": -1,
    })
    return result.get("data", [])


def _heating_by_period(rows: list[dict]) -> list[dict]:
    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        sums[r["period"]][r["category"]] += r.get("value") or 0
    data = []
    for period in sorted(sums):
        cats = sums[period]
        total = cats.get("total")
        for category in sorted(cats, key=lambda c: (c != "total", -cats[c])):
            data.append({
                "period": period,
                "category": category,
                "value": cats[category],
                "share_pct": _pct(cats[category], total),
            })
    return data


@_route(
    "/regions/{code}/heating",
    "Heating systems",
    "Dwellings (DE) or households (AT) by main heating energy source — gas, heating oil, "
    "district heating, heat pumps/solar thermal, wood, electricity, etc. — with each "
    "source's share of the total.\n\n"
    "**Germany:** Zensus 2022, available per municipality; districts and states are summed "
    "from their municipalities.\n\n"
    "**Austria:** Statistik Austria Mikrozensus (biennial since 2003/04), only published per "
    "federal state. Requests for an Austrian municipality or district return the figures of "
    "its federal state; `data_region` tells you which region the numbers describe. The "
    "Mikrozensus period stored as `2024-12-31` covers the survey wave July 2023 – June 2024.",
)
async def get_region_heating(
    request: Request,
    code: str,
    country: Annotated[str | None, Query(description=QUERY_DESC_COUNTRY)] = None,
):
    async def build(region: dict) -> dict:
        source = HEATING_SOURCES[region["country"]]
        data_region = public_region(region)

        if region["country"] == "AT":
            target_id = region["id"]
            if region["layer"] in ("municipality", "district"):
                target_id = parent_of_layer(region, "state")
                state = await resolve_region(target_id) if target_id else None
                data_region = public_region(state) if state else None
            rows = await _heating_rows([target_id], source["key"]) if target_id else []
        else:
            require_layer(region, CARS_LAYERS)
            if region["layer"] == "municipality":
                ids = [region["id"]]
            else:
                ids = [m["id"] for m in await child_municipalities(region)]
            rows = await _heating_rows(ids, source["key"]) if ids else []

        if not rows:
            raise HTTPException(status_code=404, detail=f"No heating data for '{region['name']}'.")
        return {
            "data_region": data_region,
            "data": _heating_by_period(rows),
            "meta": {
                "source": source["label"],
                "unit": source["unit"],
                "aggregated_from_municipalities": len({r["region"] for r in rows})
                if region["country"] == "DE" and region["layer"] != "municipality" else None,
                "license": LICENSE,
            },
        }

    return await _respond(request, "heating", code, country, {}, HEATING_TTL, build)

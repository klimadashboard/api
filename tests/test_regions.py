"""Unit tests for the per-region endpoints' data shaping and region lookup.

Directus is mocked, so these run offline: `pytest tests/test_regions.py`.
"""

import asyncio

import pytest
from fastapi import HTTPException

from app.routes import regions as routes
from app.services import cache, directus
from app.services import regions as region_service


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    async def get_cached(key):
        return None

    async def set_cached(key, value, ttl):
        pass

    monkeypatch.setattr(cache, "get_cached", get_cached)
    monkeypatch.setattr(cache, "set_cached", set_cached)


def test_storage_rows_adds_battery_total_and_renames_net_fields():
    by_period = [{
        "period": 2025,
        **{f"heimspeicher_{m}": 10 for m in routes.STORAGE_METRICS},
        **{f"grossspeicher_{m}": 5 for m in routes.STORAGE_METRICS},
        **{f"pumpspeicher_{m}": 1000 for m in routes.STORAGE_METRICS},
    }]
    rows = routes._storage_rows(by_period, ["Heimspeicher", "Grossspeicher", "Pumpspeicher"])

    total = rows[0]
    assert total["category"] == "battery_total"
    assert total["cumulative_capacity_kwh"] == 15
    assert total["net_added_units"] == 15
    assert "added_units" not in total
    pumped = next(r for r in rows if r["category"] == "Pumpspeicher")
    assert pumped["is_battery"] is False


def test_cars_by_period_sums_municipalities_and_skips_nulls():
    rows = [
        {"region": "a", "period": "2024", "category": "Insgesamt", "value": 100},
        {"region": "b", "period": "2024", "category": "Insgesamt", "value": 50},
        {"region": "b", "period": "2024", "category": "Privat", "value": None},
        {"region": "a", "period": "2019", "category": "Insgesamt", "value": 90},
    ]
    result = routes._cars_by_period(rows)
    assert list(result) == ["2019", "2024"]
    assert result["2024"] == {"Insgesamt": 150}


def test_heating_by_period_puts_total_first_with_shares():
    rows = [
        {"region": "a", "period": "2022", "category": "gas", "value": 30},
        {"region": "a", "period": "2022", "category": "total", "value": 100},
        {"region": "b", "period": "2022", "category": "gas", "value": 20},
        {"region": "b", "period": "2022", "category": "heating oil", "value": 10},
    ]
    data = routes._heating_by_period(rows)
    assert [r["category"] for r in data] == ["total", "gas", "heating oil"]
    assert data[1]["value"] == 50
    assert data[1]["share_pct"] == 50.0


def test_resolve_region_rejects_ambiguous_codes(monkeypatch):
    async def fetch_items(**kwargs):
        return {"data": [
            {"name": "A", "country": "AT", "layer": "municipality"},
            {"name": "B", "country": "DE", "layer": "district"},
        ]}

    monkeypatch.setattr(directus, "fetch_items", fetch_items)
    with pytest.raises(HTTPException) as exc:
        run(region_service.resolve_region("10101"))
    assert exc.value.status_code == 409


def test_child_municipalities_skips_same_name_aggregate(monkeypatch):
    wien = {"id": "wien", "name": "Wien", "country": "AT"}
    munis = [
        {"id": "1", "name": "Wien", "parents": [{"id": "wien", "layer": "state"}]},
        {"id": "2", "name": "Innere Stadt", "parents": [{"id": "wien", "layer": "state"}]},
        {"id": "3", "name": "Graz", "parents": [{"id": "stmk", "layer": "state"}]},
    ]

    async def fetch_items(**kwargs):
        return {"data": munis}

    monkeypatch.setattr(directus, "fetch_items", fetch_items)
    assert [m["id"] for m in run(region_service.child_municipalities(wien))] == ["2"]


def test_solar_rejects_austrian_regions():
    with pytest.raises(HTTPException) as exc:
        run(routes._solar_growth({"country": "AT", "layer": "municipality", "id": "x"}, "year"))
    assert exc.value.status_code == 404

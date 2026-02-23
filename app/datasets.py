DATASETS = {
    "emissions_data": {
        "title": "Greenhouse Gas Emissions",
        "description": (
            "Greenhouse gas emissions data for various regions and countries, broken down by sector "
            "(energy, industry, transport, etc.), gas type, and year. "
            "Values are in kt CO2-equivalent."
        ),
        "license": "CC-BY-4.0",
        "source": "see source field",
        "source_url": "",
        "tags": ["climate", "emissions", "greenhouse-gas", "austria"],
        "update_frequency": "yearly",
        "cache_ttl": 3600,
        "fields": {
            "id": "Auto-incrementing primary key",
            "gas": "Greenhouse gas identifier (e.g. THG = total GHG)",
            "source": "Data source label (e.g. 'BLI 2025 (1990-2023)')",
            "year": "Year of observation",
            "month": "Month (null for annual data)",
            "day": "Day (null for annual data)",
            "update": "Last update timestamp (ISO 8601)",
            "value": "Emissions in kt CO2-equivalent",
            "value_weighted": "Population-weighted value (if available)",
            "country": "ISO 3166-1 alpha-2 country code (AT, DE)",
            "region": "Region UUID (foreign key)",
            "category": "Emissions sector (e.g. ksg_energy, ksg_transport)",
            "type": "Sub-type within category (e.g. Gesamt = total)",
            "scenario": "Scenario label (null for historical data, 'target' for projections)",
        },
        "example_record": {
            "id": 36184,
            "gas": "THG",
            "source": "BLI 2025 (1990-2023)",
            "year": 1990,
            "update": "2025-07-30T00:00:00",
            "month": None,
            "day": None,
            "value": 7543.558,
            "value_weighted": None,
            "country": "AT",
            "region": "2bc3faed-7cb4-492c-9097-145a0f8f1f01",
            "category": "ksg_energy",
            "type": "Gesamt",
            "scenario": None,
        },
        "example_queries": [
            "filter[year][_gte]=2020 — records from 2020 onward",
            "filter[category][_eq]=ksg_transport — only transport sector",
            "filter[country][_eq]=AT — only Austria",
            "sort=-year&limit=10 — latest 10 records by year",
            "fields=year,value,category — return only selected columns",
        ],
    },
    "mobility_modal_split": {
        "title": "Mobility Modal Split",
        "description": (
            "Modal split data showing the percentage share of different "
            "transport modes (walking, cycling, public transport, car) "
            "in various Austrian and German regions."
        ),
        "license": "CC-BY-4.0",
        "source": "various sources, see the source field",
        "source_url": None,
        "tags": ["mobility", "transport", "modal-split", "austria"],
        "update_frequency": "yearly",
        "cache_ttl": 3600,
        "fields": {
            "id": "Auto-incrementing primary key",
            "year": "Year of observation",
            "category": "Transport mode (on_foot, bicycle, e_bike, public_transport, car, etc.)",
            "region": "Region UUID (foreign key)",
            "value": "Percentage share of this transport mode (integer, 0-100)",
            "source": "Data source name",
            "update": "Last update date (YYYY-MM-DD)",
            "source_link": "URL to original data source (if available)",
        },
        "example_record": {
            "id": 8,
            "year": 2017,
            "category": "on_foot",
            "region": "dd4fd7ac-aa2b-4762-8902-1be6ef2fcdb2",
            "value": 8,
            "source": "Kommunale Mobilitaetserhebung",
            "update": "2025-12-18",
            "source_link": None,
        },
        "example_queries": [
            "filter[year][_eq]=2017 — data for a specific year",
            "filter[category][_eq]=bicycle — only cycling data",
            "sort=category — sort alphabetically by transport mode",
        ],
    },
    "mobility_modal_split_goals": {
        "title": "Mobility Modal Split Goals",
        "description": (
            "Policy targets for sustainable transport modal split in "
            "Austrian and German cities and regions, including target years and "
            "sustainable mobility percentage goals."
        ),
        "license": "CC-BY-4.0",
        "source": "Various city climate mobility plans",
        "source_url": None,
        "tags": ["mobility", "transport", "targets", "policy", "austria"],
        "update_frequency": "yearly",
        "cache_ttl": 86400,
        "fields": {
            "id": "UUID primary key",
            "region": "Region UUID (foreign key)",
            "target_year": "Year by which the goal should be achieved",
            "goal_type": "Type of goal (e.g. sustainable_total)",
            "sustainable_target": "Target percentage for sustainable transport (string, e.g. '66.00')",
            "category_targets": "Per-category breakdown (JSON object, if available)",
            "goal_path": "Intermediate milestones / trajectory (JSON array, if available)",
            "source": "Policy source document name",
            "update": "Last update date (YYYY-MM-DD)",
        },
        "example_record": {
            "id": "07d68325-e42e-4eb5-add2-50837f459efd",
            "region": "",
            "target_year": 2050,
            "goal_type": "sustainable_total",
            "sustainable_target": "90.00",
            "category_targets": None,
            "goal_path": None,
            "source": "Klimamobilitaetsplan of City",
            "update": "2026-01-01",
        },
        "example_queries": [
            "filter[target_year][_lte]=2030 — goals with deadline by 2030",
            "sort=target_year — sort by target year",
        ],
    },
}

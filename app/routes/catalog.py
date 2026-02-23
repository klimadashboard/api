from fastapi import APIRouter, HTTPException
from app.datasets import DATASETS

router = APIRouter()

API_PREFIX = "/v0"


@router.get(
    "/data",
    summary="List all datasets",
    description=(
        "Returns metadata for all available datasets in the catalog, "
        "including endpoints, license information, and update frequency."
    ),
    tags=["Data Catalog"],
)
async def list_datasets():
    results = []
    for dataset_id, meta in DATASETS.items():
        results.append(
            {
                "id": dataset_id,
                "title": meta["title"],
                "description": meta["description"],
                "license": meta["license"],
                "source": meta["source"],
                "source_url": meta["source_url"],
                "tags": meta["tags"],
                "update_frequency": meta["update_frequency"],
                "endpoints": {
                    "metadata": f"{API_PREFIX}/data/{dataset_id}",
                    "records": f"{API_PREFIX}/data/{dataset_id}/records",
                    "csv": f"{API_PREFIX}/data/{dataset_id}/records.csv",
                },
            }
        )
    return {"datasets": results, "total": len(results)}


@router.get(
    "/data/{dataset_id}",
    summary="Get dataset metadata",
    description=(
        "Returns detailed metadata for a single dataset, including "
        "field descriptions, example queries, and available endpoints."
    ),
    tags=["Data Catalog"],
)
async def get_dataset(dataset_id: str):
    if dataset_id not in DATASETS:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    meta = DATASETS[dataset_id]
    return {
        "id": dataset_id,
        "title": meta["title"],
        "description": meta["description"],
        "license": meta["license"],
        "source": meta["source"],
        "source_url": meta["source_url"],
        "tags": meta["tags"],
        "update_frequency": meta["update_frequency"],
        "fields": meta["fields"],
        "example_queries": meta.get("example_queries", []),
        "endpoints": {
            "records": f"{API_PREFIX}/data/{dataset_id}/records",
            "csv": f"{API_PREFIX}/data/{dataset_id}/records.csv",
        },
    }

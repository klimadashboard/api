import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from scalar_fastapi import get_scalar_api_reference
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.routes import catalog, data
from app.services import cache, directus

load_dotenv()
logging.basicConfig(level=logging.INFO)

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

DESCRIPTION = """\
> **Beta API** — This API is in active development. Endpoints, response \
structures, and data formats may change without notice. We do not assume \
any responsibility for the accuracy, completeness, or reliability of the \
data provided.

---

Public API for climate data, curated by \
[Klimadashboard](https://klimadashboard.org).

All data is freely available under open licenses.
We’re adding new datasets continually.

---

**Links**

- [klimadashboard.org](https://klimadashboard.org)
- [GitHub: klimadashboard/api](https://github.com/klimadashboard/api) \
— report issues and request new datasets here

---

### How to use this API

**Pagination:** Use `limit` (default 100, max 10,000) and `offset` parameters.

**Sorting:** Use `sort=field` for ascending or `sort=-field` for descending order.

**Field selection:** Use `fields=field1,field2` to return only specific columns.

**Filtering:** Use `filter[field][operator]=value` query parameters. \
Supported operators:

| Operator | Meaning |
|----------|---------|
| `_eq` | Equals |
| `_neq` | Not equals |
| `_gt` / `_gte` | Greater than / greater or equal |
| `_lt` / `_lte` | Less than / less or equal |
| `_in` | In list (comma-separated) |
| `_contains` | Contains substring |
| `_null` | Is null (true/false) |

**Example:** `/v0/data/emissions_data/records?filter[year][_gte]=2020&sort=-year&limit=10`

**CSV export:** Append `.csv` to any records endpoint for a downloadable file.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    directus.init_directus(os.environ["DIRECTUS_URL"])
    await cache.init_redis(os.environ.get("REDIS_URL", "redis://localhost:6379"))
    yield
    await directus.close_directus()
    await cache.close_redis()


app = FastAPI(
    title="Klimadashboard Open Data API",
    description=DESCRIPTION,
    version="0.1.0-beta",
    license_info={"name": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
    contact={
        "name": "Klimadashboard",
        "url": "https://klimadashboard.org",
    },
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please slow down."},
        headers={"Retry-After": "60"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
    expose_headers=["X-License"],
)

# --- Versioned API routes under /v0 ---
from fastapi import APIRouter

v0_router = APIRouter(prefix="/v0")
v0_router.include_router(catalog.router)
v0_router.include_router(data.router)
app.include_router(v0_router)


# --- Docs and root (outside versioning) ---

@app.get("/docs", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title="Klimadashboard Open Data API",
    )


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")

# Order API

A Python REST API for order intake, idempotent order creation, stock processing, and daily reporting, backed by PostgreSQL.

Design decisions, assumptions, and trade-offs are documented in [SOLUTION.md](SOLUTION.md). AI assistance is documented in [AI_USAGE.md](AI_USAGE.md).

## Status

| Capability | Status |
|---|---|
| Order intake (idempotent, price snapshots, atomic) | Implemented |
| `GET /orders/{order_ref}`, `GET /products/{sku}`, `GET /health` | Implemented |
| Stock processor (`process_one_order`) | Implemented |
| Worker runner (polling, shutdown, Compose service) | Not yet implemented |
| `GET /reports/daily` | Not yet implemented |
| Wontainers | Not yet implemented |
| Seed + burst script (`scripts/seed_and_burst.py`) | Implemented (duplicate demo); interruption phase pending worker |

## Requirements

- Python 3.14
- Docker Engine or Docker Desktop with Docker Compose
- `uv` for Python dependency and environment management

## Configuration

Copy `.env.example` to `.env` and set:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Database used by the running API |
| `TEST_DATABASE_URL` | Database used by the tests. The database name must end in `_test`; the test suite refuses to run otherwise because it truncates all tables. |

Variables already set in the environment take precedence over `.env`.

Do not commit `.env` or other files containing credentials.

## Run locally

Start PostgreSQL, install dependencies, and start the API:

```bash
docker compose up -d db
uv sync
uv run uvicorn order_api.main:app --reload
```

The schema is created automatically when the API starts.

## Burst script

`scripts/seed_and_burst.py` seeds demo products and submits a short burst of orders, intentionally including duplicate submissions of the same `order_ref`. Each run uses a unique run ID, so it can be re-run without colliding with earlier data.

Until the stock-processing worker is implemented, run with `--skip-interruption`:

```bash
uv run python scripts/seed_and_burst.py --skip-interruption
```

Once the worker honours the pause sentinel, drop the flag to also demonstrate the interruption/catch-up path:

```bash
uv run python scripts/seed_and_burst.py
```

| Flag | Purpose |
|---|---|
| `--api-url` | Base URL of the running API (default `http://localhost:8000`, or `$API_URL`). |
| `--database-url` | Database used only for seeding demo products (default `$DATABASE_URL`). |
| `--sentinel` | Pause-file path shared with the worker (default `.worker_paused`, or `$WORKER_PAUSE_SENTINEL`). |
| `--skip-interruption` | Skip the pause/resume phase. Use this until the worker is implemented. |
| `--settle-seconds` | Maximum time to wait for the worker to process orders (default 15). |

The script exits non-zero if any phase fails, so it is safe to run in CI. See [SOLUTION.md](SOLUTION.md) for the pause-sentinel contract.

## API documentation

Interactive API documentation is available at `http://localhost:8000/docs` while the API is running.

| Endpoint | Success | Errors |
|---|---|---|
| `POST /orders` | `202 Accepted` (order persisted with status `RECEIVED`; an identical retry returns the existing order) | `409` same `order_ref` with a different payload, `404` unknown SKU, `422` invalid request (including a combined quantity over 1,000,000 for one SKU) |
| `GET /orders/{order_ref}` | `200` | `404` |
| `GET /products/{sku}` | `200` | `404` |

Orders stay `RECEIVED` until the stock processor runs. The polling worker that runs it automatically is not built yet.

`POST /orders` returns `202` with a `Location` header because stock processing happens asynchronously after the order is stored. See [SOLUTION.md](SOLUTION.md).

## Tests

```bash
uv run pytest
```

### Test database

Tests use a separate PostgreSQL database (`order_api_test`) configured through `TEST_DATABASE_URL`. Every test starts from empty tables.

Before running tests for the first time:

1. Start PostgreSQL:

   ```bash
   docker compose up -d db
   ```

2. Create the test database:

   ```bash
   docker compose exec db psql -U order_api -d postgres -c "CREATE DATABASE order_api_test;"
   ```

**Resetting the test database**

```bash
docker compose exec db psql -U order_api -d postgres -c "DROP DATABASE order_api_test WITH (FORCE);"
docker compose exec db psql -U order_api -d postgres -c "CREATE DATABASE order_api_test;"
```

**Warning:** Resetting the test database permanently deletes its contents. Never run these commands against the development or production database.

## Linting

```bash
uv run ruff check .
uv run ruff format .
```

## Scope

The target scope is order creation and retrieval, product stock lookup, asynchronous stock processing with recovery after interruption, and a daily report endpoint. The Status table above shows what is built so far.

See [SOLUTION.md](SOLUTION.md) for the selected behaviour and remaining assumptions.

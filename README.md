# Order API

A Python REST API for order intake, idempotent order creation, stock processing, and daily reporting, backed by PostgreSQL.

Design decisions, assumptions, and trade-offs are documented in [SOLUTION.md](SOLUTION.md). AI assistance is documented in [AI_USAGE.md](AI_USAGE.md).

## Status

| Capability | Status |
|---|---|
| Order intake (idempotent, price snapshots, atomic) | Implemented |
| `GET /orders/{order_ref}`, `GET /products/{sku}`, `GET /health` | Implemented |
| Stock-processing worker | Not yet implemented |
| `GET /reports/daily` | Not yet implemented |
| Application and worker containers | Not yet implemented |

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

## API documentation

Interactive API documentation is available at `http://localhost:8000/docs` while the API is running.

| Endpoint | Success | Errors |
|---|---|---|
| `POST /orders` | `202 Accepted` (order persisted with status `RECEIVED`; an identical retry returns the existing order) | `409` same `order_ref` with a different payload, `404` unknown SKU, `422` invalid request (including a combined quantity over 1,000,000 for one SKU) |
| `GET /orders/{order_ref}` | `200` | `404` |
| `GET /products/{sku}` | `200` | `404` |

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

# Order API

A Python REST API for order intake, idempotent order creation, stock processing, and daily reporting, backed by PostgreSQL.

Design decisions, assumptions, and trade-offs are documented in [SOLUTION.md](SOLUTION.md). AI assistance is documented in [AI_USAGE.md](AI_USAGE.md).

## Status

| Capability | Status |
|---|---|
| Order intake (idempotent, price snapshots, atomic) | Implemented |
| `GET /orders/{order_ref}`, `GET /products/{sku}`, `GET /health` | Implemented |
| Stock processor (`process_one_order`) | Implemented |
| Worker runner (polling, graceful shutdown, pause sentinel) | Implemented |
| `GET /reports/daily` | Implemented |
| Docker images and Compose services (`api`, `worker`) | Implemented |

## Requirements

- Python 3.14
- Docker Engine or Docker Desktop with Docker Compose
- `uv` for Python dependency and environment management

## Configuration

Copy `.env.example` to `.env`.

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Database password used by Docker Compose |
| `DATABASE_URL` | Database for the API and worker when run outside Docker |
| `TEST_DATABASE_URL` | Database for the tests. The name must end in `_test`; the test suite truncates all tables and refuses to run otherwise. |
| `WORKER_POLL_INTERVAL` | Seconds the worker waits when there is no work (default `1`) |
| `WORKER_PAUSE_SENTINEL` | While this file exists the worker does not process orders (default `.worker_paused`) |

Variables already set in the environment take precedence over `.env`. Do not commit `.env`.

## Run with Docker (API + worker + database)

```bash
docker compose up --build
```

The API is on `http://localhost:8000` (docs at `/docs`). The worker starts once the API is healthy. The test database `order_api_test` is created automatically the first time the database volume is created; on an existing volume, create it manually (see Tests).

## Run locally

```bash
docker compose up -d db
uv sync
uv run uvicorn order_api.main:app --reload     # terminal 1
uv run python -m order_api.worker              # terminal 2
```

## Pause and resume processing (demonstration)

Orders are always accepted; the worker only processes them while the sentinel file does not exist.

```bash
touch worker_control/paused     # pause: new orders stay RECEIVED
rm worker_control/paused        # resume: the worker catches up on the backlog
```

This path is used by Docker Compose. For a local worker, set `WORKER_PAUSE_SENTINEL=worker_control/paused`. Make sure `scripts/seed_and_burst.py` uses the same path.

## Burst script

`scripts/seed_and_burst.py` seeds demo products, submits a burst of orders (including intentional duplicates), and demonstrates the interruption scenario: orders are accepted while processing is paused, then processed after resuming. Each run uses a unique run ID, so it can be repeated without colliding with earlier data.

**Prerequisites:** the database, API and worker must be running, and `.env` must exist so the script uses the same pause file as the worker (`WORKER_PAUSE_SENTINEL=worker_control/paused`).

```bash
uv run python scripts/seed_and_burst.py                      # full demonstration
uv run python scripts/seed_and_burst.py --skip-interruption  # duplicates only
```

| Flag | Purpose |
|---|---|
| `--api-url` | Base URL of the API (default `http://localhost:8000`, or `$API_URL`). |
| `--database-url` | Database used only to seed demo products (default `$DATABASE_URL`). |
| `--sentinel` | Pause-file path shared with the worker (default `$WORKER_PAUSE_SENTINEL`, else `.worker_paused`). |
| `--skip-interruption` | Skip the pause/resume phase. |
| `--settle-seconds` | Maximum time to wait for the worker to process orders (default 15). |

The script creates and removes the pause file itself. It exits non-zero if any phase fails.

## API documentation

Interactive API documentation is available at `http://localhost:8000/docs` while the API is running.

| Endpoint | Success | Errors |
|---|---|---|
| `POST /orders` | `202 Accepted` (order persisted with status `RECEIVED`; an identical retry returns the existing order) | `409` same `order_ref` with a different payload, `404` unknown SKU, `422` invalid request (including a combined quantity over 1,000,000 for one SKU) |
| `GET /orders/{order_ref}` | `200` | `404` |
| `GET /products/{sku}` | `200` | `404` |
| `GET /reports/daily?date=YYYY-MM-DD` | `200` | `422` missing or invalid date |

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

2. Create the test database (not needed on a fresh volume, where Compose creates it):

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

## Troubleshooting

**Orders stay `RECEIVED` and the burst script times out** ("Orders did not all reach PROCESSED")

The orders were accepted but nothing is processing them. Check, in order:

1. The worker is running: `docker compose ps` (the `worker` service should be running) and `docker compose logs worker --tail 30`. Without Docker, start it with `uv run python -m order_api.worker`.
2. No pause file is left over from an earlier run: `ls -la worker_control/ .worker_paused`, then `rm -f worker_control/paused .worker_paused`.
3. The worker uses the same database as the API (`DATABASE_URL`), not the test database.

Orders left in `RECEIVED` are processed as soon as a working worker starts.

**`service "db" refers to undefined volume postgres_data: invalid compose project`**

`docker-compose.yml` must declare the volume at the top level, at the end of the file:

```yaml
volumes:
  postgres_data:
```

Verify with `docker compose config --quiet`.

## Scope

The implementation covers order creation and retrieval, product stock lookup, asynchronous stock processing with recovery after interruption, and a daily report endpoint.

See [SOLUTION.md](SOLUTION.md) for the selected behaviour, trade-offs and known limitations.
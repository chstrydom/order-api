# Order API

A Python REST API for order intake, idempotent order creation, stock processing, and daily reporting, backed by PostgreSQL.

Design decisions, assumptions, and trade-offs are documented in [SOLUTION.md](SOLUTION.md). AI assistance is documented in [AI_USAGE.md](AI_USAGE.md).

## Requirements

- Python 3.14
- Docker Engine or Docker Desktop with Docker Compose
- `uv` for Python dependency and environment management

## Configuration

Copy `.env.example` to `.env` and configure the database connection.

Do not commit `.env` or other files containing credentials.

## Run locally

The application and database setup is still under development. The commands below will be finalised once the Docker Compose configuration and application entry point are implemented.

```bash
docker compose up -d
uv sync
```

## API documentation

Once the application is running, interactive API documentation will be available at:

`http://localhost:8000/docs`

## Tests

Run the test suite from the project root:

```bash
uv run pytest
```

### Test database

Tests use a separate PostgreSQL database (`order_api_test`) configured through `TEST_DATABASE_URL` in `.env`.

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

When a clean database is required, the test database can be dropped and recreated:

```bash
docker compose exec db psql -U order_api -d postgres -c "DROP DATABASE order_api_test WITH (FORCE);"
docker compose exec db psql -U order_api -d postgres -c "CREATE DATABASE order_api_test;"
```

**Warning:** Resetting the test database permanently deletes its contents. Never run these commands against the development or production database.

Database-dependent tests require PostgreSQL to be running and configured.

## Scope

The implementation covers order creation and retrieval, product stock lookup, asynchronous stock processing with recovery after interruption, and a daily report endpoint.

See [SOLUTION.md](SOLUTION.md) for the selected behaviour and remaining assumptions.
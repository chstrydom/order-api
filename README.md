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

```bash
uv run pytest
```

Database-dependent tests require PostgreSQL to be running and configured.

## Scope

The implementation covers order creation and retrieval, product stock lookup, asynchronous stock processing with recovery after interruption, and a daily report endpoint.

See [SOLUTION.md](SOLUTION.md) for the selected behaviour and remaining assumptions.
import os

import psycopg
import pytest
from dotenv import load_dotenv

from order_api.db import initialise_database


@pytest.fixture(scope="session", autouse=True)
def load_environment():
    load_dotenv(override=False)
    test_url = os.environ["TEST_DATABASE_URL"]
    os.environ["DATABASE_URL"] = test_url

    # Safety guard: every test truncates tables, so only ever run on a test DB.
    database_name = psycopg.conninfo.conninfo_to_dict(test_url)["dbname"]
    assert database_name.endswith("_test"), (
        f"Refusing to run tests against non-test database '{database_name}'."
    )

    initialise_database(test_url)


@pytest.fixture(autouse=True)
def clean_database(load_environment):
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("TRUNCATE order_lines, orders, products")


@pytest.fixture
def test_product():
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            """
            INSERT INTO products (sku, name, price_cents, stock)
            VALUES (%s, %s, %s, %s)
            """,
            ("TEST-001", "Test Product", 199, 10),
        )


@pytest.fixture
def order_submission(test_product):
    return {
        "order_ref": "API-TEST-001",
        "customer_id": "CUSTOMER-001",
        "items": [{"sku": "TEST-001", "qty": 2}],
    }


@pytest.fixture
def database_url():
    """The test database URL. Does not change any data."""
    return os.environ["DATABASE_URL"]


@pytest.fixture
def order_products(database_url):
    """Seed two products used by the order repository tests."""
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO products (sku, name, price_cents, stock)
            VALUES (%s, %s, %s, %s)
            """,
            [
                ("order-sku-1", "Product 1", 1000, 10),
                ("order-sku-2", "Product 2", 2500, 5),
            ],
        )

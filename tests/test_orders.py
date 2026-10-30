from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from order_api.orders.exceptions import (
    InvalidOrderError,
    OrderConflictError,
    UnknownProductError,
)
from order_api.orders.repository import create_order

pytestmark = pytest.mark.usefixtures("order_products")


def test_create_order_persists_order_and_price_snapshots(database_url):
    order = create_order(
        database_url,
        "ORD-CREATE-001",
        "CUST-001",
        [
            {"sku": "order-sku-1", "qty": 2},
            {"sku": "order-sku-2", "qty": 1},
        ],
    )

    assert order["total_cents"] == 4500
    assert order["status"] == "RECEIVED"
    assert order["items"] == [
        {"sku": "order-sku-1", "qty": 2, "price_cents": 1000},
        {"sku": "order-sku-2", "qty": 1, "price_cents": 2500},
    ]


def test_identical_submission_returns_existing_order(database_url):
    first = create_order(
        database_url,
        "ORD-DUPLICATE-001",
        "CUST-001",
        [
            {"sku": "order-sku-1", "qty": 1},
            {"sku": "order-sku-2", "qty": 1},
        ],
    )

    retry = create_order(
        database_url,
        "ORD-DUPLICATE-001",
        "CUST-001",
        [
            {"sku": "order-sku-2", "qty": 1},
            {"sku": "order-sku-1", "qty": 1},
        ],
    )

    assert retry == first


def test_duplicate_skus_are_consolidated(database_url):
    order = create_order(
        database_url,
        "ORD-CONSOLIDATE-001",
        "CUST-001",
        [
            {"sku": "order-sku-1", "qty": 1},
            {"sku": "order-sku-1", "qty": 2},
        ],
    )

    assert order["total_cents"] == 3000
    assert order["items"] == [
        {"sku": "order-sku-1", "qty": 3, "price_cents": 1000},
    ]


def test_different_submission_with_same_reference_conflicts(database_url):
    create_order(
        database_url,
        "ORD-CONFLICT-001",
        "CUST-001",
        [{"sku": "order-sku-1", "qty": 1}],
    )

    with pytest.raises(OrderConflictError):
        create_order(
            database_url,
            "ORD-CONFLICT-001",
            "CUST-001",
            [{"sku": "order-sku-1", "qty": 2}],
        )


def test_unknown_product_does_not_persist_order(database_url):
    with pytest.raises(UnknownProductError):
        create_order(
            database_url,
            "ORD-UNKNOWN-001",
            "CUST-001",
            [{"sku": "unknown-sku", "qty": 1}],
        )

    with psycopg.connect(database_url) as connection:
        result = connection.execute(
            "SELECT order_ref FROM orders WHERE order_ref = %s",
            ("ORD-UNKNOWN-001",),
        ).fetchone()

    assert result is None


def test_retry_preserves_original_price_snapshot(database_url):
    first = create_order(
        database_url,
        "ORD-PRICE-001",
        "CUST-001",
        [{"sku": "order-sku-1", "qty": 2}],
    )

    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            UPDATE products
            SET price_cents = 2000
            WHERE sku = %s
            """,
            ("order-sku-1",),
        )

    retry = create_order(
        database_url,
        "ORD-PRICE-001",
        "CUST-001",
        [{"sku": "order-sku-1", "qty": 2}],
    )

    assert first["total_cents"] == 2000
    assert retry["total_cents"] == 2000
    assert retry["items"][0]["price_cents"] == 1000


def test_order_intake_does_not_deduct_stock(database_url):
    create_order(
        database_url,
        "ORD-NO-STOCK-001",
        "CUST-001",
        [{"sku": "order-sku-1", "qty": 3}],
    )

    with psycopg.connect(database_url) as connection:
        stock = connection.execute(
            "SELECT stock FROM products WHERE sku = %s",
            ("order-sku-1",),
        ).fetchone()[0]

    assert stock == 10


def test_order_with_unknown_sku_does_not_persist_partial_lines(database_url):
    with pytest.raises(UnknownProductError):
        create_order(
            database_url,
            "ORD-PARTIAL-001",
            "CUST-001",
            [
                {"sku": "order-sku-1", "qty": 1},
                {"sku": "unknown-sku", "qty": 1},
            ],
        )

    with psycopg.connect(database_url) as connection:
        result = connection.execute(
            "SELECT COUNT(*) FROM orders WHERE order_ref = %s",
            ("ORD-PARTIAL-001",),
        ).fetchone()[0]

    assert result == 0


def test_concurrent_identical_submissions_create_one_order(database_url):
    def submit(_):
        return create_order(
            database_url,
            "ORD-CONCURRENT-001",
            "CUST-001",
            [{"sku": "order-sku-1", "qty": 1}],
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(8)))

    assert all(result == results[0] for result in results)

    with psycopg.connect(database_url) as connection:
        orders = connection.execute(
            "SELECT COUNT(*) FROM orders WHERE order_ref = %s",
            ("ORD-CONCURRENT-001",),
        ).fetchone()[0]
        lines = connection.execute(
            "SELECT COUNT(*) FROM order_lines WHERE order_ref = %s",
            ("ORD-CONCURRENT-001",),
        ).fetchone()[0]

    assert (orders, lines) == (1, 1)


def test_concurrent_conflicting_submissions_have_one_winner(database_url):
    def submit(qty):
        try:
            create_order(
                database_url,
                "ORD-CONCURRENT-002",
                "CUST-001",
                [{"sku": "order-sku-1", "qty": qty}],
            )
        except OrderConflictError:
            return "conflict"
        return "ok"

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(submit, [1, 2, 3, 4]))

    assert outcomes.count("ok") == 1
    assert outcomes.count("conflict") == 3


def test_items_are_returned_in_sku_order_not_submission_order(database_url):
    order = create_order(
        database_url,
        "ORD-SORTED-001",
        "CUST-001",
        [
            {"sku": "order-sku-2", "qty": 1},
            {"sku": "order-sku-1", "qty": 1},
        ],
    )

    assert [item["sku"] for item in order["items"]] == ["order-sku-1", "order-sku-2"]


def test_consolidated_quantity_over_limit_is_rejected(database_url):
    with pytest.raises(InvalidOrderError):
        create_order(
            database_url,
            "ORD-LIMIT-001",
            "CUST-001",
            [
                {"sku": "order-sku-1", "qty": 600_000},
                {"sku": "order-sku-1", "qty": 600_000},
            ],
        )

    with psycopg.connect(database_url) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM orders WHERE order_ref = %s",
            ("ORD-LIMIT-001",),
        ).fetchone()[0]

    assert count == 0

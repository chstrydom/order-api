from datetime import UTC, date, datetime

import psycopg
import pytest

from order_api.reports.repository import get_daily_report

pytestmark = pytest.mark.usefixtures("order_products")

# order-sku-1: 1000 cents, order-sku-2: 2500 cents (see conftest.order_products)
PRICES = {"order-sku-1": 1000, "order-sku-2": 2500}


def _insert_order(database_url, order_ref, status, created_at, lines):
    total = sum(qty * PRICES[sku] for sku, qty in lines)
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO orders (order_ref, customer_id, total_cents, created_at, status)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (order_ref, "CUST-001", total, created_at, status),
        )
        cursor.executemany(
            """
            INSERT INTO order_lines (order_ref, sku, qty, price_cents)
            VALUES (%s, %s, %s, %s)
            """,
            [(order_ref, sku, qty, PRICES[sku]) for sku, qty in lines],
        )


def _utc(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


REPORT_DAY = date(2026, 10, 30)
# 2026-10-30 00:00 in Africa/Johannesburg (UTC+2) is 2026-10-29 22:00 UTC.
NOON = _utc(2026, 10, 30, 10, 0)


def test_empty_day_reports_zeros_and_lists_every_product(database_url):
    report = get_daily_report(database_url, REPORT_DAY)

    assert report["date"] == "2026-10-30"
    assert report["timezone"] == "Africa/Johannesburg"
    assert report["orders_total"] == 0
    assert report["orders_by_status"] == {"RECEIVED": 0, "PROCESSED": 0, "REJECTED": 0}
    assert report["revenue_cents"] == 0
    assert report["skus"] == [
        {
            "sku": "order-sku-1",
            "units_sold": 0,
            "revenue_cents": 0,
            "current_stock": 10,
        },
        {"sku": "order-sku-2", "units_sold": 0, "revenue_cents": 0, "current_stock": 5},
    ]


def test_counts_every_status_but_revenue_only_from_processed(database_url):
    _insert_order(database_url, "R-1", "PROCESSED", NOON, [("order-sku-1", 2)])
    _insert_order(
        database_url,
        "R-2",
        "PROCESSED",
        NOON,
        [("order-sku-1", 1), ("order-sku-2", 1)],
    )
    _insert_order(database_url, "R-3", "REJECTED", NOON, [("order-sku-1", 50)])
    _insert_order(database_url, "R-4", "RECEIVED", NOON, [("order-sku-2", 4)])

    report = get_daily_report(database_url, REPORT_DAY)

    assert report["orders_total"] == 4
    assert report["orders_by_status"] == {"RECEIVED": 1, "PROCESSED": 2, "REJECTED": 1}
    assert report["revenue_cents"] == 3 * 1000 + 1 * 2500
    assert report["skus"] == [
        {
            "sku": "order-sku-1",
            "units_sold": 3,
            "revenue_cents": 3000,
            "current_stock": 10,
        },
        {
            "sku": "order-sku-2",
            "units_sold": 1,
            "revenue_cents": 2500,
            "current_stock": 5,
        },
    ]


def test_revenue_uses_stored_line_prices_not_current_prices(database_url):
    _insert_order(database_url, "R-PRICE", "PROCESSED", NOON, [("order-sku-1", 2)])
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "UPDATE products SET price_cents = 9999 WHERE sku = 'order-sku-1'"
        )

    report = get_daily_report(database_url, REPORT_DAY)

    assert report["revenue_cents"] == 2000


def test_day_boundaries_use_the_report_timezone(database_url):
    # Local (SAST, UTC+2) times around midnight between 29 and 30 October.
    _insert_order(  # 29th 23:59:59 local
        database_url,
        "B-BEFORE",
        "PROCESSED",
        _utc(2026, 10, 29, 21, 59, 59),
        [("order-sku-1", 1)],
    )
    _insert_order(  # 30th 00:00:00 local (start of the day: included)
        database_url,
        "B-START",
        "PROCESSED",
        _utc(2026, 10, 29, 22, 0, 0),
        [("order-sku-1", 1)],
    )
    _insert_order(  # 30th 23:59:59 local (last second: included)
        database_url,
        "B-END",
        "PROCESSED",
        _utc(2026, 10, 30, 21, 59, 59),
        [("order-sku-1", 1)],
    )
    _insert_order(  # 31st 00:00:00 local (next day: excluded)
        database_url,
        "B-AFTER",
        "PROCESSED",
        _utc(2026, 10, 30, 22, 0, 0),
        [("order-sku-1", 1)],
    )

    report = get_daily_report(database_url, REPORT_DAY)

    assert report["orders_total"] == 2
    assert report["skus"][0]["units_sold"] == 2


def test_current_stock_is_live_not_historical(database_url):
    with psycopg.connect(database_url) as connection:
        connection.execute("UPDATE products SET stock = 3 WHERE sku = 'order-sku-2'")

    report = get_daily_report(database_url, REPORT_DAY)

    assert report["skus"][1]["current_stock"] == 3

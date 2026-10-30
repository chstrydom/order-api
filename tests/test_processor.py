from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from order_api.orders.repository import create_order
from order_api.worker import processor
from order_api.worker.processor import process_one_order

pytestmark = pytest.mark.usefixtures("order_products")


def _submit(database_url, order_ref, items):
    return create_order(database_url, order_ref, "CUST-001", items)


def _status(database_url, order_ref):
    with psycopg.connect(database_url) as connection:
        return connection.execute(
            "SELECT status FROM orders WHERE order_ref = %s",
            (order_ref,),
        ).fetchone()[0]


def _stock(database_url, sku):
    with psycopg.connect(database_url) as connection:
        return connection.execute(
            "SELECT stock FROM products WHERE sku = %s",
            (sku,),
        ).fetchone()[0]


def test_returns_false_when_no_order_is_pending(database_url):
    assert process_one_order(database_url) is False


def test_sufficient_stock_is_processed_and_deducted(database_url):
    _submit(database_url, "ORD-OK-001", [{"sku": "order-sku-1", "qty": 3}])

    assert process_one_order(database_url) is True

    assert _status(database_url, "ORD-OK-001") == "PROCESSED"
    assert _stock(database_url, "order-sku-1") == 7


def test_order_for_exactly_the_available_stock_is_processed(database_url):
    _submit(database_url, "ORD-EXACT-001", [{"sku": "order-sku-2", "qty": 5}])

    assert process_one_order(database_url) is True

    assert _status(database_url, "ORD-EXACT-001") == "PROCESSED"
    assert _stock(database_url, "order-sku-2") == 0


def test_insufficient_stock_is_rejected_and_stock_unchanged(database_url):
    _submit(database_url, "ORD-REJECT-001", [{"sku": "order-sku-1", "qty": 11}])

    assert process_one_order(database_url) is True

    assert _status(database_url, "ORD-REJECT-001") == "REJECTED"
    assert _stock(database_url, "order-sku-1") == 10


def test_one_insufficient_line_causes_no_partial_deduction(database_url):
    _submit(
        database_url,
        "ORD-PARTIAL-001",
        [
            {"sku": "order-sku-1", "qty": 2},  # available
            {"sku": "order-sku-2", "qty": 6},  # only 5 in stock
        ],
    )

    assert process_one_order(database_url) is True

    assert _status(database_url, "ORD-PARTIAL-001") == "REJECTED"
    assert _stock(database_url, "order-sku-1") == 10
    assert _stock(database_url, "order-sku-2") == 5


def test_processed_order_is_not_processed_twice(database_url):
    _submit(database_url, "ORD-TWICE-001", [{"sku": "order-sku-1", "qty": 3}])

    assert process_one_order(database_url) is True
    assert process_one_order(database_url) is False

    assert _status(database_url, "ORD-TWICE-001") == "PROCESSED"
    assert _stock(database_url, "order-sku-1") == 7


def test_rejected_order_is_not_retried(database_url):
    _submit(database_url, "ORD-NORETRY-001", [{"sku": "order-sku-1", "qty": 11}])

    assert process_one_order(database_url) is True
    assert process_one_order(database_url) is False
    assert _status(database_url, "ORD-NORETRY-001") == "REJECTED"


def test_oldest_order_is_processed_first(database_url):
    _submit(database_url, "ORD-OLD-001", [{"sku": "order-sku-1", "qty": 1}])
    _submit(database_url, "ORD-NEW-001", [{"sku": "order-sku-1", "qty": 1}])

    assert process_one_order(database_url) is True

    assert _status(database_url, "ORD-OLD-001") == "PROCESSED"
    assert _status(database_url, "ORD-NEW-001") == "RECEIVED"


def test_failure_rolls_back_stock_and_status(database_url, monkeypatch):
    _submit(
        database_url,
        "ORD-ROLLBACK-001",
        [
            {"sku": "order-sku-1", "qty": 3},
            {"sku": "order-sku-2", "qty": 2},
        ],
    )

    def fail(*args, **kwargs):
        raise RuntimeError("boom")

    # Stock is deducted first, then the status update fails.
    monkeypatch.setattr(processor, "_set_status", fail)

    with pytest.raises(RuntimeError, match="boom"):
        process_one_order(database_url)

    assert _status(database_url, "ORD-ROLLBACK-001") == "RECEIVED"
    assert _stock(database_url, "order-sku-1") == 10
    assert _stock(database_url, "order-sku-2") == 5

    # A retry after the failure applies the deduction exactly once.
    monkeypatch.undo()
    assert process_one_order(database_url) is True
    assert _status(database_url, "ORD-ROLLBACK-001") == "PROCESSED"
    assert _stock(database_url, "order-sku-1") == 7
    assert _stock(database_url, "order-sku-2") == 3


def test_concurrent_workers_process_a_single_order_once(database_url):
    _submit(database_url, "ORD-CONCURRENT-001", [{"sku": "order-sku-1", "qty": 3}])

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: process_one_order(database_url), range(6)))

    assert results.count(True) == 1
    assert _status(database_url, "ORD-CONCURRENT-001") == "PROCESSED"
    assert _stock(database_url, "order-sku-1") == 7


def test_concurrent_workers_do_not_oversell_limited_stock(database_url):
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "UPDATE products SET stock = 1 WHERE sku = %s",
            ("order-sku-1",),
        )

    order_refs = [f"ORD-RACE-{i:03d}" for i in range(6)]
    for order_ref in order_refs:
        _submit(database_url, order_ref, [{"sku": "order-sku-1", "qty": 1}])

    def drain(_):
        handled = 0
        while process_one_order(database_url):
            handled += 1
        return handled

    with ThreadPoolExecutor(max_workers=4) as pool:
        handled_counts = list(pool.map(drain, range(4)))

    statuses = [_status(database_url, order_ref) for order_ref in order_refs]

    assert sum(handled_counts) == 6
    assert statuses.count("PROCESSED") == 1
    assert statuses.count("REJECTED") == 5
    assert _stock(database_url, "order-sku-1") == 0

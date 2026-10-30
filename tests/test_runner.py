import threading
import time

import psycopg
import pytest

from order_api.orders.repository import create_order
from order_api.worker import runner
from order_api.worker.runner import run_worker

pytestmark = pytest.mark.usefixtures("order_products")

POLL_INTERVAL = 0.05


def _submit(database_url, order_ref, qty=1):
    create_order(
        database_url,
        order_ref,
        "CUST-001",
        [{"sku": "order-sku-1", "qty": qty}],
    )


def _statuses(database_url):
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            "SELECT order_ref, status FROM orders ORDER BY order_ref"
        ).fetchall()
    return dict(rows)


def _wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def start_worker(database_url, tmp_path):
    """Run the worker in a background thread; always stop it afterwards."""
    sentinel = tmp_path / "paused"
    stop_event = threading.Event()
    result = {}

    def target():
        result["handled"] = run_worker(
            database_url,
            poll_interval=POLL_INTERVAL,
            pause_sentinel=sentinel,
            stop_event=stop_event,
        )

    thread = threading.Thread(target=target, daemon=True)

    def start():
        thread.start()
        return sentinel, stop_event, thread, result

    yield start

    stop_event.set()
    if thread.is_alive():
        thread.join(timeout=5)


def test_worker_processes_a_backlog_and_then_stops(database_url, start_worker):
    for i in range(5):
        _submit(database_url, f"ORD-BACKLOG-{i}")

    _, stop_event, thread, result = start_worker()

    assert _wait_until(lambda: set(_statuses(database_url).values()) == {"PROCESSED"})

    stop_event.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert result["handled"] == 5


def test_worker_picks_up_orders_that_arrive_while_idle(database_url, start_worker):
    _, _, _, _ = start_worker()
    time.sleep(0.2)  # worker is idle and polling

    _submit(database_url, "ORD-LATE-001")

    assert _wait_until(
        lambda: _statuses(database_url).get("ORD-LATE-001") == "PROCESSED"
    )


def test_pause_sentinel_holds_orders_until_it_is_removed(database_url, start_worker):
    sentinel, _, _, _ = start_worker()
    sentinel.touch()

    for i in range(3):
        _submit(database_url, f"ORD-PAUSED-{i}")

    time.sleep(0.4)  # several poll cycles
    assert set(_statuses(database_url).values()) == {"RECEIVED"}

    sentinel.unlink()

    assert _wait_until(lambda: set(_statuses(database_url).values()) == {"PROCESSED"})


def test_stop_event_ends_the_loop_promptly(database_url, start_worker):
    _, stop_event, thread, _ = start_worker()
    time.sleep(0.1)

    stop_event.set()
    thread.join(timeout=2)

    assert not thread.is_alive()


def test_worker_survives_a_database_error_and_retries(
    database_url, start_worker, monkeypatch
):
    _submit(database_url, "ORD-RETRY-001")

    real_process = runner.process_one_order
    calls = {"n": 0}

    def flaky(url):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise psycopg.OperationalError("database unavailable")
        return real_process(url)

    monkeypatch.setattr(runner, "process_one_order", flaky)

    _, _, thread, _ = start_worker()

    assert _wait_until(
        lambda: _statuses(database_url).get("ORD-RETRY-001") == "PROCESSED"
    )
    assert thread.is_alive()
    assert calls["n"] >= 3

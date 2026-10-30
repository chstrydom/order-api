import logging
import os
import signal
import threading
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from order_api.worker.processor import process_one_order

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_PAUSE_SENTINEL = ".worker_paused"


def run_worker(
    database_url: str,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    pause_sentinel: str | Path = DEFAULT_PAUSE_SENTINEL,
    stop_event: threading.Event | None = None,
) -> int:
    """Process outstanding orders until `stop_event` is set.

    While orders are available the worker processes them back to back; when
    there are none (or processing is paused or the database is unavailable) it
    waits `poll_interval` seconds. Setting `stop_event` ends the loop after
    the order currently being processed has been committed.

    Returns the number of orders handled (processed or rejected).
    """
    stop_event = stop_event or threading.Event()
    sentinel = Path(pause_sentinel)
    handled = 0

    while not stop_event.is_set():
        # Demonstration hook: orders keep being accepted but not processed.
        if sentinel.exists():
            stop_event.wait(poll_interval)
            continue

        try:
            processed = process_one_order(database_url)
        except psycopg.Error:
            # The failed transaction rolled back, so the order stays RECEIVED
            # and will be picked up again.
            logger.exception("Order processing failed; retrying shortly")
            stop_event.wait(poll_interval)
            continue

        if processed:
            handled += 1
        else:
            stop_event.wait(poll_interval)

    return handled


def main() -> None:
    load_dotenv(override=False)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    database_url = os.environ["DATABASE_URL"]
    poll_interval = float(os.environ.get("WORKER_POLL_INTERVAL", DEFAULT_POLL_INTERVAL))
    pause_sentinel = os.environ.get("WORKER_PAUSE_SENTINEL", DEFAULT_PAUSE_SENTINEL)

    stop_event = threading.Event()

    def request_stop(signum, _frame):
        logger.info("Received signal %s; finishing current order and stopping", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    logger.info(
        "Worker started (poll interval %.2fs, pause sentinel %s)",
        poll_interval,
        pause_sentinel,
    )
    handled = run_worker(database_url, poll_interval, pause_sentinel, stop_event)
    logger.info("Worker stopped after handling %d order(s)", handled)

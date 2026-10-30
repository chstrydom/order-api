#!/usr/bin/env python3
"""Seed demo products and demonstrate order idempotency and worker recovery.

Run from the repository root:

    uv run python scripts/seed_and_burst.py --skip-interruption

Once the stock worker supports the pause sentinel:

    uv run python scripts/seed_and_burst.py

Each run creates uniquely named demo products and orders. Existing data is
never overwritten or deleted.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_SENTINEL = Path(".worker_paused")

PRODUCT_TEMPLATES = [
    {"key": "BAN", "name": "Bananas 1kg", "price_cents": 199, "stock": 50},
    {"key": "APL", "name": "Apples 1kg", "price_cents": 249, "stock": 30},
    {"key": "MLK", "name": "Milk 1L", "price_cents": 189, "stock": 20},
]


@dataclass
class BurstResult:
    submitted: int
    accepted_new: int
    accepted_duplicate: int
    conflicts: int
    unexpected: int
    order_refs: list[str]


def build_products(run_id: str) -> list[dict]:
    """Create unique product SKUs for this demonstration run."""
    return [
        {
            "sku": f"DEMO-{run_id}-{product['key']}",
            "name": f"{product['name']} (demo {run_id})",
            "price_cents": product["price_cents"],
            "stock": product["stock"],
        }
        for product in PRODUCT_TEMPLATES
    ]


def order_reference(run_id: str, suffix: str) -> str:
    return f"web-{run_id}-{suffix}"


# --- API helpers -----------------------------------------------------------


def submit_order(client: httpx.Client, payload: dict) -> httpx.Response:
    return client.post("/orders", json=payload)


def get_stock(client: httpx.Client, sku: str) -> int:
    response = client.get(f"/products/{sku}")
    response.raise_for_status()
    return response.json()["stock"]


def get_order(client: httpx.Client, order_ref: str) -> dict | None:
    response = client.get(f"/orders/{order_ref}")

    if response.status_code == 404:
        return None

    response.raise_for_status()
    return response.json()


def wait_for_processed_orders(
    client: httpx.Client,
    order_refs: list[str],
    timeout_seconds: float,
) -> None:
    """Wait until every specified order reaches PROCESSED."""
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        statuses = {
            ref: (get_order(client, ref) or {}).get("status") for ref in order_refs
        }

        rejected = [ref for ref, status in statuses.items() if status == "REJECTED"]
        if rejected:
            raise RuntimeError(f"Orders unexpectedly rejected: {rejected}")

        if all(status == "PROCESSED" for status in statuses.values()):
            return

        time.sleep(0.5)

    raise RuntimeError(
        f"Orders did not all reach PROCESSED within {timeout_seconds}s. "
        f"Last statuses: {statuses}"
    )


# --- Product seeding -------------------------------------------------------


def seed_products(database_url: str, products: list[dict]) -> None:
    """Insert fresh demo products without modifying existing inventory."""
    import psycopg

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.executemany(
            """
                INSERT INTO products (sku, name, price_cents, stock)
                VALUES (%(sku)s, %(name)s, %(price_cents)s, %(stock)s)
                """,
            products,
        )

    print(f"[seed] inserted {len(products)} demo products")


# --- Duplicate-submission demonstration -----------------------------------


def run_duplicate_burst(
    client: httpx.Client,
    run_id: str,
    products: list[dict],
) -> BurstResult:
    """Submit three orders twice each, including one reordered duplicate."""

    bananas, apples, milk = [product["sku"] for product in products]

    submissions = [
        {
            "order_ref": order_reference(run_id, "100045"),
            "customer_id": "cust-42",
            "items": [
                {"sku": bananas, "qty": 2},
                {"sku": apples, "qty": 1},
            ],
        },
        {
            "order_ref": order_reference(run_id, "100045"),
            "customer_id": "cust-42",
            "items": [
                {"sku": apples, "qty": 1},
                {"sku": bananas, "qty": 2},
            ],
        },
        {
            "order_ref": order_reference(run_id, "100046"),
            "customer_id": "cust-43",
            "items": [{"sku": milk, "qty": 1}],
        },
        {
            "order_ref": order_reference(run_id, "100046"),
            "customer_id": "cust-43",
            "items": [{"sku": milk, "qty": 1}],
        },
        {
            "order_ref": order_reference(run_id, "100047"),
            "customer_id": "cust-44",
            "items": [{"sku": bananas, "qty": 5}],
        },
        {
            "order_ref": order_reference(run_id, "100047"),
            "customer_id": "cust-44",
            "items": [{"sku": bananas, "qty": 5}],
        },
    ]

    seen_refs: set[str] = set()
    accepted_new = 0
    accepted_duplicate = 0
    conflicts = 0
    unexpected = 0

    for payload in submissions:
        ref = payload["order_ref"]
        is_duplicate = ref in seen_refs
        seen_refs.add(ref)

        response = submit_order(client, payload)

        if response.status_code == 202:
            if is_duplicate:
                accepted_duplicate += 1
            else:
                accepted_new += 1
        elif response.status_code == 409:
            conflicts += 1
            print(f"[burst/duplicates] unexpected conflict for {ref}")
        else:
            unexpected += 1
            print(
                f"[burst/duplicates] unexpected response for {ref}: "
                f"{response.status_code} {response.text}"
            )

    result = BurstResult(
        submitted=len(submissions),
        accepted_new=accepted_new,
        accepted_duplicate=accepted_duplicate,
        conflicts=conflicts,
        unexpected=unexpected,
        order_refs=sorted(seen_refs),
    )

    print(
        f"[burst/duplicates] submitted={result.submitted} "
        f"new_accepted={result.accepted_new} "
        f"duplicate_accepted={result.accepted_duplicate} "
        f"conflicts={result.conflicts} "
        f"unexpected={result.unexpected}"
    )

    return result


def assert_duplicate_handling(
    client: httpx.Client,
    result: BurstResult,
) -> None:
    errors: list[str] = []

    if result.accepted_new != 3:
        errors.append(f"expected 3 new accepted orders, got {result.accepted_new}")

    if result.accepted_duplicate != 3:
        errors.append(
            f"expected 3 accepted duplicate submissions, "
            f"got {result.accepted_duplicate}"
        )

    if result.conflicts != 0:
        errors.append(f"expected no conflicts, got {result.conflicts}")

    if result.unexpected != 0:
        errors.append(f"unexpected HTTP responses: {result.unexpected}")

    for ref in result.order_refs:
        order = get_order(client, ref)

        if order is None:
            errors.append(f"order {ref} could not be retrieved")

    if errors:
        raise RuntimeError(
            "Duplicate demonstration failed:\n  - " + "\n  - ".join(errors)
        )

    print(
        "[burst/duplicates] OK: three unique orders persisted; "
        "three retries returned the existing orders"
    )


# --- Worker pause/resume demonstration ------------------------------------


def pause_worker(sentinel: Path) -> None:
    """Create the pause sentinel, refusing to overwrite an existing one."""
    if sentinel.exists():
        raise RuntimeError(
            f"Pause sentinel already exists: {sentinel}. "
            "Check whether the worker is already paused."
        )

    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("paused", encoding="utf-8")
    print(f"[pause] created {sentinel}")


def resume_worker(sentinel: Path) -> None:
    sentinel.unlink(missing_ok=True)
    print(f"[resume] removed {sentinel}")


def run_interruption_phase(
    client: httpx.Client,
    sentinel: Path,
    run_id: str,
    products: list[dict],
    settle_seconds: float,
) -> None:
    """Verify that orders survive a worker pause and process after recovery."""

    bananas, apples, _milk = [product["sku"] for product in products]

    during = [
        {
            "order_ref": order_reference(run_id, "100050"),
            "customer_id": "cust-50",
            "items": [{"sku": bananas, "qty": 3}],
        },
        {
            "order_ref": order_reference(run_id, "100051"),
            "customer_id": "cust-51",
            "items": [{"sku": apples, "qty": 2}],
        },
    ]

    refs = [payload["order_ref"] for payload in during]

    pause_worker(sentinel)

    try:
        before = {
            product["sku"]: get_stock(client, product["sku"]) for product in products
        }

        for payload in during:
            response = submit_order(client, payload)

            if response.status_code != 202:
                raise RuntimeError(
                    f"Order {payload['order_ref']} was not accepted: "
                    f"{response.status_code} {response.text}"
                )

        # Confirm the orders are persisted and remain pending.
        for ref in refs:
            order = get_order(client, ref)

            if order is None:
                raise RuntimeError(f"Order {ref} was not persisted")

            if order["status"] != "RECEIVED":
                raise RuntimeError(
                    f"Expected {ref} to remain RECEIVED while paused; "
                    f"got {order['status']}"
                )

        still = {
            product["sku"]: get_stock(client, product["sku"]) for product in products
        }

        print(f"[interruption] stock before pause={before}")
        print(f"[interruption] stock during pause={still}")

        if still != before:
            raise RuntimeError("Stock changed while the worker was paused")

    finally:
        # Always release the worker, even if a check or HTTP request fails.
        resume_worker(sentinel)

    expected = dict(before)
    expected[bananas] -= 3
    expected[apples] -= 2

    deadline = time.monotonic() + settle_seconds
    last_stock = None
    last_statuses = {}

    while time.monotonic() < deadline:
        last_statuses = {
            ref: (get_order(client, ref) or {}).get("status") for ref in refs
        }

        rejected = [
            ref for ref, status in last_statuses.items() if status == "REJECTED"
        ]

        if rejected:
            raise RuntimeError(f"Orders unexpectedly rejected after resume: {rejected}")

        last_stock = {
            product["sku"]: get_stock(client, product["sku"]) for product in products
        }

        if (
            all(status == "PROCESSED" for status in last_statuses.values())
            and last_stock == expected
        ):
            print(f"[interruption] stock after resume={last_stock}")
            print("[interruption] OK: pending orders processed after recovery")
            return

        time.sleep(0.5)

    raise RuntimeError(
        "Worker did not catch up within "
        f"{settle_seconds}s. "
        f"Statuses={last_statuses}; stock={last_stock}; expected={expected}"
    )


# --- CLI -------------------------------------------------------------------


def main() -> int:
    load_dotenv(override=False)

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--api-url",
        default=os.environ.get("API_URL", DEFAULT_API_URL),
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Database used for demo product seeding; defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--sentinel",
        type=Path,
        default=Path(os.environ.get("WORKER_PAUSE_SENTINEL", str(DEFAULT_SENTINEL))),
        help="Pause sentinel path shared with the worker.",
    )
    parser.add_argument(
        "--skip-interruption",
        action="store_true",
        help="Skip the pause/resume demonstration until the worker exists.",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=15.0,
        help="Maximum time to wait for worker processing.",
    )

    args = parser.parse_args()

    if not args.database_url:
        parser.error("DATABASE_URL or --database-url is required")

    if args.settle_seconds <= 0:
        parser.error("--settle-seconds must be greater than zero")

    run_id = uuid.uuid4().hex[:8]
    products = build_products(run_id)

    try:
        with httpx.Client(base_url=args.api_url, timeout=5.0) as client:
            client.get("/health").raise_for_status()

            print(f"[run] ID: {run_id}")

            seed_products(args.database_url, products)

            result = run_duplicate_burst(client, run_id, products)
            assert_duplicate_handling(client, result)

            if args.skip_interruption:
                print("[interruption] SKIPPED (--skip-interruption)")
            else:
                # Avoid taking the stock baseline while earlier demo orders
                # are still being processed.
                wait_for_processed_orders(
                    client,
                    result.order_refs,
                    args.settle_seconds,
                )

                run_interruption_phase(
                    client,
                    args.sentinel,
                    run_id,
                    products,
                    args.settle_seconds,
                )

        print("\nAll requested phases OK.")
        return 0

    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

import psycopg

from order_api.orders.exceptions import (
    InvalidOrderError,
    OrderConflictError,
    UnknownProductError,
)
from order_api.orders.schemas import MAX_QTY


def _normalise_items(items: list[dict]) -> dict[str, int]:
    """Combine duplicate SKUs. The result is sorted by SKU, so order lines (and
    the `items` in responses) are always returned in SKU order, not submission
    order."""
    quantities: dict[str, int] = {}

    for item in items:
        sku = item["sku"]
        quantities[sku] = quantities.get(sku, 0) + item["qty"]

    return dict(sorted(quantities.items()))


def _get_existing_order(cursor: psycopg.Cursor, order_ref: str) -> dict | None:
    cursor.execute(
        """
        SELECT order_ref, customer_id, total_cents, status
        FROM orders
        WHERE order_ref = %s
        """,
        (order_ref,),
    )
    order = cursor.fetchone()

    if order is None:
        return None

    cursor.execute(
        """
        SELECT sku, qty, price_cents
        FROM order_lines
        WHERE order_ref = %s
        ORDER BY sku
        """,
        (order_ref,),
    )

    lines = cursor.fetchall()

    return {
        "order_ref": order[0],
        "customer_id": order[1],
        "total_cents": order[2],
        "status": order[3],
        "items": [
            {
                "sku": line[0],
                "qty": line[1],
                "price_cents": line[2],
            }
            for line in lines
        ],
    }


def _is_same_submission(
    existing_order: dict,
    customer_id: str,
    quantities: dict[str, int],
) -> bool:
    existing_quantities = {item["sku"]: item["qty"] for item in existing_order["items"]}

    return (
        existing_order["customer_id"] == customer_id
        and existing_quantities == quantities
    )


def create_order(
    database_url: str,
    order_ref: str,
    customer_id: str,
    items: list[dict],
) -> dict:
    quantities = _normalise_items(items)

    if not quantities:
        raise InvalidOrderError("An order must contain at least one item.")

    too_large = [sku for sku, qty in quantities.items() if qty > MAX_QTY]
    if too_large:
        raise InvalidOrderError(
            f"Combined quantity exceeds {MAX_QTY} for SKU(s): {', '.join(too_large)}"
        )

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        # Check for an existing submission first.
        existing = _get_existing_order(cursor, order_ref)

        if existing is not None:
            if _is_same_submission(existing, customer_id, quantities):
                return existing

            raise OrderConflictError(order_ref)

        # Resolve current product prices in one query. FOR KEY SHARE keeps the
        # rows from being deleted but does not block the worker's stock updates.
        cursor.execute(
            """
                SELECT sku, price_cents
                FROM products
                WHERE sku = ANY(%s)
                ORDER BY sku
                FOR KEY SHARE
                """,
            (list(quantities),),
        )
        products = {row[0]: row[1] for row in cursor.fetchall()}

        missing_skus = set(quantities) - set(products)

        if missing_skus:
            raise UnknownProductError(
                f"Unknown product SKU(s): {', '.join(sorted(missing_skus))}"
            )

        total_cents = sum(products[sku] * qty for sku, qty in quantities.items())

        cursor.execute(
            """
                INSERT INTO orders (
                    order_ref, customer_id, total_cents, status
                )
                VALUES (%s, %s, %s, 'RECEIVED')
                ON CONFLICT (order_ref) DO NOTHING
                RETURNING order_ref
                """,
            (order_ref, customer_id, total_cents),
        )

        inserted = cursor.fetchone()

        if inserted is None:
            # Another request may have inserted this reference meanwhile.
            existing = _get_existing_order(cursor, order_ref)

            if existing is not None and _is_same_submission(
                existing, customer_id, quantities
            ):
                return existing

            raise OrderConflictError(order_ref)

        # Only the transaction that inserted the order row reaches this point;
        # a concurrent duplicate waits on the order's primary key and takes the
        # branch above, so order_lines cannot hit a primary-key race.
        cursor.executemany(
            """
                INSERT INTO order_lines (
                    order_ref, sku, qty, price_cents
                )
                VALUES (%s, %s, %s, %s)
                """,
            [(order_ref, sku, qty, products[sku]) for sku, qty in quantities.items()],
        )

        return {
            "order_ref": order_ref,
            "customer_id": customer_id,
            "total_cents": total_cents,
            "status": "RECEIVED",
            "items": [
                {
                    "sku": sku,
                    "qty": qty,
                    "price_cents": products[sku],
                }
                for sku, qty in quantities.items()
            ],
        }


def get_order_by_ref(database_url: str, order_ref: str) -> dict | None:
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        return _get_existing_order(cursor, order_ref)

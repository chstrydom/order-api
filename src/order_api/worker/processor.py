import psycopg


def _claim_next_order(cursor: psycopg.Cursor) -> str | None:
    """Lock the oldest RECEIVED order. Orders locked by another worker are skipped."""
    cursor.execute(
        """
        SELECT order_ref
        FROM orders
        WHERE status = 'RECEIVED'
        ORDER BY created_at, order_ref
        LIMIT 1
        FOR UPDATE SKIP LOCKED
        """
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _get_order_lines(cursor: psycopg.Cursor, order_ref: str) -> list[tuple[str, int]]:
    cursor.execute(
        """
        SELECT sku, qty
        FROM order_lines
        WHERE order_ref = %s
        ORDER BY sku
        """,
        (order_ref,),
    )
    return cursor.fetchall()


def _lock_products(cursor: psycopg.Cursor, skus: list[str]) -> dict[str, int]:
    """Lock the product rows in SKU order (so workers cannot deadlock) and
    return their current stock.

    FOR NO KEY UPDATE is enough because only `stock` changes. It does not
    conflict with the FOR KEY SHARE lock that order intake takes, so intake
    is not blocked by the worker.
    """
    cursor.execute(
        """
        SELECT sku, stock
        FROM products
        WHERE sku = ANY(%s)
        ORDER BY sku
        FOR NO KEY UPDATE
        """,
        (skus,),
    )
    return dict(cursor.fetchall())


def _deduct_stock(cursor: psycopg.Cursor, lines: list[tuple[str, int]]) -> None:
    cursor.executemany(
        "UPDATE products SET stock = stock - %s WHERE sku = %s",
        [(qty, sku) for sku, qty in lines],
    )


def _set_status(cursor: psycopg.Cursor, order_ref: str, status: str) -> None:
    cursor.execute(
        "UPDATE orders SET status = %s WHERE order_ref = %s",
        (status, order_ref),
    )


def process_one_order(database_url: str) -> bool:
    """Process one RECEIVED order in a single transaction.

    Returns True if an order was claimed and processed (including an order
    that was rejected), and False if no order was available.

    The order is PROCESSED only if every line has enough stock; otherwise it
    is REJECTED and no stock is deducted. Stock changes and the status change
    commit together, or roll back together if anything raises.
    """
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        order_ref = _claim_next_order(cursor)
        if order_ref is None:
            return False

        lines = _get_order_lines(cursor, order_ref)
        stock = _lock_products(cursor, [sku for sku, _ in lines])

        if all(stock.get(sku, 0) >= qty for sku, qty in lines):
            _deduct_stock(cursor, lines)
            _set_status(cursor, order_ref, "PROCESSED")
        else:
            _set_status(cursor, order_ref, "REJECTED")

        return True

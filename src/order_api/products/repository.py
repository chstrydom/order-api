import psycopg


def get_product_by_sku(database_url: str, sku: str) -> dict | None:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT sku, name, price_cents, stock
            FROM products
            WHERE sku = %s
            """,
            (sku,),
        ).fetchone()

    if row is None:
        return None

    return {
        "sku": row[0],
        "name": row[1],
        "price_cents": row[2],
        "stock": row[3],
    }


def get_products_by_skus(database_url: str, skus: list[str]) -> list[dict]:
    if not skus:
        return []

    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT sku, name, price_cents, stock
            FROM products
            WHERE sku = ANY(%s)
            ORDER BY sku
            """,
            (skus,),
        ).fetchall()

    return [
        {
            "sku": row[0],
            "name": row[1],
            "price_cents": row[2],
            "stock": row[3],
        }
        for row in rows
    ]

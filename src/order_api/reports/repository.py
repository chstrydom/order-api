from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg

REPORT_TIMEZONE_NAME = "Africa/Johannesburg"
REPORT_TIMEZONE = ZoneInfo(REPORT_TIMEZONE_NAME)

ORDER_STATUSES = ("RECEIVED", "PROCESSED", "REJECTED")


def _day_bounds(report_date: date) -> tuple[datetime, datetime]:
    """Half-open [start, end) range covering the calendar day in the report
    timezone, so an order at exactly midnight belongs to the new day."""
    start = datetime.combine(report_date, time.min, tzinfo=REPORT_TIMEZONE)
    end = datetime.combine(
        report_date + timedelta(days=1), time.min, tzinfo=REPORT_TIMEZONE
    )
    return start, end


def get_daily_report(database_url: str, report_date: date) -> dict:
    """Report on orders *created* on `report_date`, as the database stands now.

    - orders_total / orders_by_status include every order created that day.
    - Revenue and units sold count only PROCESSED orders, using the unit
      prices stored on their order lines.
    - current_stock is the live stock level, not an end-of-day snapshot.
    """
    start, end = _day_bounds(report_date)

    with psycopg.connect(database_url) as connection:
        # One consistent snapshot for all three queries, even if the worker
        # commits an order in between.
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.read_only = True

        status_rows = connection.execute(
            """
            SELECT status, COUNT(*)
            FROM orders
            WHERE created_at >= %s AND created_at < %s
            GROUP BY status
            """,
            (start, end),
        ).fetchall()

        sales_rows = connection.execute(
            """
            SELECT l.sku,
                   SUM(l.qty)::bigint,
                   SUM(l.qty * l.price_cents)::bigint
            FROM orders o
            JOIN order_lines l ON l.order_ref = o.order_ref
            WHERE o.status = 'PROCESSED'
              AND o.created_at >= %s AND o.created_at < %s
            GROUP BY l.sku
            """,
            (start, end),
        ).fetchall()

        stock_rows = connection.execute(
            "SELECT sku, stock FROM products ORDER BY sku"
        ).fetchall()

    by_status = dict.fromkeys(ORDER_STATUSES, 0)
    by_status.update({status: count for status, count in status_rows})

    sales = {sku: (units, revenue) for sku, units, revenue in sales_rows}

    skus = [
        {
            "sku": sku,
            "units_sold": sales.get(sku, (0, 0))[0],
            "revenue_cents": sales.get(sku, (0, 0))[1],
            "current_stock": stock,
        }
        for sku, stock in stock_rows
    ]

    return {
        "date": report_date.isoformat(),
        "timezone": REPORT_TIMEZONE_NAME,
        "orders_total": sum(by_status.values()),
        "orders_by_status": by_status,
        "revenue_cents": sum(line["revenue_cents"] for line in skus),
        "skus": skus,
    }

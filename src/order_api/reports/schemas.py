from pydantic import BaseModel


class SkuReportLine(BaseModel):
    sku: str
    units_sold: int
    revenue_cents: int
    current_stock: int


class OrdersByStatus(BaseModel):
    RECEIVED: int
    PROCESSED: int
    REJECTED: int


class DailyReport(BaseModel):
    date: str
    timezone: str
    orders_total: int
    orders_by_status: OrdersByStatus
    revenue_cents: int
    skus: list[SkuReportLine]

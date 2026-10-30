from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]

# Maximum quantity of a single order line (after duplicate SKUs are combined).
# Keeps lines comfortably inside PostgreSQL's INTEGER range.
MAX_QTY = 1_000_000


class OrderItemRequest(BaseModel):
    sku: NonEmptyString
    qty: int = Field(gt=0, le=MAX_QTY)


class CreateOrderRequest(BaseModel):
    order_ref: NonEmptyString
    customer_id: NonEmptyString
    items: list[OrderItemRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def check_consolidated_quantities(self):
        # Duplicate SKUs are merged into one order line, so the limit applies to
        # the combined quantity, not just to each item on its own.
        totals: dict[str, int] = {}
        for item in self.items:
            totals[item.sku] = totals.get(item.sku, 0) + item.qty

        too_large = sorted(sku for sku, qty in totals.items() if qty > MAX_QTY)
        if too_large:
            raise ValueError(
                f"Combined quantity exceeds {MAX_QTY} for SKU(s): "
                f"{', '.join(too_large)}"
            )
        return self


class OrderItemResponse(BaseModel):
    sku: str
    qty: int
    price_cents: int


class OrderResponse(BaseModel):
    order_ref: str
    customer_id: str
    total_cents: int
    status: str
    items: list[OrderItemResponse]

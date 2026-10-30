from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class OrderItemRequest(BaseModel):
    sku: NonEmptyString
    qty: int = Field(gt=0)


class CreateOrderRequest(BaseModel):
    order_ref: NonEmptyString
    customer_id: NonEmptyString
    items: list[OrderItemRequest] = Field(min_length=1)

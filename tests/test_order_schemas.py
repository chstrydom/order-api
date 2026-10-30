import pytest
from pydantic import ValidationError

from order_api.orders.schemas import CreateOrderRequest


def test_valid_order_request():
    request = CreateOrderRequest(
        order_ref="ORD-001",
        customer_id="CUST-001",
        items=[
            {"sku": "sku-1", "qty": 2},
            {"sku": "sku-2", "qty": 1},
        ],
    )

    assert request.order_ref == "ORD-001"
    assert len(request.items) == 2


def test_order_request_rejects_empty_items():
    with pytest.raises(ValidationError):
        CreateOrderRequest(
            order_ref="ORD-001",
            customer_id="CUST-001",
            items=[],
        )


def test_order_request_rejects_non_positive_quantity():
    with pytest.raises(ValidationError):
        CreateOrderRequest(
            order_ref="ORD-001",
            customer_id="CUST-001",
            items=[{"sku": "sku-1", "qty": 0}],
        )


def test_order_request_rejects_blank_sku():
    with pytest.raises(ValidationError):
        CreateOrderRequest(
            order_ref="ORD-001",
            customer_id="CUST-001",
            items=[{"sku": "  ", "qty": 1}],
        )


def test_order_request_rejects_consolidated_quantity_over_limit():
    with pytest.raises(ValidationError):
        CreateOrderRequest(
            order_ref="ORD-001",
            customer_id="CUST-001",
            items=[
                {"sku": "sku-1", "qty": 600_000},
                {"sku": "sku-1", "qty": 600_000},
            ],
        )


def test_order_request_accepts_large_quantities_on_different_skus():
    request = CreateOrderRequest(
        order_ref="ORD-001",
        customer_id="CUST-001",
        items=[
            {"sku": "sku-1", "qty": 600_000},
            {"sku": "sku-2", "qty": 600_000},
        ],
    )

    assert len(request.items) == 2

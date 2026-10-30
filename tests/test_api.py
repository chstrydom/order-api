from fastapi.testclient import TestClient

from order_api.main import app

client = TestClient(app)


def test_health_check_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_product_returns_product(test_product):
    response = client.get("/products/TEST-001")

    assert response.status_code == 200
    assert response.json() == {
        "sku": "TEST-001",
        "name": "Test Product",
        "price_cents": 199,
        "stock": 10,
    }


def test_get_unknown_product_returns_404():
    response = client.get("/products/DOES-NOT-EXIST")

    assert response.status_code == 404


def test_submit_order_returns_accepted_order(order_submission):
    response = client.post("/orders", json=order_submission)

    assert response.status_code == 202
    assert response.json() == {
        "order_ref": "API-TEST-001",
        "customer_id": "CUSTOMER-001",
        "total_cents": 398,
        "status": "RECEIVED",
        "items": [
            {
                "sku": "TEST-001",
                "qty": 2,
                "price_cents": 199,
            }
        ],
    }


def test_submit_order_sets_location_header(order_submission):
    response = client.post("/orders", json=order_submission)

    assert response.headers["Location"] == "/orders/API-TEST-001"


def test_duplicate_submission_returns_existing_order(order_submission):
    first_response = client.post("/orders", json=order_submission)
    second_response = client.post("/orders", json=order_submission)

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert second_response.json() == first_response.json()


def test_reusing_order_reference_with_different_payload_returns_409(
    order_submission,
):
    first_response = client.post("/orders", json=order_submission)

    conflicting_submission = {
        **order_submission,
        "customer_id": "DIFFERENT-CUSTOMER",
    }
    second_response = client.post("/orders", json=conflicting_submission)

    assert first_response.status_code == 202
    assert second_response.status_code == 409


def test_submitting_order_with_unknown_product_returns_404():
    payload = {
        "order_ref": "API-UNKNOWN-001",
        "customer_id": "CUSTOMER-001",
        "items": [
            {"sku": "DOES-NOT-EXIST", "qty": 1},
        ],
    }

    response = client.post("/orders", json=payload)

    assert response.status_code == 404


def test_get_order_returns_persisted_order(order_submission):
    create_response = client.post("/orders", json=order_submission)
    assert create_response.status_code == 202

    response = client.get("/orders/API-TEST-001")

    assert response.status_code == 200
    assert response.json() == create_response.json()


def test_get_unknown_order_returns_404():
    response = client.get("/orders/DOES-NOT-EXIST")

    assert response.status_code == 404


def test_blank_sku_returns_422(test_product):
    payload = {
        "order_ref": "API-VALID-001",
        "customer_id": "CUSTOMER-001",
        "items": [{"sku": "  ", "qty": 1}],
    }

    assert client.post("/orders", json=payload).status_code == 422


def test_zero_quantity_returns_422(test_product):
    payload = {
        "order_ref": "API-VALID-002",
        "customer_id": "CUSTOMER-001",
        "items": [{"sku": "TEST-001", "qty": 0}],
    }

    assert client.post("/orders", json=payload).status_code == 422


def test_oversized_quantity_returns_422(test_product):
    payload = {
        "order_ref": "API-VALID-003",
        "customer_id": "CUSTOMER-001",
        "items": [{"sku": "TEST-001", "qty": 3_000_000_000}],
    }

    assert client.post("/orders", json=payload).status_code == 422


def test_empty_items_returns_422():
    payload = {
        "order_ref": "API-VALID-004",
        "customer_id": "CUSTOMER-001",
        "items": [],
    }

    assert client.post("/orders", json=payload).status_code == 422


def test_consolidated_quantity_over_limit_returns_422(test_product):
    payload = {
        "order_ref": "API-VALID-005",
        "customer_id": "CUSTOMER-001",
        "items": [
            {"sku": "TEST-001", "qty": 600_000},
            {"sku": "TEST-001", "qty": 600_000},
        ],
    }

    assert client.post("/orders", json=payload).status_code == 422

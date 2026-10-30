import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status

from order_api.db import initialise_database
from order_api.orders.exceptions import (
    InvalidOrderError,
    OrderConflictError,
    UnknownProductError,
)
from order_api.orders.repository import create_order, get_order_by_ref
from order_api.orders.schemas import CreateOrderRequest, OrderResponse
from order_api.products.repository import get_product_by_sku
from order_api.reports.repository import get_daily_report
from order_api.reports.schemas import DailyReport

# Does not override variables that are already set (e.g. by Docker Compose).
load_dotenv(override=False)


def get_database_url() -> str:
    return os.environ["DATABASE_URL"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialise_database(get_database_url())
    yield


app = FastAPI(title="Order API", lifespan=lifespan)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/products/{sku}")
def read_product(sku: str, database_url: str = Depends(get_database_url)):
    product = get_product_by_sku(database_url, sku)

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{sku}' not found.",
        )

    return product


@app.post(
    "/orders",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=OrderResponse,
)
def submit_order(
    request: CreateOrderRequest,
    response: Response,
    database_url: str = Depends(get_database_url),
):
    try:
        order = create_order(
            database_url=database_url,
            order_ref=request.order_ref,
            customer_id=request.customer_id,
            items=[item.model_dump() for item in request.items],
        )
        response.headers["Location"] = f"/orders/{order['order_ref']}"
        return order
    except InvalidOrderError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except OrderConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order reference already exists with a different submission.",
        ) from exc
    except UnknownProductError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@app.get("/orders/{order_ref}", response_model=OrderResponse)
def read_order(order_ref: str, database_url: str = Depends(get_database_url)):
    order = get_order_by_ref(database_url=database_url, order_ref=order_ref)

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_ref}' not found.",
        )

    return order


@app.get("/reports/daily", response_model=DailyReport)
def read_daily_report(
    report_date: Annotated[
        date, Query(alias="date", description="Calendar day, YYYY-MM-DD")
    ],
    database_url: str = Depends(get_database_url),
):
    return get_daily_report(database_url, report_date)

# Solution Design

This document records the requirements, assumptions, design decisions, and trade-offs for the Order API take-home assignment. Decisions may be revised as implementation and testing expose issues.

## 1. Requirements and assumptions

### Functional requirements

- Accept orders through an API.
- Prevent duplicate submissions from creating duplicate orders or stock deductions.
- Calculate order totals using product prices at the time of order creation.
- Process accepted orders against available stock.
- Expose order details and current product stock.
- Accept and persist orders while stock processing is temporarily unavailable.
- Resume processing and catch up on outstanding orders after recovery.
- Provide a daily report containing order counts, revenue, and units sold per SKU.
- Demonstrate the duplicate-submission and temporary-processing-interruption scenarios.

### Non-functional requirements

- Handle bursts of incoming orders without losing accepted submissions.
- Persist work that remains outstanding during a processing interruption.
- Keep the implementation appropriately small for the assignment.
- Provide reproducible local setup, database initialisation, and tests.

### Current scope assumptions

- Stock is decremented only when an order is successfully processed.
- Stock replenishment and order cancellation are out of scope.
- The daily report is the selected extension option (Option B).
- The database-backed processing queue is polled by a background worker.
- Authentication and authorisation are out of scope for this exercise.
- Insufficient stock policy: An order requesting more stock than is available is rejected. No stock is deducted, and the rejection is persisted as the order's terminal processing outcome. Partial fulfilment and waiting for future stock availability are out of scope. Replenishment and order cancellation are also out of scope.

## 2. Technology choices

### Python and FastAPI

Python 3.14 is the selected runtime because it is available in the development environment. Dependency compatibility will be verified through installation and tests.

FastAPI provides typed request and response models, input validation, generated OpenAPI documentation, and a straightforward testing interface.

FastAPI background tasks alone are not used as the durable processing mechanism. Outstanding stock work must remain recorded in PostgreSQL so it can be resumed after interruption or process restart.

### PostgreSQL and psycopg

PostgreSQL provides durable storage, unique constraints, transactions, and concurrency controls needed for order intake and stock processing.

The application uses psycopg with explicit SQL rather than an ORM. This keeps the data access behaviour visible and allows the implementation to demonstrate transaction boundaries, constraints, and stock updates directly.

SQL will be kept in focused data-access functions rather than embedded indiscriminately in HTTP route handlers.

## 3. Data model

The proposed core entities are:

| Entity | Purpose | Proposed fields |
|---|---|---|
| Product | Current product and stock information | `sku`, `name`, `unit_price`, `stock_quantity` |
| Order | Order identity, total, and processing status | `order_ref`, `customer_id`, `total`, `created_at`, `status` |
| OrderLine | Products and quantities captured for an order | `order_ref`, `sku`, `quantity`, `unit_price` |

### Data-model decisions

- `order_ref` is unique and identifies an order submission.
- The order line stores the unit price used when the order was created. Later product price changes must not change historical order totals.
- Order creation time is stored for processing order and daily reporting.
- Order status represents the processing outcome.
- The order and its lines are persisted together in a transaction.
- The database schema and initialisation or migration approach still need to be implemented.

The draft does not include a separate log table because application logging is outside the current scope. Operational errors can be reported through standard application logging.

If an order can contain the same SKU on multiple input lines, the implementation must define whether those quantities are consolidated or represented as separate lines. The simpler initial contract is to consolidate quantities by SKU before persistence.

## 4. API contract

| Endpoint | Purpose |
|---|---|
| `POST /orders` | Create an order |
| `GET /orders/{order_ref}` | Retrieve an order, its lines, and its status |
| `GET /products/{sku}` | Retrieve product details and current stock |
| `GET /reports/daily?date=YYYY-MM-DD` | Retrieve the daily report |

### Expected HTTP behaviour

- `POST /orders` returns `201 Created` for a newly persisted order.
- An identical retry using an existing `order_ref` returns the existing order and its current persisted status, without creating another order or triggering stock processing again.
- Reusing an existing `order_ref` with a different payload returns `409 Conflict`.
- A new attempt after a rejected order must use a new `order_ref`.
- Invalid request data returns `422 Unprocessable Entity`.
- An unknown SKU returns `404 Not Found`; order creation must be atomic so that no partial order is committed.
- Unknown order or product references return `404 Not Found`.

The implementation must ensure that validation and persistence failures do not leave a partially created order.

## 5. Order intake and stock processing

### Durable order intake

Order intake and stock processing are separate stages.

1. Validate the request and resolve product prices.
2. Persist the order and its lines in a single transaction.
3. Mark the order as awaiting stock processing.
4. Return the persisted order to the caller.
5. A background worker polls outstanding orders and attempts stock processing.
6. The worker records the final processing outcome.

This design allows order intake to continue while the worker is temporarily stopped, provided PostgreSQL and the API remain available.

An order accepted by the intake API is not necessarily a successfully fulfilled order. Its status must make that distinction clear.

### Database-backed work polling

The worker polls the orders table for eligible outstanding work. This is a database-backed work queue; it is not a separate message broker.

The worker should process older outstanding orders first unless testing demonstrates a reason to use a different ordering.

The implementation must also prevent two workers from successfully processing the same order concurrently.

### Transactional stock processing

Stock deductions and the corresponding order status update must be atomic.

Within one database transaction, the worker must:

1. Lock or otherwise safely coordinate access to the relevant stock records.
2. Verify that sufficient stock is available for every order line.
3. If all lines can be fulfilled, deduct the requested quantities and mark the order `PROCESSED`.
4. If any line has insufficient stock, leave all stock quantities unchanged and mark the order `REJECTED`.

The order status update and any stock deductions must commit together. If a database error occurs during processing, the transaction must roll back so that a retry cannot repeat a partially applied stock deduction.

A rejected order is a terminal outcome for that `order_ref`. Retrying the original request returns the existing rejected order; it does not automatically attempt processing again.

Concurrent orders competing for the same stock must be handled using appropriate database locking or conditional updates. Application-side stock checks alone are insufficient.

## 6. Daily report

The daily report is the selected extension option.

The endpoint will report for the requested calendar date:

- Total number of orders created, including orders that have not been processed or were rejected.
- Order counts grouped by processing status.
- Revenue from successfully processed orders, calculated using their stored order-line prices.
- Units sold per SKU, counting only successfully processed orders.
- Current stock per SKU.

Revenue and units sold reflect successful stock processing, not merely order intake. Current stock represents the latest stock level at the time the report is generated; it is not a historical end-of-day stock snapshot.

The reporting date boundary and timezone must be documented and applied consistently. The report must also define whether the requested date filters order creation time or processing time. For this design, the initial choice is order creation date, with revenue and units sold including only orders created on that date that have reached `PROCESSED` status by the time the report is generated.

## 7. Code organisation

The implementation will use a small separation of responsibilities:

- **API routes:** HTTP request handling, response formatting, and input/output models.
- **Business logic:** order rules, idempotency behaviour, and stock-processing decisions.
- **Data access:** explicit SQL, database transactions, and queries.
- **Worker:** polling and processing outstanding orders.

The separation should make business rules testable without requiring every test to exercise the HTTP layer. Additional abstractions will be introduced only when they provide a clear benefit.

## 8. Testing strategy

Tests will cover:

- Successful order creation and retrieval.
- Duplicate submission with the same payload.
- Reuse of an order reference with a different payload.
- Product price snapshotting.
- Unknown products and invalid quantities.
- Sufficient and insufficient stock.
- Concurrent orders competing for limited stock.
- Transaction rollback when processing fails.
- Worker interruption and recovery, including processing outstanding work after restart.
- Daily report totals and status filtering.

The two required unhappy-path demonstrations are duplicate submission and temporary stock-processing interruption followed by catch-up.

## 9. Out of scope

- Order cancellation.
- Stock replenishment.
- Product CRUD beyond what is necessary for initial data and stock lookup.
- Direct OrderLine CRUD.
- Authentication and authorisation.
- A separate message broker.
- A dedicated logging table.
- Price refresh for existing orders.
- Row-level security.

## 10. Remaining implementation decisions

- Database schema creation and migration strategy.
- Initial product seed data.
- Exact order status names and transitions.
- Final API request and response shapes.
- Reporting timezone and revenue definition.
- Worker polling interval and shutdown behaviour.
- Final Docker Compose configuration and application entry point.

These decisions will be settled before or during implementation and reflected in the tests and README.
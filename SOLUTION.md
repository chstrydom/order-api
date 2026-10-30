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
- Insufficient stock policy: An order requesting more stock than is available is rejected. No stock is deducted, and the rejection is persisted as the order's terminal processing outcome. Partial fulfilment and waiting for future stock availability are out of scope.
- An order reference identifies a single order submission. A new attempt after rejection must use a new order reference.

|   Area	|   Status  |
|   -   | - |
|   PostgreSQL schema and initialisation	|   Implemented  |
|   Product data access	|   Implemented  |
|   Order request validation	|   Implemented  |
|   Order intake and persistence	|   Implemented  |
|   Duplicate SKU consolidation	|   Implemented  |
|   Idempotent order submission	|   Implemented  |
|   Order-line price snapshots	|   Implemented  |
|   Unknown-product handling	|   Implemented  |
|   FastAPI routes	|   Pending  |
|   Stock-processing worker	|   Pending  |
|   Transactional stock deduction	|   Pending  |
|   Daily report	|   Pending  |
|   Application containerisation	|   Pending  |

## 2. Technology choices

### Python and FastAPI

Python 3.14 is the selected runtime because it is available in the development environment. The selected dependencies have been installed and verified through the current automated test suite.

FastAPI provides typed request and response models, input validation, generated OpenAPI documentation, and a straightforward testing interface.

FastAPI background tasks alone are not used as the durable processing mechanism. Outstanding stock work must remain recorded in PostgreSQL so it can be resumed after interruption or process restart.

### PostgreSQL and psycopg

PostgreSQL 17, using the official Docker image, provides a predictable development and test environment without relying on the mutable `latest` tag.

PostgreSQL provides the transactional guarantees, row-level locking, constraints, and aggregation required for reliable stock processing and reporting.

The application uses psycopg with explicit SQL rather than an ORM. This keeps the data access behaviour visible and allows the implementation to demonstrate transaction boundaries, constraints, and stock updates directly.

SQL will be kept in focused data-access functions rather than embedded indiscriminately in HTTP route handlers.

## 3. Data model

The core entities are:

| Entity | Purpose | Fields |
|---|---|---|
| Product | Current product and stock information | `sku`, `name`, `price_cents`, `stock` |
| Order | Order identity, total, and processing status | `order_ref`, `customer_id`, `total_cents`, `created_at`, `status` |
| OrderLine | Products and quantities captured for an order | `order_ref`, `sku`, `qty`, `price_cents` |

### Data-model decisions

- `order_ref` is the primary key of an order and identifies a unique submission.
- The order line stores the unit price used when the order was created. Later product price changes must not change historical order totals.
- Order creation time is stored for processing order and daily reporting.
- Order status represents the processing outcome.
- The order and its lines are persisted together in a transaction.
- Product deletion is restricted when historical order lines reference it (`ON DELETE RESTRICT`), preserving order history.
- Order-line quantities for duplicate SKUs in the same request are consolidated before persistence.
- Monetary values use integer (BIGINT) cents throughout the database and business calculations. This avoids floating-point precision issues in monetary calculations.
- Database constraints enforce basic data validity independently of application-level validation.

The draft does not include a separate log table because application logging is outside the current scope. Operational errors can be reported through standard application logging.

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

### Considerations

The API resolves prices from product records when accepting an order, then snapshots those prices into `order_lines`.

An accepted order is not necessarily a fulfilled order. The response and subsequent order retrieval must distinguish between successful intake and completed stock processing.

## 5. Order intake and stock processing

### Durable order intake

Order intake and stock processing are separate stages.

1. Validate the request and resolve product prices.
2. Persist the order and its lines in a single transaction.
3. Set the initial order status to `RECEIVED`.
4. Return the persisted order to the caller.
5. A background worker polls outstanding orders and attempts stock processing.
6. The worker records the final processing outcome.

### Order intake guarantees
- Duplicate SKUs in a request are consolidated into one order line, with quantities added together.
- Product prices are resolved and locked for the duration of the intake transaction before the order is persisted.
- The order total is calculated using The captured unit prices and consolidated quantities.
- The order and all order lines are inserted within one transaction.
- If any requested SKU does not exist, order creation fails without persisting a partial order.
- An identical retry is identified by comparing the customer and consolidated SKU quantities, rather than relying on the order of items in the request.
- A conflicting retry using the same order reference is rejected.

This design allows order intake to continue while the worker is temporarily stopped, provided PostgreSQL and the API remain available.

Order acceptance means that the Orders capability has validated and durably persisted the submission. It does not guarantee stock availability or successful fulfilment. Stock processing occurs asynchronously, and the final outcome is reflected in the order status.

### Order statuses

| Status | Meaning |
|---|---|
| `RECEIVED` | Order is durably persisted and awaiting stock processing. |
| `PROCESSED` | Stock was successfully deducted for all order lines. |
| `REJECTED` | Stock was insufficient for at least one order line; no stock was deducted. |

`PROCESSED` and `REJECTED` are terminal outcomes for the order reference.

An identical retry of a rejected order returns the existing rejected order. It does not automatically attempt processing again.

### Database-backed work polling

The worker polls the orders table for eligible outstanding work. This is a database-backed work queue; it is not a separate message broker.

The worker should prioritise older outstanding orders using created_at as the primary ordering field. A deterministic secondary ordering field should be used where timestamps are equal. Under concurrent processing, strict global FIFO ordering is not guaranteed.

The implementation must also prevent two workers from successfully processing the same order concurrently.

### Transactional stock processing

Stock deductions and the corresponding order status update must be atomic.

Within one database transaction, the worker must:

1. Lock or otherwise safely coordinate access to the relevant stock records.
2. Verify that sufficient stock is available for every order line.
3. If all lines can be fulfilled, deduct the requested quantities and mark the order `PROCESSED`.
4. If any line has insufficient stock, leave all stock quantities unchanged and mark the order `REJECTED`.

The order status update and any stock deductions must commit together. If a database error occurs during processing, the transaction must roll back so that a retry cannot repeat a partially applied stock deduction.

Concurrent orders competing for the same stock must be handled using appropriate database locking or conditional updates. Application-side stock checks alone are insufficient.

## 6. Database schema

The database consists of three tables:

### Products

| Column | PostgreSQL type | Constraints |
|---|---|---|
| `sku` | TEXT | Primary key |
| `name` | TEXT | NOT NULL |
| `price_cents` | BIGINT | NOT NULL, CHECK (`price_cents >= 0`) |
| `stock` | INTEGER | NOT NULL, CHECK (`stock >= 0`) |

### Orders

| Column | PostgreSQL type | Constraints |
|---|---|---|
| `order_ref` | TEXT | Primary key |
| `customer_id` | TEXT | NOT NULL |
| `total_cents` | BIGINT | NOT NULL, CHECK (`total_cents >= 0`) |
| `created_at` | TIMESTAMPTZ | NOT NULL, defaults to current timestamp |
| `status` | TEXT | NOT NULL, restricted to `RECEIVED`, `PROCESSED`, `REJECTED` |

### Order lines

| Column | PostgreSQL type | Constraints |
|---|---|---|
| `order_ref` | TEXT | NOT NULL, foreign key to `orders.order_ref` |
| `sku` | TEXT | NOT NULL, foreign key to `products.sku` |
| `qty` | INTEGER | NOT NULL, CHECK (`qty > 0`) |
| `price_cents` | BIGINT | NOT NULL, CHECK (`price_cents >= 0`) |

The `order_lines` table has a composite primary key on (`order_ref`, `sku`), preventing duplicate SKU lines within an order.

Both foreign keys use `ON DELETE RESTRICT`.

### Relationships

```text
products
   |
   | sku
   |
   v
order_lines -------- orders
     |                   |
     +---- order_ref ----+
```

### Database constraints

1. Product prices cannot be negative.
2. Product stock cannot be negative.
3. Order-line quantities must be greater than zero.
4. Order totals cannot be negative.
5. Product SKU is unique and cannot be null.
6. Order reference is unique and cannot be null.
7. Order lines have a composite primary key on (`order_ref`, `sku`).
8. Order lines reference both their order and product.
9. Both foreign keys restrict deletion of referenced records.
10. Monetary values use integer cents.

### Schema initialisation

The schema is maintained in `src/order_api/db/schema.sql` and initialised through the database module.

`CREATE TABLE IF NOT EXISTS` allows initialisation to be repeated without failing when tables already exist. It does not apply changes to existing tables. Schema changes to an existing database will require an appropriate migration or a fresh database.

## 7. Daily report

The daily report is the selected extension option (Option B).

The endpoint will report for the requested calendar date:

- Total number of orders created, including orders that have not been processed or were rejected.
- Revenue from successfully processed orders, calculated using their stored order-line prices.
- Units sold per SKU, counting only successfully processed orders.
- Current stock per SKU.

Revenue and units sold reflect successful stock processing, not merely order intake. Current stock represents the latest stock level at the time the report is generated; it is not a historical end-of-day stock snapshot.

The reporting date filters orders by creation date, not processing date.

Revenue and units sold include only orders created on the requested date that have reached `PROCESSED` status by the time the report is generated.

The reporting timezone must be documented and applied consistently when determining the calendar-day boundaries.

The report is calculated using the state of the database at generation time. Consequently, a report generated for a past date may include orders that were still `RECEIVED` when an earlier version of that report was generated but have since become `PROCESSED`.

## 8. Code organisation

The implementation uses a small separation of responsibilities:

- **API routes:** HTTP request handling, response formatting, and input/output models.
- **Business logic:** order rules, idempotency behaviour, and stock-processing decisions.
- **Data access:** explicit SQL, database transactions, and queries.
- **Worker:** polling and processing outstanding orders.

The separation should make business rules testable without requiring every test to exercise the HTTP layer. Additional abstractions will be introduced only when they provide a clear benefit.

## 9. Testing strategy

Implemented tests
- Database connection and schema initialisation.
- Database-enforced non-negative product stock.
- Product retrieval by SKU.
- Multiple product retrieval and missing SKU handling.
- Order request validation.
- Successful order persistence.
- Order total calculation.
- Duplicate SKU consolidation.
- Identical submission retry.
- Conflicting submission using an existing order reference.
- Product price snapshot preservation.
- Unknown product handling.
- No stock deduction during order intake.
- Atomic order creation when a requested SKU is unknown.

Remaining tests
- Order retrieval through the API.
- Sufficient and insufficient stock processing.
- Concurrent orders competing for limited stock.
- Transaction rollback during stock processing.
- Worker interruption and recovery.
- Daily report calculations and status filtering.
- HTTP response behaviour.

The two required unhappy-path demonstrations are duplicate submission and temporary stock-processing interruption followed by catch-up.

Database tests also verify the connection, schema initialisation, and database-enforced constraints.

The current automated test suite contains 20 passing tests covering the implemented database, product-repository, order-repository, and request-validation functionality.

## 10. Out of scope

- Order cancellation.
- Stock replenishment.
- Product CRUD beyond what is necessary for initial data and stock lookup.
- Direct OrderLine CRUD.
- Authentication and authorisation.
- A separate message broker.
- A dedicated logging table.
- Price refresh for existing orders.
- Row-level security.

## 11. Remaining implementation decisions

The following details remain to be finalised during implementation:

- Initial product seed data.
- Final API request and response shapes.
- Reporting timezone.
- Worker polling interval and shutdown behaviour.
- Final Docker Compose configuration and application entry point.

These decisions will be reflected in the implementation, tests, and README as they are settled.
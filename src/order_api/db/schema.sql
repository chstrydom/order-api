CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price_cents BIGINT NOT NULL CHECK (price_cents >= 0),
    stock INTEGER NOT NULL,

    CONSTRAINT products_stock_non_negative
        CHECK (stock >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
    order_ref TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    total_cents BIGINT NOT NULL CHECK (total_cents >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL CHECK (
        status IN ('RECEIVED', 'PROCESSED', 'REJECTED')
    )
);

CREATE TABLE IF NOT EXISTS order_lines (
    order_ref TEXT NOT NULL,
    sku TEXT NOT NULL,
    qty INTEGER NOT NULL CHECK (qty > 0),
    price_cents BIGINT NOT NULL CHECK (price_cents >= 0),

    PRIMARY KEY (order_ref, sku),

    CONSTRAINT fk_order_lines_order
        FOREIGN KEY (order_ref)
        REFERENCES orders (order_ref)
        ON DELETE RESTRICT,

    CONSTRAINT fk_order_lines_product
        FOREIGN KEY (sku)
        REFERENCES products (sku)
        ON DELETE RESTRICT
);
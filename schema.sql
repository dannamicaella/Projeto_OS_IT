-- DDL for the OS IT application
-- Compatible with PostgreSQL (Supabase) and SQLite

CREATE TABLE IF NOT EXISTS "order" (
    id          SERIAL PRIMARY KEY,
    token       VARCHAR(64)  NOT NULL UNIQUE,
    cliente     VARCHAR(120) NOT NULL,
    contato     VARCHAR(120) NOT NULL,
    produto     VARCHAR(120) NOT NULL,
    problema    TEXT         NOT NULL,
    status      VARCHAR(50)  NOT NULL DEFAULT 'Recebido',
    data_entrada TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_order_token       ON "order" (token);
CREATE INDEX IF NOT EXISTS ix_order_status      ON "order" (status);
CREATE INDEX IF NOT EXISTS ix_order_data_entrada ON "order" (data_entrada);

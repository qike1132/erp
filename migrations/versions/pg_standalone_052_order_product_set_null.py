"""Set order.product_id FK to ON DELETE SET NULL and allow NULL.

Background:
    Order soft-delete keeps the order row and its product_id. When the product
    is later deleted, SQLAlchemy's ``Product.orders`` backref tries to detach
    those soft-deleted orders by setting ``order.product_id = NULL``. The old
    schema had ``NOT NULL`` + ``ON DELETE RESTRICT``, so the flush raised
    ``NotNullViolation`` and the API returned 500.

    Soft-deleted orders are already excluded from all business queries, so it
    is safe to detach them from a deleted product instead of blocking product
    deletion on hidden history.

Revision ID: pg_standalone_052_order_product_set_null
Revises: pg_standalone_051_fix_is_default_flag
Create Date: 2026-09-27
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'pg_standalone_052_order_product_set_null'
down_revision = 'pg_standalone_051_fix_is_default_flag'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "order" ALTER COLUMN product_id DROP NOT NULL')
    op.execute("""
        DO $$
        DECLARE
            cname text;
        BEGIN
            SELECT conname INTO cname
            FROM pg_constraint
            WHERE conrelid = 'order'::regclass
              AND confrelid = 'product'::regclass
              AND contype = 'f';
            IF cname IS NOT NULL THEN
                EXECUTE format('ALTER TABLE "order" DROP CONSTRAINT %I', cname);
            END IF;
        END $$;
    """)
    op.execute("""
        ALTER TABLE "order"
        ADD CONSTRAINT order_product_id_fkey
        FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE SET NULL
    """)


def downgrade() -> None:
    """Not reversible once NULL product_id rows exist for deleted products."""

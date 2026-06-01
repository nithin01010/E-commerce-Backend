"""Add GIN index and trigger for search_vector

Revision ID: f98fc5569630
Revises: 5069d3b707c8
Create Date: 2026-06-02 01:01:18.121200

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f98fc5569630'
down_revision: Union[str, None] = '5069d3b707c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create the GIN index
    op.create_index(
        'ix_product_search_gin',
        'products',
        ['search_vector'],
        unique=False,
        postgresql_using='gin'
    )
    
    # 2. Update existing rows
    op.execute("""
        UPDATE products 
        SET search_vector = to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, ''));
    """)
    
    # 3. Create the function for the trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION products_search_vector_update() RETURNS trigger AS $$
        BEGIN
          new.search_vector := to_tsvector('english', coalesce(new.name, '') || ' ' || coalesce(new.description, ''));
          return new;
        END
        $$ LANGUAGE plpgsql;
    """)
    
    # 4. Create the trigger
    op.execute("""
        CREATE TRIGGER products_vector_update
        BEFORE INSERT OR UPDATE ON products
        FOR EACH ROW EXECUTE FUNCTION products_search_vector_update();
    """)


def downgrade() -> None:
    # 1. Drop trigger
    op.execute("DROP TRIGGER IF EXISTS products_vector_update ON products;")
    # 2. Drop function
    op.execute("DROP FUNCTION IF EXISTS products_search_vector_update();")
    # 3. Drop index
    op.drop_index('ix_product_search_gin', table_name='products', postgresql_using='gin')

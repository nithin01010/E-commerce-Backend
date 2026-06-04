import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.models.product import Product
from app.models.category import Category
from app.models.seller import Seller
from app.models.user import User

async def create_dummy_data(db: AsyncSession):
    # Create User
    user = User(
        email="seller@test.com",
        username="seller",
        hashed_password="hashed_password",
        role="seller"
    )
    db.add(user)
    await db.commit()
    
    # Create Category
    category = Category(name="Electronics", description="Gadgets")
    db.add(category)
    await db.commit()
    
    # Create Seller Profile
    seller = Seller(
        user_id=user.id,
        store_name="Tech Store",
        gst_number="123456789",
        pan_number="ABCDE1234F",
        address="123 Tech St"
    )
    db.add(seller)
    await db.commit()
    
    # Create Product (This relies on the DB trigger for search_vector)
    product = Product(
        name="Ultra Fast Gaming Laptop",
        description="A super fast laptop with 32GB RAM and RTX 4090.",
        price=2000,
        stock=10,
        is_verified=True,
        status="active",
        category_id=category.id,
        seller_id=seller.id
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    
    return product

async def test_search_products_success(client: AsyncClient, db_session: AsyncSession):
    # Setup Data
    product = await create_dummy_data(db_session)
    
    # In PostgreSQL, we need to manually invoke the trigger if the test database
    # was just created by SQLAlchemy Base.metadata.create_all because triggers
    # are usually handled by Alembic, not SQLAlchemy metadata!
    # Let's forcefully update the search_vector for the test
    await db_session.execute(
        text("UPDATE products SET search_vector = to_tsvector('english', name || ' ' || description)")
    )
    await db_session.commit()

    # Hit the Search Endpoint
    response = await client.get("/products/?search=fast laptop")
    
    assert response.status_code == 200
    data = response.json()
    
    # Assert our product was found
    assert len(data) > 0
    assert data[0]["name"] == "Ultra Fast Gaming Laptop"

async def test_search_products_no_match(client: AsyncClient, db_session: AsyncSession):
    await create_dummy_data(db_session)
    await db_session.execute(
        text("UPDATE products SET search_vector = to_tsvector('english', name || ' ' || description)")
    )
    await db_session.commit()

    # Search for something that doesn't exist
    response = await client.get("/products/?search=wooden chair")
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 0

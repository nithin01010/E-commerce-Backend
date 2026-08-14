import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.models.product import Product
from app.models.category import Category
from app.models.seller import Seller
from app.models.user import User
from app.models.role import Role
from app.main import app

@pytest.fixture
async def authenticated_seller_client(client, db_session):
    # 1. Create Seller Role (required for User FK)
    role = Role(id=2, name="seller")
    db_session.add(role)
    await db_session.commit()

    # 2. Create User with role_id=2
    user = User(
        email="seller@test.com",
        password="hashed_password",
        role_id=2,
        is_active=True
    )
    db_session.add(user)
    await db_session.commit()

    # 3. Create Seller profile (required by get_seller_profile)
    seller = Seller(
        name="Tech Store",
        phone_number="9876543210",
        is_active=True,
        is_verified=True,
        user_id=user.id
    )
    db_session.add(seller)

    # 4. Create Category
    category = Category(name="Electronics")
    db_session.add(category)
    await db_session.commit()

    # 5. Override dependency
    from app.api.deps import get_current_user
    app.dependency_overrides[get_current_user] = lambda: user
    
    yield client, category.id

    # Clean up overrides
    app.dependency_overrides.pop(get_current_user, None)


async def test_create_product_success(authenticated_seller_client):
    client, category_id = authenticated_seller_client
    
    # Hit the POST products creation endpoint
    response = await client.post(
        "/products/",
        json={
            "name": "Ultra Fast Gaming Laptop",
            "description": "A super fast laptop with 32GB RAM and RTX 4090.",
            "price": 2000,
            "stock": 10,
            "category_id": category_id
        }
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Ultra Fast Gaming Laptop"
    assert data["price"] == 2000
    assert data["stock"] == 10
    assert data["category_id"] == category_id


async def create_dummy_data(db: AsyncSession):
    # 1. Create Seller Role
    role = Role(id=2, name="seller")
    db.add(role)
    await db.commit()

    # 2. Create User
    user = User(
        email="seller_dummy@test.com",
        password="hashed_password",
        role_id=2,
        is_active=True
    )
    db.add(user)
    await db.commit()
    
    # 3. Create Category
    category = Category(name="Electronics")
    db.add(category)
    await db.commit()
    
    # 4. Create Seller Profile
    seller = Seller(
        name="Tech Store",
        phone_number="9876543210",
        is_active=True,
        is_verified=True,
        user_id=user.id
    )
    db.add(seller)
    await db.commit()
    
    # 5. Create Product (with search_vector)
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
    
    return product, category.id, user


async def test_search_products_success(client: AsyncClient, db_session: AsyncSession):
    # Setup Data
    product, category_id, _ = await create_dummy_data(db_session)
    
    # Forcefully update the search_vector for PostgreSQL full-text search test
    await db_session.execute(
        text("UPDATE products SET search_vector = to_tsvector('english', name || ' ' || description)")
    )
    await db_session.commit()

    # Hit the Search Endpoint
    response = await client.get("/products/?search=fast laptop")
    
    assert response.status_code == 200
    data = response.json()
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


async def test_filter_products_by_category(client: AsyncClient, db_session: AsyncSession):
    product, category_id, _ = await create_dummy_data(db_session)

    response = await client.get(f"/products/?category_id={category_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert data[0]["category_id"] == category_id


async def test_get_product_details_success(client: AsyncClient, db_session: AsyncSession):
    product, _, _ = await create_dummy_data(db_session)

    response = await client.get(f"/products/{product.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == product.id
    assert data["name"] == product.name


async def test_get_product_details_not_found(client: AsyncClient):
    response = await client.get("/products/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


async def test_partially_update_product(authenticated_seller_client):
    client, category_id = authenticated_seller_client
    
    # 1. Create a product
    create_res = await client.post(
        "/products/",
        json={
            "name": "Original Name",
            "description": "Original description",
            "price": 100,
            "stock": 5,
            "category_id": category_id
        }
    )
    assert create_res.status_code == 201
    prod_id = create_res.json()["id"]

    # 2. Patch the product
    patch_res = await client.patch(
        f"/products/{prod_id}",
        json={"price": 150, "stock": 20}
    )
    assert patch_res.status_code == 200
    patched_data = patch_res.json()
    assert patched_data["price"] == 150
    assert patched_data["stock"] == 20
    assert patched_data["name"] == "Original Name"


async def test_delete_product_success(authenticated_seller_client):
    client, category_id = authenticated_seller_client
    
    # 1. Create product
    create_res = await client.post(
        "/products/",
        json={
            "name": "Product to delete",
            "description": "Will be deleted",
            "price": 50,
            "stock": 2,
            "category_id": category_id
        }
    )
    assert create_res.status_code == 201
    prod_id = create_res.json()["id"]

    # 2. Delete product
    del_res = await client.delete(f"/products/{prod_id}")
    assert del_res.status_code == 204

    # 3. Verify it cannot be retrieved
    get_res = await client.get(f"/products/{prod_id}")
    assert get_res.status_code == 404

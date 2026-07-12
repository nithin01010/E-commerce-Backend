from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.core.database import get_db
from app.api.deps import get_current_user, get_redis
from app.models.user import User
from app.models.category import Category
from app.models.seller import Seller
from app.models.product import Product, ProductImage
from app.schemas.product import ProductCreate, ProductImageResponse
from app.schemas.product import ProductResponse, ProductUpdate
import redis.asyncio as redis
from app.core.cache import get_cached, set_cache, invalidate_pattern
from app.core.cache import serialize_product
from app.core.config import settings

from fastapi_limiter.depends import RateLimiter
from pyrate_limiter import Rate, Duration, Limiter

router = APIRouter()


# -----------------------------HELPER FUNCTIOSNS-------------------------------


async def get_seller_profile(db: AsyncSession, user_id: int) -> Seller:
    result = await db.execute(select(Seller).where(Seller.user_id == user_id))
    seller = result.scalars().first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Seller profile not found."
        )
    return seller


def check_is_seller(role_id):
    if role_id != 2:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only sellers can create products",
        )


def check_category_exists(category):
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )


async def check_product_exists(db: AsyncSession, name: str, seller_id: int):
    result = await db.execute(
        select(Product).where(
            Product.name == name, Product.seller_id == seller_id
        )
    )
    product = result.scalars().first()
    if product:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product with this name already exists in your store",
        )


def check_product_exists1(product):
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )


async def get_product(db, product_id, seller_id):
    prod = await db.execute(
        select(Product)
        .where(Product.id == product_id, Product.seller_id == seller_id)
        .options(selectinload(Product.images))
    )
    product = prod.scalars().first()
    check_product_exists1(product)
    return product


# ----------------------------------------------------------------------------------

limiter_create_post = Limiter(Rate(100000, Duration.MINUTE)) if settings.DEBUG else Limiter(Rate(5, Duration.MINUTE))


@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimiter(limiter=limiter_create_post))]
)
async def create_product(
    product_in: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis)
):
    check_is_seller(current_user.role_id)

    seller = await get_seller_profile(db, current_user.id)
    cat = await db.execute(
        select(Category).where(Category.id == product_in.category_id)
    )
    category = cat.scalars().first()
    check_category_exists(category)

    await check_product_exists(db, product_in.name, seller.id)

    new_prod = Product(
        name=product_in.name,
        description=product_in.description,
        price=product_in.price,
        stock=product_in.stock,
        category_id=product_in.category_id,
        seller_id=seller.id,
    )

    db.add(new_prod)
    await db.commit()
    await db.refresh(new_prod, ["images"])

    # WRITE-THROUGH: cache
    await set_cache(
        redis_client,
        f"product:{new_prod.id}",
        serialize_product(new_prod),
        ttl=120
    )

    await invalidate_pattern(redis_client, "products:*")

    return new_prod


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    product_in: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis)
):
    check_is_seller(current_user.role_id)

    seller = await get_seller_profile(db, current_user.id)
    product = await get_product(db, product_id, seller.id)

    cat = await db.execute(
        select(Category).where(Category.id == product_in.category_id)
    )
    category = cat.scalars().first()
    check_category_exists(category)

    product.name = product_in.name
    product.description = product_in.description
    product.price = product_in.price
    product.stock = product_in.stock
    product.category_id = product_in.category_id

    await db.commit()
    await db.refresh(product, ["images"])

    # WRITE-THROUGH: cache
    await set_cache(
        redis_client,
        f"product:{product.id}",
        serialize_product(product),
        ttl=120
    )

    await invalidate_pattern(redis_client, "products:*")

    return product


@router.patch("/{product_id}", response_model=ProductResponse)
async def partially_update_product(
    product_id: int,
    product_in: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis)
):
    check_is_seller(current_user.role_id)

    seller = await get_seller_profile(db, current_user.id)
    product = await get_product(db, product_id, seller.id)

    update_data = product_in.model_dump(exclude_unset=True)

    if "category_id" in update_data:
        cat = await db.execute(
            select(Category).where(Category.id == product_in.category_id)
        )
        category = cat.scalars().first()
        check_category_exists(category)

    for field, value in update_data.items():
        setattr(product, field, value)

    await db.commit()
    await db.refresh(product, ["images"])

    # WRITE-THROUGH: cache
    await set_cache(
        redis_client,
        f"product:{product.id}",
        serialize_product(product),
        ttl=120
    )

    await invalidate_pattern(redis_client, "products:*")

    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis)
):
    check_is_seller(current_user.role_id)

    seller = await get_seller_profile(db, current_user.id)

    product = await get_product(db, product_id, seller.id)

    from sqlalchemy import delete
    from app.models.cart import Cart
    from app.models.order import Order
    from app.models.return_request import Return
    from app.models.review import Review

    # Find all orders for this product to clean up child relations (returns, reviews)
    order_ids_stmt = select(Order.id).where(Order.product_id == product_id)
    order_ids_result = await db.execute(order_ids_stmt)
    order_ids = order_ids_result.scalars().all()

    if order_ids:
        await db.execute(delete(Return).where(Return.order_id.in_(order_ids)))
        await db.execute(delete(Review).where(Review.order_id.in_(order_ids)))
        await db.execute(delete(Order).where(Order.id.in_(order_ids)))

    # Clean up cart items for this product
    await db.execute(delete(Cart).where(Cart.product_id == product_id))

    await db.delete(product)
    await db.commit()

    # evict deleted product
    await redis_client.delete(f"product:{product.id}")
    await invalidate_pattern(redis_client, "products:*")
    return



@router.post(
    "/{product_id}/images",
    response_model=ProductImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_product_image(
    product_id: int,
    image_url: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_is_seller(current_user.role_id)

    seller = await get_seller_profile(db, current_user.id)
    product = await get_product(db, product_id, seller.id)

    new_image = ProductImage(url=image_url, product_id=product_id)
    db.add(new_image)
    await db.commit()
    await db.refresh(new_image)
    return new_image


# ----------------------------- CUSTOMER & SELLER DISCOVERY ---------------


@router.get("/", response_model=List[ProductResponse])
async def search_products(
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):

    # Try cache
    cache_key = f"procducts:cat={category_id}:search={search}"

    cached = await get_cached(redis_client, cache_key)
    if cached:
        return cached

    query = select(Product).where(
        Product.is_verified == True,
        Product.status == "active"
    ).options(selectinload(Product.images))

    if category_id:
        query = query.where(Product.category_id == category_id)

    if search:
        # Using GIN -> Generalized Inverted Index
        query = query.where(
            Product.search_vector.op('@@')
            (func.plainto_tsquery('english', search))
        )

    result = await db.execute(query)
    products = result.scalars().all()

    # add to cache
    await set_cache(
        redis_client,
        cache_key,
        [serialize_product(p) for p in products],
        ttl=60
    )

    return products


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product_details(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    # Try cache
    cache_key = f"product:{product_id}"
    cached = await get_cached(redis_client, cache_key)
    if cached:
        return cached

    result = await db.execute(
        select(Product)
        .where(
            Product.id == product_id,
            Product.is_verified == True,
            Product.status == "active"
        )
        .options(selectinload(Product.images))
    )
    product = result.scalars().first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    # add to cache
    await set_cache(
        redis_client,
        cache_key,
        serialize_product(product),
        ttl=120
    )
    return product

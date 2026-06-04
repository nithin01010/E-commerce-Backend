from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from app.schemas.pagination import PaginatedResponse
import redis.asyncio as redis
from app.core.cache import get_cached, serialize_review, set_cache
from app.core.cache import invalidate_pattern
from app.core.database import get_db
from app.models.user import User
from app.models.customer import Customer
from app.models.seller import Seller
from app.models.product import Product
from app.models.order import Order
from app.models.review import Review
from app.schemas.review import ReviewCreate, ReviewResponse
from app.api.deps import get_current_user, get_redis

from fastapi_limiter.depends import RateLimiter
from pyrate_limiter import Rate, Duration, Limiter


router = APIRouter()


# ----------------------------HELPER FUCTION-----------------------------


async def get_customer_profile(db: AsyncSession, user_id: int) -> Customer:
    result = await db.execute(
        select(Customer).where(Customer.user_id == user_id)
    )
    customer = result.scalars().first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="""Customer profile not found.
            Please complete onboarding first."""
        )
    return customer


def check_auth(role_id):
    if role_id != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can write reviews"
        )


def check_order(order):
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )


async def check_review_exists(db, order_id):
    result = await db.execute(
        select(Review).where(
            Review.order_id == order_id
        )
    )
    review = result.scalars().first()
    if review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already reviewed this order"
        )


async def update_product_rating(db, order: Order):
    review = await db.execute(
        select(Review).join(Order).where(
            Order.product_id == order.product_id
        )
    )
    prod_reviw = review.scalars().all()
    tot_rating = sum(r.rating for r in prod_reviw)
    avg = tot_rating / len(prod_reviw) if prod_reviw else 0.0

    prod_result = await db.execute(
        select(Product).where(
            Product.id == order.product_id
        )
    )
    product = prod_result.scalars().first()
    product.rating = avg


async def update_seller_rating(db, order):
    seller_reviews_result = await db.execute(
        select(Review).join(Order).where(Order.seller_id == order.seller_id)
    )
    seller_reviews = seller_reviews_result.scalars().all()
    total_seller_rating = sum(r.rating for r in seller_reviews)
    avg = total_seller_rating / len(seller_reviews) if seller_reviews else 0.0
    sell_result = await db.execute(
        select(Seller).where(Seller.id == order.seller_id)
    )
    seller = sell_result.scalars().first()
    seller.rating = avg


# ------------------------------------------------------------------------

limiter_product = Limiter(Rate(5, Duration.MINUTE))


@router.post(
    "/",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimiter(limiter=limiter_product))]
)
async def create_review(
    review_in: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis)
):
    check_auth(current_user.role_id)

    customer = await get_customer_profile(db, current_user.id)

    order_result = await db.execute(
        select(Order).where(
            Order.id == review_in.order_id,
            Order.customer_id == customer.id
        )
    )

    order = order_result.scalars().first()
    check_order(order)

    await check_review_exists(db, order.id)

    new_review = Review(
        rating=review_in.rating,
        comment=review_in.comment,
        order_id=review_in.order_id
    )
    db.add(new_review)
    await db.commit()
    await db.refresh(new_review)

    await update_product_rating(db, order)
    await update_seller_rating(db, order)

    await db.commit()

    # Invalidate review caches
    await redis_client.delete(f"reviews:product:{order.product_id}")
    await redis_client.delete(f"reviews:seller:{order.seller_id}")

    await redis_client.delete(f"product:{order.product_id}")
    await invalidate_pattern(redis_client, "products:*")

    return new_review


@router.get("/product/{product_id}", response_model=PaginatedResponse[ReviewResponse])
async def get_product_reviews(
    product_id: int,
    cursor: Optional[int] = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    cache_key = f"reviews:product:{product_id}:cursor:{cursor}:limit:{limit}"
    cached = await get_cached(redis_client, cache_key)
    if cached:
        return cached

    query = select(Review).join(Order).where(Order.product_id == product_id)
    
    if cursor:
        query = query.where(Review.id > cursor)
        
    query = query.order_by(Review.id.asc()).limit(limit + 1)
    
    result = await db.execute(query)
    reviews = list(result.scalars().all())
    
    next_cur = None
    if len(reviews) > limit:
        next_cur = reviews[-2].id
        reviews = reviews[:-1]
        
    response_dict = {
        "items": [serialize_review(v) for v in reviews],
        "next_cursor": next_cur
    }
    
    await set_cache(redis_client, cache_key, response_dict, ttl=60)
    return PaginatedResponse(items=reviews, next_cursor=next_cur)


@router.get("/seller/{seller_id}", response_model=PaginatedResponse[ReviewResponse])
async def get_seller_reviews(
    seller_id: int,
    cursor: Optional[int] = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    cache_key = f"reviews:seller:{seller_id}:cursor:{cursor}:limit:{limit}"
    cached = await get_cached(redis_client, cache_key)
    if cached:
        return cached

    query = select(Review).join(Order).where(Order.seller_id == seller_id)
    
    if cursor:
        query = query.where(Review.id > cursor)
        
    query = query.order_by(Review.id.asc()).limit(limit + 1)
    
    result = await db.execute(query)
    reviews = list(result.scalars().all())
    
    next_cur = None
    if len(reviews) > limit:
        next_cur = reviews[-2].id
        reviews = reviews[:-1]
        
    response_dict = {
        "items": [serialize_review(v) for v in reviews],
        "next_cursor": next_cur
    }
    
    await set_cache(redis_client, cache_key, response_dict, ttl=60)
    return PaginatedResponse(items=reviews, next_cursor=next_cur)

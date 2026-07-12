from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.schemas.pagination import PaginatedResponse

from app.core.database import get_db
from app.models.user import User
from app.models.customer import Customer
from app.models.product import Product
from app.models.cart import Cart
from app.schemas.cart import CartItemCreate, CartItemResponse, CartItemUpdate
from app.api.deps import get_current_user
from app.core.config import settings

from fastapi_limiter.depends import RateLimiter
from pyrate_limiter import Rate, Duration, Limiter


router = APIRouter()

# ---------------------- HELPER functions -----------------


async def get_customer_profile(db: AsyncSession, user_id: int) -> Customer:
    result = await db.execute(
        select(Customer).where(
            Customer.user_id == user_id
        )
    )
    customer = result.scalars().first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer profile not found"
        )
    return customer


def check_auth(current_user: User):
    if current_user.role_id != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can have cart"
        )
    return


def check_stock(product, quantity):
    if product.stock < quantity:
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only {product.stock} items in stock"
            )


def check_cart(cart_item):
    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart not found"
        )

# -------------------------------------------------


@router.get("/", response_model=PaginatedResponse[CartItemResponse])
async def get_user_cart(
    cursor: Optional[int] = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    check_auth(current_user)
    customer = await get_customer_profile(db, current_user.id)

    query = select(Cart).where(
        Cart.customer_id == customer.id
    ).options(
        selectinload(Cart.product).selectinload(Product.images)
    )

    if cursor:
        query = query.where(Cart.id > cursor)

    query = query.order_by(Cart.id.asc()).limit(limit + 1)
    
    result = await db.execute(query)
    cart_items = list(result.scalars().all())
    
    next_cur = None
    if len(cart_items) > limit:
        next_cur = cart_items[-2].id
        cart_items = cart_items[:-1]

    return PaginatedResponse(items=cart_items, next_cursor=next_cur)

limiter_add_to_cart = Limiter(Rate(100000, Duration.MINUTE)) if settings.DEBUG else Limiter(Rate(30, Duration.MINUTE))


@router.post(
    "/",
    response_model=CartItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimiter(limiter=limiter_add_to_cart))]
)
async def add_to_cart(
    item_in: CartItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    check_auth(current_user)
    customer = await get_customer_profile(db, current_user.id)

    product_result = await db.execute(
        select(Product).where(
            Product.id == item_in.product_id
        ).options(
            selectinload(Product.images)
        )
    )
    product = product_result.scalars().first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    check_stock(product, item_in.quantity)

    cart_result = await db.execute(
        select(Cart).where(
            Cart.customer_id == customer.id, Cart.product_id == product.id
        ).options(selectinload(
                Cart.product
            ).selectinload(Product.images)
        )
    )
    cart_item_db = cart_result.scalars().first()
    if cart_item_db:
        cart_item = cart_item_db
        check_stock(product, item_in.quantity + cart_item.quantity)
        cart_item.quantity += item_in.quantity
    else:
        cart_item = Cart(
            customer_id=customer.id,
            product_id=item_in.product_id,
            quantity=item_in.quantity
        )
        db.add(cart_item)
    await db.commit()
    
    # Re-fetch with product and images eagerly loaded to prevent lazy-load 500 error
    refreshed = await db.execute(
        select(Cart).where(Cart.id == cart_item.id)
        .options(selectinload(Cart.product).selectinload(Product.images))
    )
    cart_item = refreshed.scalars().first()
    return cart_item


@router.put('/{item_id}', response_model=CartItemResponse)
async def update_cart_item(
    item_id: int,
    item_update: CartItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    check_auth(current_user)

    customer = await get_customer_profile(db, current_user.id)

    cart_result = await db.execute(
        select(Cart).where(
            Cart.id == item_id, Cart.customer_id == customer.id
        ).options(
            selectinload(Cart.product).selectinload(Product.images)
        )
    )

    cart_item = cart_result.scalars().first()

    check_cart(cart_item)

    product_result = await db.execute(
        select(Product).where(
            Product.id == cart_item.product_id
        )
    )
    product = product_result.scalars().first()

    check_stock(product, item_update.quantity)
    cart_item.quantity = item_update.quantity
    await db.commit()
    # Re-fetch with product+images eagerly loaded for response serialization
    refreshed = await db.execute(
        select(Cart).where(Cart.id == item_id)
        .options(selectinload(Cart.product).selectinload(Product.images))
    )
    cart_item = refreshed.scalars().first()
    return cart_item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_cart(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    check_auth(current_user)

    customer = await get_customer_profile(db, current_user.id)

    cart_result = await db.execute(
        select(Cart).where(
            Cart.id == item_id, Cart.customer_id == customer.id
        )
    )
    cart_item = cart_result.scalars().first()
    check_cart(cart_item)
    await db.delete(cart_item)
    await db.commit()
    return

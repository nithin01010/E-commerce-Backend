from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional

from app.schemas.pagination import PaginatedResponse

from app.core.database import get_db
from app.models.user import User
from app.models.product import Product
from app.models.customer import Customer
from app.models.address import Address
from app.models.seller import Seller
from app.models.order import Order
from app.models.cart import Cart
from app.schemas.order import OrderCreate, OrderResponse, OrderStatusUpdate
from app.api.deps import get_current_user
from app.tasks.email import send_order_confirmation_email

from fastapi_limiter.depends import RateLimiter
from pyrate_limiter import Rate, Duration, Limiter


router = APIRouter()


# ------------------------------ helper functions -------------------------


async def get_customer_profile(db: AsyncSession, user_id: int) -> Customer:
    result = await db.execute(select(Customer).where(
        Customer.user_id == user_id
        ))
    customer = result.scalars().first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )
    return customer


async def get_seller_profile(db: AsyncSession, user_id: int) -> Customer:
    result = await db.execute(select(Seller).where(Seller.user_id == user_id))
    seller = result.scalars().first()
    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Seller not found"
        )
    return seller


def check_auth(role_id):
    if role_id != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can check out and place orders",
        )


def check_cart(cart_items):
    if not cart_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your shopping cart is empty",
        )


def check_availability(product):
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product no longer exists"
        )


def check_stock(product, need):
    if product.stock < need:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=product.name + " has only " + str(product.stock)
            + " items left in stock"
        )


# -----------------------------------------------------------------

limiter_checkout = Limiter(Rate(10, Duration.MINUTE))


@router.post(
    "/checkout",
    response_model=List[OrderResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimiter(limiter=limiter_checkout))]
)
async def checkout(
    order_in: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_auth(current_user.role_id)
    customer = await get_customer_profile(db, current_user.id)

    # 1. Verify shipping address exists and belongs to the customer
    addr_result = await db.execute(
        select(Address).where(
            Address.id == order_in.address_id,
            Address.customer_id == customer.id
        )
    )
    address = addr_result.scalars().first()
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shipping address not found or does not belong to you",
        )

    # 2. Get customer's cart
    cart_result = await db.execute(
        select(Cart)
        .where(Cart.customer_id == customer.id)
        .options(selectinload(Cart.product).selectinload(Product.images))
    )

    cart_items = cart_result.scalars().all()
    check_cart(cart_items)

    created_orders = []

    for cart_item in cart_items:
        locked_result = await db.execute(
            select(Product).where(
                Product.id == cart_item.product_id
            ).with_for_update()  # row-level lock
        )
        locked_product = locked_result.scalars().first()
        check_availability(locked_product)
        check_stock(locked_product, cart_item.quantity)

        locked_product.stock -= cart_item.quantity
        total_amount = int(locked_product.price * cart_item.quantity)

        new_order = Order(
            quantity=cart_item.quantity,
            status="Order placed",
            total_amount=total_amount,
            address_id=address.id,
            customer_id=customer.id,
            seller_id=locked_product.seller_id,
            product_id=cart_item.product_id,
        )
        db.add(new_order)
        created_orders.append(new_order)

        await db.delete(cart_item)

    await db.commit()

    for o in created_orders:
        await db.refresh(o)
        send_order_confirmation_email.delay(o.id, current_user.email)
    return created_orders


@router.get("/", response_model=PaginatedResponse[OrderResponse])
async def get_order(
    cursor: Optional[int] = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(Order)
    if current_user.role_id == 1:
        customer = await get_customer_profile(db, current_user.id)
        query = query.where(Order.customer_id == customer.id)
    elif current_user.role_id == 2:
        seller = await get_seller_profile(db, current_user.id)
        query = query.where(Order.seller_id == seller.id)
    elif current_user.role_id == 3:
        pass
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Role not recognized"
        )

    if cursor:
        query = query.where(Order.id > cursor)

    query = query.order_by(Order.id.asc()).limit(limit + 1)
    
    result = await db.execute(query)
    orders = list(result.scalars().all())
    
    next_cur = None
    if len(orders) > limit:
        next_cur = orders[-2].id
        orders = orders[:-1]

    return PaginatedResponse(items=orders, next_cursor=next_cur)


@router.put("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: int,
    status_update: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role_id != 2:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only sellers can update order status",
        )
    seller = await get_seller_profile(db, current_user.id)
    result = await db.execute(
        select(Order).where(
            Order.id == order_id, Order.seller_id == seller.id
        )
    )
    order = result.scalars().first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found or does not belong to you",
        )
    order.status = status_update.status
    await db.commit()
    await db.refresh(order)
    return order

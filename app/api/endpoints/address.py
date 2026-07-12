from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.user import User
from app.models.address import Address
from app.models.customer import Customer
from app.models.seller import Seller
from app.schemas.address import AddressCreate, AddressResponse
from app.api.deps import get_current_user

router = APIRouter()


@router.post(
    '/',
    response_model=AddressResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_address(
    address_in: AddressCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_address = Address(
        full_name=address_in.full_name,
        phone=address_in.phone,
        street=address_in.street,
        city=address_in.city,
        state=address_in.state,
        pincode=address_in.pincode,
        country=address_in.country,
        is_default=address_in.is_default
    )

    if current_user.role_id == 1:
        result = await db.execute(
            select(Customer).where(
                Customer.user_id == current_user.id
            )
        )
        customer = result.scalars().first()

        if not customer:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Customer profile not found"
            )
        new_address.customer_id = customer.id
    elif current_user.role_id == 2:
        result = await db.execute(
            select(Seller).where(
                Seller.user_id == current_user.id
            )
        )
        seller = result.scalars().first()

        if not seller:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Seller profile not found"
            )
        new_address.seller_id = seller.id
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins do not need addresses"
        )

    db.add(new_address)
    await db.commit()
    await db.refresh(new_address)

    return new_address


@router.get('/', response_model=list[AddressResponse])
async def get_my_address(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role_id == 1:
        result = await db.execute(
            select(Customer.id).where(
                Customer.user_id == current_user.id
            )
        )
        customer_id = result.scalars().first()
        addr_result = await db.execute(
            select(Address).where(
                Address.customer_id == customer_id
            )
        )
    elif current_user.role_id == 2:
        result = await db.execute(
            select(Seller.id).where(
                Seller.user_id == current_user.id
            )
        )
        seller_id = result.scalars().first()
        addr_result = await db.execute(
            select(Address).where(
                Address.seller_id == seller_id
            )
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins do not have addresses"
        )
    addresses = addr_result.scalars().all()
    return addresses


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(select(Address).where(Address.id == id))
    address = result.scalars().first()

    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")

    # Security Check: Make sure it belongs to them!
    if current_user.role_id == 1:
        cust_res = await db.execute(
            select(Customer.id).where(
                Customer.user_id == current_user.id
                )
            )
        if address.customer_id != cust_res.scalars().first():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your address")

    elif current_user.role_id == 2:
        sell_res = await db.execute(
            select(Seller.id).where(
                Seller.user_id == current_user.id
                )
            )
        if address.seller_id != sell_res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not your address"
                )

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins cannot delete addresses"
            )

    from sqlalchemy import delete
    from app.models.order import Order
    from app.models.return_request import Return
    from app.models.review import Review

    # Find all orders referencing this address to clean up child relations
    order_ids_stmt = select(Order.id).where(Order.address_id == id)
    order_ids_result = await db.execute(order_ids_stmt)
    order_ids = order_ids_result.scalars().all()

    if order_ids:
        await db.execute(delete(Return).where(Return.order_id.in_(order_ids)))
        await db.execute(delete(Review).where(Review.order_id.in_(order_ids)))
        await db.execute(delete(Order).where(Order.id.in_(order_ids)))

    await db.delete(address)
    await db.commit()

    return None


class new:
    name = 'str'
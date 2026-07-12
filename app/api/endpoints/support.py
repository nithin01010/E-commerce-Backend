from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List

from app.core.database import get_db
from app.models.user import User
from app.models.support import SupportTicket
from app.schemas.support import SupportTicketCreate, SupportTicketUpdate
from app.schemas.support import SupportTicketResponse
from app.api.deps import get_current_user

router = APIRouter()


# -----------------------------HELPER FUNCTIONS-------------------------------


def check_ticket_exists(ticket):
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Support ticket not found."
        )


def check_ticket_access(ticket, current_user: User):
    if ticket.user_id != current_user.id and current_user.role_id != 3:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this support ticket."
        )


async def get_ticket(db: AsyncSession, ticket_id: int) -> SupportTicket:
    result = await db.execute(
        select(SupportTicket)
        .where(SupportTicket.id == ticket_id)
        .options(selectinload(SupportTicket.replies))
    )
    ticket = result.scalars().first()
    check_ticket_exists(ticket)
    return ticket


# -----------------------------------------------------------------------------


@router.post(
    "/",
    response_model=SupportTicketResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_support_ticket(
    ticket_in: SupportTicketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_ticket = SupportTicket(
        subject=ticket_in.subject,
        description=ticket_in.description,
        priority=ticket_in.priority or "medium",
        status="open",
        user_id=current_user.id
    )
    db.add(new_ticket)
    await db.commit()

    # Re-fetch with replies eagerly loaded to avoid async lazy-load error
    result = await db.execute(
        select(SupportTicket)
        .where(SupportTicket.id == new_ticket.id)
        .options(selectinload(SupportTicket.replies))
    )
    new_ticket = result.scalars().first()
    return new_ticket


@router.get("/", response_model=List[SupportTicketResponse])
async def list_support_tickets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role_id == 3:
        result = await db.execute(
            select(SupportTicket).options(selectinload(SupportTicket.replies))
        )
    else:
        result = await db.execute(
            select(SupportTicket)
            .where(SupportTicket.user_id == current_user.id)
            .options(selectinload(SupportTicket.replies))
        )
    return result.scalars().all()


@router.get("/{ticket_id}", response_model=SupportTicketResponse)
async def get_support_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    ticket = await get_ticket(db, ticket_id)
    check_ticket_access(ticket, current_user)
    return ticket


@router.put("/{ticket_id}/status", response_model=SupportTicketResponse)
async def update_support_ticket_status(
    ticket_id: int,
    ticket_update: SupportTicketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    ticket = await get_ticket(db, ticket_id)
    check_ticket_access(ticket, current_user)

    if ticket_update.status:
        ticket.status = ticket_update.status
    if ticket_update.priority:
        ticket.priority = ticket_update.priority

    await db.commit()
    # Re-fetch with replies to avoid lazy-load error on response serialization
    result = await db.execute(
        select(SupportTicket)
        .where(SupportTicket.id == ticket_id)
        .options(selectinload(SupportTicket.replies))
    )
    ticket = result.scalars().first()
    return ticket

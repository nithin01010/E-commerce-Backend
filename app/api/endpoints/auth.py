from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi import Request, Header
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta
import redis.asyncio as redis
from typing import Optional

from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, ForgetPassword
from app.schemas.user import ResetPassword
from app.core.config import settings
from jose import jwt, JWTError
from app.core.security import verify_password, get_password_hash
from app.core.security import create_password_reset_token
from app.core.security import create_access_token, create_refresh_token
from app.api.deps import get_redis, get_current_user

from fastapi_limiter.depends import RateLimiter
from pyrate_limiter import Rate, Duration, Limiter

router = APIRouter()

auth_limiter_register = Limiter(Rate(100000, Duration.HOUR)) if settings.DEBUG else Limiter(Rate(10, Duration.HOUR))


@router.post(
    "/register", response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimiter(limiter=auth_limiter_register))]
)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == user_in.email))
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registerd"
        )

    hashed_pwd = get_password_hash(user_in.password)
    new_user = User(
        email=user_in.email,
        password=hashed_pwd,
        role_id=user_in.role_id
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return new_user

auth_limiter = Limiter(Rate(100000, Duration.MINUTE)) if settings.DEBUG else Limiter(Rate(5, Duration.MINUTE))


@router.post(
    "/login",
    dependencies=[Depends(RateLimiter(limiter=auth_limiter))]
)
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(
            User.email == form_data.username
        )
    )
    user = result.scalars().first()

    if not user or not verify_password(form_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # creeate JWT token
    access_token_expire = timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expire
    )
    ref = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token = create_refresh_token(
        data={"sub": str(user.id)}, expires_delta=ref
    )

    # HTTP Cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 600,
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

    return {
        "message": "Successfully logged in",
        "token_type": "bearer",
        "access_token": access_token,
        "refresh_token": refresh_token
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    redis_client: redis.Redis = Depends(get_redis),
    current_user: User = Depends(get_current_user),
):
    token = request.cookies.get("access_token")
    ref = request.cookies.get("refresh_token")
    # Add token to Redis blacklist with a TTL equal to token expiration
    if token:
        await redis_client.setex(
            f"blacklist:{token}",
            settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, "true"
        )
    if ref:
        await redis_client.setex(
            f"blacklist:{ref}",
            settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, "true"
        )

    # Clear the cookie
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")

    return {"message": "Successfully logged out"}


@router.post("/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
    x_refresh_token: Optional[str] = Header(None)
):
    rf_t = request.cookies.get("refresh_token") or x_refresh_token

    if not rf_t:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing"
        )

    is_blacklisted = await redis_client.get(f"blacklist:{rf_t}")
    if is_blacklisted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked"
        )

    try:
        payload = jwt.decode(
            rf_t, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalars().first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    access_token_expire = timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    new_access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expire
    )

    new_refresh_token_expire = timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
    new_refresh_token = create_refresh_token(
        data={"sub": str(user.id)}, expires_delta=new_refresh_token_expire
    )

    # Blacklist old refresh token
    await redis_client.setex(
        f"blacklist:{rf_t}", settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, "true"
    )

    # Set new cookies
    response.set_cookie(
        key="access_token",
        value=new_access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )

    return {"message": "Token refreshed successfully"}


auth_limiter_forget = Limiter(Rate(100000, Duration.HOUR)) if settings.DEBUG else Limiter(Rate(3, Duration.HOUR))


@router.post(
    "/forgot-password",
    dependencies=[Depends(RateLimiter(auth_limiter_forget))]
)
async def forgot_password(
    forgot_in: ForgetPassword,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(User).where(
            User.email == forgot_in.email
            )
        )
    user = result.scalars().first()
    if not user:
        return {
            "message": "A password reset link has been sent."
            }

    reset_token = create_password_reset_token(user.email)

    print("\n=======================================================")
    print(f"PASSWORD RESET LINK FOR {user.email}:")
    print(f"http://localhost:5173/reset-password?token={reset_token}")
    print("=======================================================\n")

    return {"message": """If the email exists,
    a password reset link has been sent."""}

auth_limiter_reset = Limiter(Rate(100000, Duration.HOUR)) if settings.DEBUG else Limiter(Rate(3, Duration.HOUR))


@router.post(
    "/reset-password",
    dependencies=[Depends(RateLimiter(auth_limiter_reset))]
)
async def reset_password(
    reset_in: ResetPassword,
    db: AsyncSession = Depends(get_db)
):
    try:
        payload = jwt.decode(
            reset_in.token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        email: str = payload.get("sub")
        token_type: str = payload.get("type")

        if email is None or token_type != "resst":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token"
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found or inactive"
        )

    hashed_pwd = get_password_hash(reset_in.new_password)
    user.password = hashed_pwd
    await db.commit()

    return {"message": "Password has been reset successfully"}


@router.get("/role_id", response_model=int)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user.role_id

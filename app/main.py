from fastapi import FastAPI
from app.core.config import settings
from app.api.endpoints import auth, customer, seller, address
from app.api.endpoints import category, cart, order, review
from app.api.endpoints import product, support, admin
from fastapi.middleware.cors import CORSMiddleware
import importlib

from fastapi.exceptions import ResponseValidationError
from fastapi.responses import JSONResponse


return_endpoint = importlib.import_module("app.api.endpoints.return")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION
)

# Completely disable/pause rate limiting if in DEBUG mode for load testing
if settings.DEBUG:
    from pyrate_limiter import Limiter
    async def dummy_acquire_async(*args, **kwargs):
        return True
    def dummy_acquire(*args, **kwargs):
        return True
    Limiter.try_acquire_async = dummy_acquire_async
    Limiter.try_acquire = dummy_acquire

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


app.include_router(
    auth.router,
    prefix="/auth",
    tags=["Auth"]
)

app.include_router(
    customer.router,
    prefix='/customer',
    tags=["Customers"]
)

app.include_router(
    seller.router,
    prefix='/seller',
    tags=["Sellers"]
)


app.include_router(
    address.router,
    prefix="/addresses",
    tags=["Addresses"]
)

app.include_router(
    category.router,
    prefix='/categories',
    tags=["Categories"]
)

app.include_router(
    cart.router,
    prefix="/cart",
    tags=["Cart"]
)

app.include_router(
    order.router,
    prefix="/orders",
    tags=["Orders"]
)

app.include_router(
    review.router,
    prefix="/reviews",
    tags=["Reviews"]
)

app.include_router(
    product.router,
    prefix="/products",
    tags=["Products"]
)

app.include_router(
    return_endpoint.router,
    prefix="/returns",
    tags=["Returns"]
)

app.include_router(
    support.router,
    prefix="/support",
    tags=["Support"]
)

app.include_router(
    admin.router,
    prefix="/admin",
    tags=["Admin"]
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.exception_handler(ResponseValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc.errors())}
    )


# Monkeypatch fastapi-limiter to avoid AttributeError on _IncludedRouter in newer FastAPI versions
try:
    import fastapi_limiter.depends
    from fastapi import Request, Response
    original_limiter_call = fastapi_limiter.depends.RateLimiter.__call__

    async def patched_limiter_call(self, request: Request, response: Response):
        # Mutate the underlying router.routes list in-place to avoid read-only property error
        original_routes = list(request.app.router.routes)
        filtered_routes = [r for r in original_routes if hasattr(r, "path") and hasattr(r, "methods")]
        request.app.router.routes.clear()
        request.app.router.routes.extend(filtered_routes)
        try:
            return await original_limiter_call(self, request, response)
        finally:
            request.app.router.routes.clear()
            request.app.router.routes.extend(original_routes)

    fastapi_limiter.depends.RateLimiter.__call__ = patched_limiter_call
except Exception as e:
    import logging
    logging.warning(f"Failed to apply fastapi-limiter monkeypatch: {e}")


# Monkeypatch bcrypt to prevent ValueError with newer versions in passlib's startup checks
try:
    import bcrypt
    original_hashpw = bcrypt.hashpw

    def patched_hashpw(password, salt):
        if isinstance(password, bytes) and len(password) > 72:
            password = password[:72]
        elif isinstance(password, str) and len(password) > 72:
            password = password[:72]
        return original_hashpw(password, salt)

    bcrypt.hashpw = patched_hashpw
except Exception as e:
    import logging
    logging.warning(f"Failed to apply bcrypt monkeypatch: {e}")






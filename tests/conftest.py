import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from typing import AsyncGenerator
import redis.asyncio as redis

from app.main import app
from app.core.database import Base, get_db
from app.api.deps import get_redis

# Test database URL (local port 5433 where Postgres 13 is running)
TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/ecommerce_test"

engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    pool_pre_ping=True
)

TestingSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Set up the test database schema
@pytest.fixture(scope="session", autouse=True)
async def setup_test_db():
    async with engine.begin() as conn:
        # Create all tables (including the GIN index from models)
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

# Override the database dependency
@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        yield session

# Provide the test client
@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    # Dependency overrides
    app.dependency_overrides[get_db] = lambda: db_session
    
    # We can mock Redis to avoid needing a clean Redis instance per test
    class MockRedis:
        async def get(self, key): return None
        async def set(self, key, value, ex=None): return True
        async def setex(self, key, time, value): return True
        async def close(self): pass

    app.dependency_overrides[get_redis] = lambda: MockRedis()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()

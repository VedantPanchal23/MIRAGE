"""SQLAlchemy async session and database engine configuration with tenant RLS support."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from shared.config import get_settings

settings = get_settings()


def create_app_engine(url: str | None = None, poolclass: Any = None) -> AsyncEngine:
    """Create a configured async engine for PostgreSQL with connection pooling."""
    target_url = url or settings.database_url
    if poolclass is not None:
        return create_async_engine(
            target_url,
            echo=settings.debug and settings.environment.value == "development",
            poolclass=poolclass,
        )
    return create_async_engine(
        target_url,
        echo=settings.debug and settings.environment.value == "development",
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


engine: AsyncEngine = create_app_engine()

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy ORM models."""

    pass


def reset_sessionmaker(new_engine: AsyncEngine) -> None:
    """Rebind AsyncSessionLocal to a new engine (used for testing / container binding)."""
    global engine, AsyncSessionLocal
    engine = new_engine
    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for scoped async database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_tenant_session(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session with transaction-scoped tenant RLS context.

    Uses PostgreSQL transaction-local parameterization:
        SELECT set_config('app.current_tenant_id', :tenant_id, true)
    The 'true' flag ensures the variable is strictly local to the active transaction
    and reverts to default/empty immediately upon COMMIT or ROLLBACK.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            yield session


async def check_database_connection() -> bool:
    """Execute a lightweight SELECT 1 to verify database connectivity without leaking data."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

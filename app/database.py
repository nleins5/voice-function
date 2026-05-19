import os
import base64
import json
import ssl as _ssl
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


def _database_disabled() -> bool:
    return os.getenv("DISABLE_DATABASE", "").strip().lower() in {"1", "true", "yes", "on"} or os.getenv("VERCEL") == "1"


def _extract_prisma_database_url(url: str) -> str:
    """Convert Prisma Accelerate local URLs into the underlying PostgreSQL URL."""
    if not url.startswith("prisma+postgres://"):
        return url

    parsed = urlparse(url)
    api_key = parse_qs(parsed.query).get("api_key", [""])[0]
    if not api_key:
        return url

    padding = "=" * (-len(api_key) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{api_key}{padding}").decode("utf-8")
        payload = json.loads(decoded)
    except Exception:
        return url

    return payload.get("databaseUrl") or url


def _normalize_database_url(url: str) -> str:
    url = _extract_prisma_database_url(url)

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.pop("sslmode", None)
    clean_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=clean_query))


def _build_engine():
    """Build async engine with proper SSL handling for Neon/PostgreSQL."""
    clean_url = _normalize_database_url(DATABASE_URL)

    connect_args = {}
    parsed_url = urlparse(clean_url)
    is_local_db = parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}

    # Create SSL context for hosted PostgreSQL. Local dev Postgres commonly rejects SSL upgrades.
    ssl_context = _ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = _ssl.CERT_NONE
    if not is_local_db:
        connect_args["ssl"] = ssl_context

    return create_async_engine(
        clean_url,
        echo=False,
        pool_pre_ping=True,       # Detect stale connections before use
        pool_size=5,              # Base pool connections
        max_overflow=10,          # Extra connections under load
        pool_recycle=1800,        # Recycle connections every 30min (prevents Neon/Supabase idle timeouts)
        pool_timeout=10,          # Wait max 10s for a connection from pool
        connect_args=connect_args,
    )


engine = None if _database_disabled() else _build_engine()

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False) if engine else None


async def get_db():
    """FastAPI dependency — yields an async DB session."""
    if AsyncSessionLocal is None:
        yield None
        return

    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Create all tables on startup."""
    if engine is None:
        return

    from app.db_models import User, Conversation, ChatMessage, RequestLog  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

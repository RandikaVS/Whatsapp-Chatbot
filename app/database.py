# app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # tests connection before using it — handles dropped connections
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # prevents "detached instance" errors after commit
)

class Base(DeclarativeBase):
    pass



# This is a FastAPI dependency — the "async with" pattern is the
# correct way to manage async SQLAlchemy sessions. It guarantees
# the session is properly closed even if an exception occurs.
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
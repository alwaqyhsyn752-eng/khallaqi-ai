"""Generic async repository base class."""
from __future__ import annotations

from typing import Any, Generic, Optional, Sequence, Type, TypeVar

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session_factory
from app.logging_config import get_logger

log = get_logger(__name__)

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    """Generic async CRUD repository.

    Subclasses must set `model` to the SQLAlchemy model class.
    """

    model: Type[ModelT]

    def __init__(self, session: Optional[AsyncSession] = None) -> None:
        """If `session` is provided, use it. Otherwise create a fresh one."""
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> "BaseRepository[ModelT]":
        if self._session is None:
            factory = get_session_factory()
            self._session = factory()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._owns_session and self._session is not None:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
            await self._session.close()
            self._session = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Repository used without context manager")
        return self._session

    # ─── Read ───
    async def get(self, id_: Any) -> Optional[ModelT]:
        """Fetch a single row by primary key."""
        return await self.session.get(self.model, id_)

    async def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[ModelT]:
        """Return all rows with pagination."""
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self) -> int:
        """Count all rows in the table."""
        stmt = select(func.count()).select_from(self.model)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    # ─── Write ───
    async def create(self, **kwargs: Any) -> ModelT:
        """Insert a new row."""
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def update(self, instance: ModelT, **kwargs: Any) -> ModelT:
        """Update fields on an existing instance."""
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        """Delete a single instance."""
        await self.session.delete(instance)
        await self.session.flush()

    async def delete_by_id(self, id_: Any) -> int:
        """Delete by primary key. Returns row count."""
        stmt = sa_delete(self.model).where(self.model.id == id_)
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def commit(self) -> None:
        """Explicit commit."""
        await self.session.commit()

    async def rollback(self) -> None:
        """Explicit rollback."""
        await self.session.rollback()

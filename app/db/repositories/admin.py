"""Admin repositories — CRUD for admin panel entities."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import delete, func, or_, select

from app.db.repositories.base import BaseRepository
from app.logging_config import get_logger
from app.models.db_models import (
    AdminAccount,
    AdminAuditLog,
    AdminSession,
    AppUser,
    Chat,
    ImpersonationLog,
    Message,
    Notification,
    SystemRule,
    SystemSetting,
)

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Password hashing (PBKDF2 — no external deps)
# ═══════════════════════════════════════════════════════════════════
def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with random salt."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"pbkdf2_sha256$200000${salt}${digest.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        parts = hashed.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        _, iters, salt, expected = parts
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
        return secrets.compare_digest(digest.hex(), expected)
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# Admin Accounts
# ═══════════════════════════════════════════════════════════════════
class AdminAccountRepository(BaseRepository[AdminAccount]):
    """Admin accounts repository."""

    model = AdminAccount

    async def find_by_username(self, username: str) -> Optional[AdminAccount]:
        stmt = select(AdminAccount).where(AdminAccount.username == username)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_admin(self, username: str, password: str, is_super: bool = False) -> AdminAccount:
        admin = await self.create(
            username=username,
            password_hash=hash_password(password),
            is_super=is_super,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        await self.session.flush()
        return admin

    async def update_login(self, admin: AdminAccount) -> None:
        admin.last_login_at = datetime.utcnow()
        await self.session.flush()

    async def ensure_default_admin(self, username: str, password: str) -> AdminAccount:
        """Ensure an admin exists with given credentials (idempotent)."""
        existing = await self.find_by_username(username)
        if existing:
            return existing
        return await self.create_admin(username, password, is_super=True)


# ═══════════════════════════════════════════════════════════════════
# Admin Sessions
# ═══════════════════════════════════════════════════════════════════
class AdminSessionRepository(BaseRepository[AdminSession]):
    """Admin session tokens repository."""

    model = AdminSession

    async def create_session(
        self,
        admin_id: int,
        hours: int = 24,
        ip: Optional[str] = None,
        ua: Optional[str] = None,
    ) -> AdminSession:
        token = secrets.token_urlsafe(48)
        session = await self.create(
            token=token,
            admin_id=admin_id,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=hours),
            ip_address=ip,
            user_agent=(ua or "")[:500],
        )
        await self.session.flush()
        return session

    async def find_by_token(self, token: str) -> Optional[AdminSession]:
        stmt = select(AdminSession).where(
            AdminSession.token == token,
            AdminSession.expires_at > datetime.utcnow(),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_token(self, token: str) -> bool:
        stmt = delete(AdminSession).where(AdminSession.token == token)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return bool(result.rowcount)

    async def cleanup_expired(self) -> int:
        stmt = delete(AdminSession).where(AdminSession.expires_at < datetime.utcnow())
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)


# ═══════════════════════════════════════════════════════════════════
# App Users (tracked users)
# ═══════════════════════════════════════════════════════════════════
class AppUserRepository(BaseRepository[AppUser]):
    """App users repository."""

    model = AppUser

    async def upsert_on_activity(
        self,
        user_id: str,
        ip: Optional[str] = None,
        ua: Optional[str] = None,
    ) -> AppUser:
        stmt = select(AppUser).where(AppUser.user_id == user_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        now = datetime.utcnow()
        if user:
            user.last_seen_at = now
            if ip:
                user.ip_address = ip[:45]
            if ua:
                user.user_agent = ua[:500]
            user.total_messages = (user.total_messages or 0) + 1
            await self.session.flush()
            return user
        user = await self.create(
            user_id=user_id,
            ip_address=(ip or "")[:45] or None,
            user_agent=(ua or "")[:500] or None,
            created_at=now,
            last_seen_at=now,
            total_messages=1,
            total_chats=0,
        )
        await self.session.flush()
        return user

    async def list_all(self, limit: int = 200, offset: int = 0) -> List[AppUser]:
        stmt = select(AppUser).order_by(AppUser.last_seen_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_user_id(self, user_id: str) -> Optional[AppUser]:
        stmt = select(AppUser).where(AppUser.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_blocked(self, user_id: str, blocked: bool) -> bool:
        user = await self.find_by_user_id(user_id)
        if not user:
            return False
        user.is_blocked = blocked
        await self.session.flush()
        return True

    async def is_blocked(self, user_id: str) -> bool:
        user = await self.find_by_user_id(user_id)
        return bool(user and user.is_blocked)


# ═══════════════════════════════════════════════════════════════════
# System Rules
# ═══════════════════════════════════════════════════════════════════
class SystemRuleRepository(BaseRepository[SystemRule]):
    """Admin-controlled rules that shape AI behavior."""

    model = SystemRule

    async def list_all(self) -> List[SystemRule]:
        stmt = select(SystemRule).order_by(SystemRule.priority.desc(), SystemRule.id.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self) -> List[SystemRule]:
        stmt = (
            select(SystemRule)
            .where(SystemRule.is_active == True)  # noqa: E712
            .order_by(SystemRule.priority.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_rule(
        self,
        name: str,
        rule_type: str,
        pattern: Optional[str] = None,
        response: Optional[str] = None,
        description: Optional[str] = None,
        priority: int = 100,
    ) -> SystemRule:
        rule = await self.create(
            name=name[:100],
            description=description,
            rule_type=rule_type,
            pattern=(pattern or "")[:500] or None,
            response=response,
            is_active=True,
            priority=priority,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await self.session.flush()
        return rule

    async def toggle(self, rule_id: int) -> Optional[SystemRule]:
        rule = await self.get(rule_id)
        if not rule:
            return None
        rule.is_active = not rule.is_active
        await self.session.flush()
        return rule

    async def delete_rule(self, rule_id: int) -> bool:
        stmt = delete(SystemRule).where(SystemRule.id == rule_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return bool(result.rowcount)


# ═══════════════════════════════════════════════════════════════════
# Notifications
# ═══════════════════════════════════════════════════════════════════
class NotificationRepository(BaseRepository[Notification]):
    """Admin notifications."""

    model = Notification

    async def create_notification(
        self,
        kind: str,
        title: str,
        body: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Notification:
        n = await self.create(
            kind=kind,
            title=title[:200],
            body=body,
            user_id=user_id,
            is_read=False,
            created_at=datetime.utcnow(),
        )
        await self.session.flush()
        return n

    async def list_recent(self, limit: int = 100) -> List[Notification]:
        stmt = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def unread_count(self) -> int:
        stmt = select(func.count()).select_from(Notification).where(Notification.is_read == False)  # noqa: E712
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def mark_all_read(self) -> int:
        stmt = select(Notification).where(Notification.is_read == False)  # noqa: E712
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        for n in rows:
            n.is_read = True
        await self.session.flush()
        return len(rows)


# ═══════════════════════════════════════════════════════════════════
# Audit Log
# ═══════════════════════════════════════════════════════════════════
class AuditLogRepository(BaseRepository[AdminAuditLog]):
    """Immutable admin audit log."""

    model = AdminAuditLog

    async def log(
        self,
        action: str,
        admin_id: Optional[int] = None,
        admin_username: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[dict] = None,
        ip: Optional[str] = None,
    ) -> AdminAuditLog:
        entry = await self.create(
            admin_id=admin_id,
            admin_username=admin_username,
            action=action[:80],
            target_type=target_type,
            target_id=target_id,
            details=json.dumps(details or {}, ensure_ascii=False),
            ip_address=(ip or "")[:45] or None,
            created_at=datetime.utcnow(),
        )
        await self.session.flush()
        return entry

    async def list_recent(self, limit: int = 200) -> List[AdminAuditLog]:
        stmt = select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ═══════════════════════════════════════════════════════════════════
# Impersonation Log
# ═══════════════════════════════════════════════════════════════════
class ImpersonationRepository(BaseRepository[ImpersonationLog]):
    """Log of admin messages sent as the AI."""

    model = ImpersonationLog

    async def log(
        self,
        admin_id: Optional[int],
        admin_username: Optional[str],
        chat_id: str,
        user_id: str,
        content: str,
        message_id: Optional[int] = None,
    ) -> ImpersonationLog:
        entry = await self.create(
            admin_id=admin_id,
            admin_username=admin_username,
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            content=content,
            created_at=datetime.utcnow(),
        )
        await self.session.flush()
        return entry

    async def list_recent(self, limit: int = 200) -> List[ImpersonationLog]:
        stmt = select(ImpersonationLog).order_by(ImpersonationLog.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ═══════════════════════════════════════════════════════════════════
# Helpers for admin viewing chats
# ═══════════════════════════════════════════════════════════════════
class AdminChatRepository(BaseRepository[Chat]):
    """Read-only chat repository for the admin panel."""

    model = Chat

    async def list_all_chats(self, limit: int = 200, offset: int = 0) -> List[Chat]:
        stmt = select(Chat).order_by(Chat.updated_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_user_chats(self, user_id: str, limit: int = 100) -> List[Chat]:
        stmt = select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_messages(self, chat_id: str, limit: int = 500) -> List[Message]:
        stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.id.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

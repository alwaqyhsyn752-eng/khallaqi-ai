"""Admin service — business logic for the admin dashboard."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.repositories.admin import (
    AdminAccountRepository,
    AdminChatRepository,
    AdminSessionRepository,
    AppUserRepository,
    AuditLogRepository,
    ImpersonationRepository,
    NotificationRepository,
    SystemRuleRepository,
    verify_password,
)
from app.db.repositories.chat import MessageRepository
from app.exceptions import UnauthorizedError, ValidationError
from app.logging_config import get_logger

log = get_logger(__name__)


class AdminService:
    """Orchestrates admin panel operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._accounts = AdminAccountRepository(session=session)
        self._sessions = AdminSessionRepository(session=session)
        self._users = AppUserRepository(session=session)
        self._rules = SystemRuleRepository(session=session)
        self._notifs = NotificationRepository(session=session)
        self._audit = AuditLogRepository(session=session)
        self._impersonations = ImpersonationRepository(session=session)
        self._chats = AdminChatRepository(session=session)
        self._messages = MessageRepository(session=session)

    # ═══════════════════════════════════════════════════════════════
    # Auth
    # ═══════════════════════════════════════════════════════════════
    async def bootstrap_default_admin(self) -> None:
        """Ensure the default admin account exists (idempotent)."""
        s = get_settings()
        if not s.admin_username or not s.admin_password:
            return
        await self._accounts.ensure_default_admin(s.admin_username, s.admin_password)
        await self._session.commit()
        log.info("admin.bootstrap_done", username=s.admin_username)

    async def login(
        self,
        username: str,
        password: str,
        ip: Optional[str] = None,
        ua: Optional[str] = None,
    ) -> dict:
        """Authenticate admin. Returns session info or raises."""
        admin = await self._accounts.find_by_username(username)
        if not admin or not admin.is_active:
            raise UnauthorizedError("بيانات الدخول غير صحيحة")
        if not verify_password(password, admin.password_hash):
            raise UnauthorizedError("بيانات الدخول غير صحيحة")

        s = get_settings()
        session = await self._sessions.create_session(
            admin_id=admin.id,
            hours=s.admin_session_hours,
            ip=ip,
            ua=ua,
        )
        await self._accounts.update_login(admin)
        await self._audit.log(
            action="admin_login",
            admin_id=admin.id,
            admin_username=admin.username,
            ip=ip,
        )
        await self._session.commit()

        return {
            "token": session.token,
            "expires_at": session.expires_at.isoformat(),
            "admin": {
                "id": admin.id,
                "username": admin.username,
                "is_super": admin.is_super,
            },
        }

    async def verify_token(self, token: str) -> dict:
        """Verify an admin session token."""
        if not token:
            raise UnauthorizedError("جلسة غير صحيحة")
        session = await self._sessions.find_by_token(token)
        if not session:
            raise UnauthorizedError("الجلسة منتهية أو غير صحيحة")
        admin = await self._accounts.get(session.admin_id)
        if not admin or not admin.is_active:
            raise UnauthorizedError("الحساب غير مفعّل")
        return {
            "id": admin.id,
            "username": admin.username,
            "is_super": admin.is_super,
        }

    async def logout(self, token: str, ip: Optional[str] = None) -> None:
        """Destroy a session token."""
        session = await self._sessions.find_by_token(token)
        if session:
            admin = await self._accounts.get(session.admin_id)
            await self._audit.log(
                action="admin_logout",
                admin_id=admin.id if admin else None,
                admin_username=admin.username if admin else None,
                ip=ip,
            )
        await self._sessions.delete_by_token(token)
        await self._session.commit()

    # ═══════════════════════════════════════════════════════════════
    # Users
    # ═══════════════════════════════════════════════════════════════
    async def list_users(self, limit: int = 200) -> List[dict]:
        users = await self._users.list_all(limit=limit)
        return [
            {
                "id": u.id,
                "user_id": u.user_id,
                "display_name": u.display_name,
                "ip_address": u.ip_address,
                "is_blocked": u.is_blocked,
                "total_messages": u.total_messages,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
            }
            for u in users
        ]

    async def block_user(self, user_id: str, admin: dict, ip: Optional[str] = None) -> bool:
        ok = await self._users.set_blocked(user_id, True)
        if ok:
            await self._notifs.create_notification(
                kind="user_blocked",
                title=f"تم حظر المستخدم {user_id}",
                user_id=user_id,
            )
            await self._audit.log(
                action="user_blocked",
                admin_id=admin["id"],
                admin_username=admin["username"],
                target_type="user",
                target_id=user_id,
                ip=ip,
            )
            await self._session.commit()
        return ok

    async def unblock_user(self, user_id: str, admin: dict, ip: Optional[str] = None) -> bool:
        ok = await self._users.set_blocked(user_id, False)
        if ok:
            await self._audit.log(
                action="user_unblocked",
                admin_id=admin["id"],
                admin_username=admin["username"],
                target_type="user",
                target_id=user_id,
                ip=ip,
            )
            await self._session.commit()
        return ok

    async def is_user_blocked(self, user_id: str) -> bool:
        return await self._users.is_blocked(user_id)

    # ═══════════════════════════════════════════════════════════════
    # Chats
    # ═══════════════════════════════════════════════════════════════
    async def list_chats(self, user_id: Optional[str] = None, limit: int = 200) -> List[dict]:
        chats = (
            await self._chats.list_user_chats(user_id, limit=limit)
            if user_id
            else await self._chats.list_all_chats(limit=limit)
        )
        return [
            {
                "id": c.id,
                "user_id": c.user_id,
                "title": c.title,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in chats
        ]

    async def get_chat_messages(self, chat_id: str) -> List[dict]:
        messages = await self._chats.get_messages(chat_id, limit=500)
        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "type": m.message_type,
                "source": m.source,
                "is_admin_message": bool(getattr(m, "is_admin_message", False)),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]

    # ═══════════════════════════════════════════════════════════════
    # Impersonation — send a message to a chat AS THE AI
    # ═══════════════════════════════════════════════════════════════
    async def impersonate_send(
        self,
        admin: dict,
        chat_id: str,
        user_id: str,
        content: str,
        ip: Optional[str] = None,
    ) -> dict:
        """Insert a message into a chat as if the AI wrote it."""
        if not content.strip():
            raise ValidationError("النص مطلوب")

        # Verify chat belongs to user
        if not await self._chats.belongs_to_user(chat_id, user_id):
            raise ValidationError("المحادثة لا تنتمي لهذا المستخدم")

        msg = await self._messages.add(
            chat_id=chat_id,
            role="assistant",
            content=content,
            message_type="text",
            source="admin",
        )
        # Mark as admin message
        try:
            msg.is_admin_message = True
            msg.admin_id = admin["id"]
            await self._session.flush()
        except Exception:
            pass

        await self._impersonations.log(
            admin_id=admin["id"],
            admin_username=admin["username"],
            chat_id=chat_id,
            user_id=user_id,
            content=content,
            message_id=msg.id if msg else None,
        )
        await self._audit.log(
            action="impersonate_send",
            admin_id=admin["id"],
            admin_username=admin["username"],
            target_type="chat",
            target_id=chat_id,
            details={"user_id": user_id, "len": len(content)},
            ip=ip,
        )
        await self._session.commit()
        return {
            "message_id": msg.id if msg else None,
            "chat_id": chat_id,
            "user_id": user_id,
            "content": content,
        }

    # ═══════════════════════════════════════════════════════════════
    # Rules
    # ═══════════════════════════════════════════════════════════════
    async def list_rules(self) -> List[dict]:
        rules = await self._rules.list_all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "rule_type": r.rule_type,
                "pattern": r.pattern,
                "response": r.response,
                "is_active": r.is_active,
                "priority": r.priority,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rules
        ]

    async def create_rule(self, admin: dict, data: dict, ip: Optional[str] = None) -> dict:
        name = str(data.get("name", "")).strip()
        rule_type = str(data.get("rule_type", "")).strip()
        if not name or rule_type not in ("refuse", "allow", "keyword", "system_prompt"):
            raise ValidationError("بيانات القاعدة غير صحيحة")

        rule = await self._rules.create_rule(
            name=name,
            rule_type=rule_type,
            pattern=data.get("pattern"),
            response=data.get("response"),
            description=data.get("description"),
            priority=int(data.get("priority", 100)),
        )
        await self._audit.log(
            action="rule_created",
            admin_id=admin["id"],
            admin_username=admin["username"],
            target_type="rule",
            target_id=str(rule.id),
            ip=ip,
        )
        await self._session.commit()
        return {"id": rule.id, "name": rule.name, "rule_type": rule.rule_type}

    async def toggle_rule(self, rule_id: int, admin: dict, ip: Optional[str] = None) -> Optional[dict]:
        rule = await self._rules.toggle(rule_id)
        if not rule:
            return None
        await self._audit.log(
            action="rule_toggled",
            admin_id=admin["id"],
            admin_username=admin["username"],
            target_type="rule",
            target_id=str(rule_id),
            details={"is_active": rule.is_active},
            ip=ip,
        )
        await self._session.commit()
        return {"id": rule.id, "is_active": rule.is_active}

    async def delete_rule(self, rule_id: int, admin: dict, ip: Optional[str] = None) -> bool:
        ok = await self._rules.delete_rule(rule_id)
        if ok:
            await self._audit.log(
                action="rule_deleted",
                admin_id=admin["id"],
                admin_username=admin["username"],
                target_type="rule",
                target_id=str(rule_id),
                ip=ip,
            )
            await self._session.commit()
        return ok

    # ═══════════════════════════════════════════════════════════════
    # Notifications
    # ═══════════════════════════════════════════════════════════════
    async def list_notifications(self, limit: int = 100) -> dict:
        notifs = await self._notifs.list_recent(limit=limit)
        unread = await self._notifs.unread_count()
        return {
            "unread_count": unread,
            "items": [
                {
                    "id": n.id,
                    "kind": n.kind,
                    "title": n.title,
                    "body": n.body,
                    "user_id": n.user_id,
                    "is_read": n.is_read,
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                }
                for n in notifs
            ],
        }

    async def mark_notifications_read(self, admin: dict) -> int:
        count = await self._notifs.mark_all_read()
        await self._session.commit()
        return count

    # ═══════════════════════════════════════════════════════════════
    # Audit / Impersonation logs
    # ═══════════════════════════════════════════════════════════════
    async def list_audit(self, limit: int = 200) -> List[dict]:
        entries = await self._audit.list_recent(limit=limit)
        return [
            {
                "id": e.id,
                "admin_username": e.admin_username,
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "details": e.details,
                "ip_address": e.ip_address,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ]

    async def list_impersonations(self, limit: int = 200) -> List[dict]:
        entries = await self._impersonations.list_recent(limit=limit)
        return [
            {
                "id": e.id,
                "admin_username": e.admin_username,
                "chat_id": e.chat_id,
                "user_id": e.user_id,
                "content": e.content,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
      ]

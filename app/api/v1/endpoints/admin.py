"""Admin panel API endpoints — protected by session token."""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, Request, status

from app.config import get_settings
from app.db.repositories.admin import AuditLogRepository
from app.dependencies import SessionDep
from app.exceptions import UnauthorizedError, ValidationError
from app.logging_config import get_logger
from app.services.admin_service import AdminService

log = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ═══════════════════════════════════════════════════════════════════
# Auth dependency
# ═══════════════════════════════════════════════════════════════════
async def _require_admin(
    session: SessionDep,
    x_admin_token: Annotated[Optional[str], Header(alias="X-Admin-Token")] = None,
) -> dict:
    """Validate the admin session token and return the admin dict."""
    if not x_admin_token:
        raise UnauthorizedError("التوكن مفقود")
    svc = AdminService(session=session)
    return await svc.verify_token(x_admin_token)


AdminDep = Annotated[dict, Depends(_require_admin)]


# ═══════════════════════════════════════════════════════════════════
# Auth endpoints
# ═══════════════════════════════════════════════════════════════════
@router.post("/login", summary="Admin login")
async def admin_login(request: Request, session: SessionDep) -> dict:
    """Login with username/password. Returns a session token."""
    data = await request.json()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or not password:
        raise ValidationError("اسم المستخدم وكلمة السر مطلوبان")

    svc = AdminService(session=session)
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return await svc.login(username, password, ip=ip, ua=ua)


@router.post("/logout", summary="Admin logout")
async def admin_logout(
    request: Request,
    admin: AdminDep,
    session: SessionDep,
    x_admin_token: Annotated[Optional[str], Header(alias="X-Admin-Token")] = None,
) -> dict:
    svc = AdminService(session=session)
    ip = request.client.host if request.client else None
    if x_admin_token:
        await svc.logout(x_admin_token, ip=ip)
    return {"status": "ok"}


@router.get("/me", summary="Current admin info")
async def admin_me(admin: AdminDep) -> dict:
    return admin


# ═══════════════════════════════════════════════════════════════════
# Users
# ═══════════════════════════════════════════════════════════════════
@router.get("/users", summary="List all users")
async def list_users(admin: AdminDep, session: SessionDep) -> dict:
    svc = AdminService(session=session)
    users = await svc.list_users(limit=500)
    return {"users": users, "count": len(users)}


@router.post("/users/{user_id}/block", summary="Block a user")
async def block_user(
    user_id: str,
    admin: AdminDep,
    session: SessionDep,
    request: Request,
) -> dict:
    svc = AdminService(session=session)
    ip = request.client.host if request.client else None
    ok = await svc.block_user(user_id, admin, ip=ip)
    return {"status": "ok" if ok else "not_found"}


@router.post("/users/{user_id}/unblock", summary="Unblock a user")
async def unblock_user(
    user_id: str,
    admin: AdminDep,
    session: SessionDep,
    request: Request,
) -> dict:
    svc = AdminService(session=session)
    ip = request.client.host if request.client else None
    ok = await svc.unblock_user(user_id, admin, ip=ip)
    return {"status": "ok" if ok else "not_found"}


# ═══════════════════════════════════════════════════════════════════
# Chats
# ═══════════════════════════════════════════════════════════════════
@router.get("/chats", summary="List chats")
async def list_chats(
    admin: AdminDep,
    session: SessionDep,
    user_id: Optional[str] = None,
) -> dict:
    svc = AdminService(session=session)
    return {"chats": await svc.list_chats(user_id=user_id, limit=500)}


@router.get("/chats/{chat_id}", summary="Get chat messages")
async def get_chat(
    chat_id: str,
    admin: AdminDep,
    session: SessionDep,
) -> dict:
    svc = AdminService(session=session)
    return {"messages": await svc.get_chat_messages(chat_id)}


# ═══════════════════════════════════════════════════════════════════
# Impersonation
# ═══════════════════════════════════════════════════════════════════
@router.post("/impersonate", summary="Send a message as the AI")
async def impersonate(
    request: Request,
    admin: AdminDep,
    session: SessionDep,
) -> dict:
    data = await request.json()
    chat_id = str(data.get("chat_id", "")).strip()
    user_id = str(data.get("user_id", "")).strip()
    content = str(data.get("content", "")).strip()

    if not chat_id or not user_id or not content:
        raise ValidationError("chat_id و user_id و content مطلوبة")

    svc = AdminService(session=session)
    ip = request.client.host if request.client else None
    return await svc.impersonate_send(admin, chat_id, user_id, content, ip=ip)


# ═══════════════════════════════════════════════════════════════════
# Rules
# ═══════════════════════════════════════════════════════════════════
@router.get("/rules", summary="List rules")
async def list_rules(admin: AdminDep, session: SessionDep) -> dict:
    svc = AdminService(session=session)
    return {"rules": await svc.list_rules()}


@router.post("/rules", status_code=status.HTTP_201_CREATED, summary="Create a rule")
async def create_rule(
    request: Request,
    admin: AdminDep,
    session: SessionDep,
) -> dict:
    data = await request.json()
    svc = AdminService(session=session)
    ip = request.client.host if request.client else None
    return await svc.create_rule(admin, data, ip=ip)


@router.post("/rules/{rule_id}/toggle", summary="Toggle rule")
async def toggle_rule(
    rule_id: int,
    admin: AdminDep,
    session: SessionDep,
    request: Request,
) -> dict:
    svc = AdminService(session=session)
    ip = request.client.host if request.client else None
    result = await svc.toggle_rule(rule_id, admin, ip=ip)
    if not result:
        raise ValidationError("القاعدة غير موجودة")
    return result


@router.delete("/rules/{rule_id}", summary="Delete a rule")
async def delete_rule(
    rule_id: int,
    admin: AdminDep,
    session: SessionDep,
    request: Request,
) -> dict:
    svc = AdminService(session=session)
    ip = request.client.host if request.client else None
    ok = await svc.delete_rule(rule_id, admin, ip=ip)
    return {"status": "ok" if ok else "not_found"}


# ═══════════════════════════════════════════════════════════════════
# Notifications
# ═══════════════════════════════════════════════════════════════════
@router.get("/notifications", summary="List notifications")
async def list_notifications(admin: AdminDep, session: SessionDep) -> dict:
    svc = AdminService(session=session)
    return await svc.list_notifications()


@router.post("/notifications/read-all", summary="Mark all notifications read")
async def mark_all_read(admin: AdminDep, session: SessionDep) -> dict:
    svc = AdminService(session=session)
    count = await svc.mark_notifications_read(admin)
    return {"status": "ok", "count": count}


# ═══════════════════════════════════════════════════════════════════
# Audit log
# ═══════════════════════════════════════════════════════════════════
@router.get("/audit", summary="List audit log")
async def list_audit(admin: AdminDep, session: SessionDep) -> dict:
    svc = AdminService(session=session)
    return {"entries": await svc.list_audit(limit=500)}


@router.get("/impersonations", summary="List impersonation log")
async def list_impersonations(admin: AdminDep, session: SessionDep) -> dict:
    svc = AdminService(session=session)
    return {"entries": await svc.list_impersonations(limit=500)}

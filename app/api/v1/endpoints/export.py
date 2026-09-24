"""Export endpoints — JSON / Markdown / HTML."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from app.db.repositories import ChatRepository
from app.db.repositories.chat import MessageRepository
from app.dependencies import ChatRepoDep, SessionDep, UserIDDep
from app.exceptions import UnauthorizedError
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["export"])


def _build_markdown(chat_id: str, messages: list) -> str:
    """Render a chat as Markdown."""
    lines = [f"# محادثة {chat_id}\n"]
    for m in messages:
        role = "👤 أنت" if m.role == "user" else "🤖 الخلاقي"
        lines.append(f"\n## {role}\n\n{m.content}\n")
    return "\n".join(lines)


def _build_html(chat_id: str, messages: list) -> str:
    """Render a chat as standalone HTML."""
    parts = [
        '<!DOCTYPE html><html lang="ar" dir="rtl"><head>',
        '<meta charset="UTF-8"><title>محادثة</title>',
        "<style>",
        "body{font-family:Tahoma,Arial;max-width:900px;margin:20px auto;",
        "padding:20px;background:#0a0e1a;color:#e5e9f0;line-height:1.7}",
        ".user{background:#2a1a3a;padding:14px;border-radius:10px;margin:10px 0}",
        ".bot{background:#1a1a2e;padding:14px;border-radius:10px;margin:10px 0}",
        "pre{background:#0d1117;padding:12px;border-radius:6px;",
        "overflow-x:auto;direction:ltr;text-align:left;white-space:pre-wrap}",
        "h1{color:#a855f7}",
        "</style></head><body>",
        "<h1>محادثة الخلاقي</h1>",
    ]
    for m in messages:
        role = "أنت" if m.role == "user" else "الخلاقي"
        cls = "user" if m.role == "user" else "bot"
        safe = m.content.replace("<", "&lt;").replace(">", "&gt;")
        parts.append(
            f'<div class="{cls}"><b>{role}:</b>'
            f'<pre style="white-space:pre-wrap">{safe}</pre></div>'
        )
    parts.append("</body></html>")
    return "".join(parts)


@router.get("/export/{chat_id}", summary="Export a chat")
async def export_chat(
    chat_id: str,
    user_id: UserIDDep,
    session: SessionDep,
    chat_repo: ChatRepoDep,
    format: str = Query(default="json", pattern="^(json|md|html)$"),
):
    """Export a chat as JSON, Markdown, or HTML."""
    if not await chat_repo.belongs_to_user(chat_id, user_id):
        raise UnauthorizedError("غير مصرح")

    message_repo = MessageRepository(session=session)
    messages = await message_repo.list_for_chat(chat_id, limit=1000)

    if format == "md":
        content = _build_markdown(chat_id, messages)
        return PlainTextResponse(
            content,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="chat_{chat_id[:8]}.md"'
                )
            },
        )

    if format == "html":
        content = _build_html(chat_id, messages)
        return HTMLResponse(
            content,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="chat_{chat_id[:8]}.html"'
                )
            },
        )

    # json (default)
    return JSONResponse(
        {
            "chat_id": chat_id,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "type": m.message_type or "text",
                    "source": m.source,
                    "created_at": str(m.created_at),
                }
                for m in messages
            ],
            "exported_at": datetime.utcnow().isoformat(),
        }
    )

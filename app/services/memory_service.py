"""Memory service — automatic extraction of user preferences."""
from __future__ import annotations

import re
from typing import List, Optional

from app.db.repositories.memory import MemoryRepository
from app.logging_config import get_logger
from app.models.db_models import UserMemory

log = get_logger(__name__)


# ─── Regex patterns (compiled once) ───
_LANG_AR = re.compile(r"(أجب|تحدث|اكتب|رد).*(عربي|بالعربية|بالعربي)")
_LANG_EN = re.compile(r"(answer|reply|write).*(english|in english)", re.IGNORECASE)

_STYLE_BRIEF = re.compile(r"(باختر|مختصر|short)", re.IGNORECASE)
_STYLE_LONG = re.compile(r"(مفصل|تفصيل|مطوّل|detailed|in detail)", re.IGNORECASE)

_SKILL_BEGINNER = re.compile(r"(أنا مبتدئ|مبتدئ|beginner|novice)", re.IGNORECASE)
_SKILL_EXPERT = re.compile(r"(أنا خبير|خبير|expert|advanced)", re.IGNORECASE)

_NAME_PATTERN = re.compile(r"(اسمي|انا|أنا)\s+([a-zA-Z\u0600-\u06FF]{3,20})")
_COMPANY_PATTERN = re.compile(
    r"(شركتي|مشروعي|عملي)\s+(?:اسمها|اسمه|هو|هي)?\s*([a-zA-Z\u0600-\u06FF]{3,30})"
)
_TECH_INTENT = re.compile(r"(أفضل|أريد|أحب|استخدم|prefer|like|use)", re.IGNORECASE)

_KNOWN_TECHS = [
    "python", "javascript", "typescript", "go", "rust",
    "java", "c++", "c#", "kotlin", "swift",
    "flask", "fastapi", "django", "node",
    "react", "vue", "svelte", "next",
    "docker", "kubernetes", "terraform",
    "postgres", "postgresql", "mysql", "sqlite", "mongodb", "redis",
]

_STOP_WORDS = {"مبتدئ", "خبير", "مبرمج", "مطور", "طالب", "here", "there"}


class MemoryService:
    """Extracts and stores user preferences automatically."""

    def __init__(self, repo: MemoryRepository) -> None:
        self._repo = repo

    # ─── Build context for the AI ───
    async def build_context(self, user_id: str, limit: int = 30) -> str:
        """Return a compact textual summary of the user's memory for the prompt."""
        try:
            entries = await self._repo.list_for_user(user_id, limit=limit)
        except Exception:
            log.exception("memory.build_context.failed")
            return ""
        if not entries:
            return ""
        lines = ["📌 ذاكرة المستخدم (تفضيلات محفوظة):"]
        for e in entries:
            lines.append(f"• {e.key}: {e.value}")
        return "\n".join(lines)

    # ─── Automatic extraction ───
    async def extract_and_save(
        self, user_id: str, user_message: str, assistant_reply: str
    ) -> None:
        """Extract preferences from a turn and persist them (best-effort)."""
        if not user_message:
            return
        text = user_message.lower()

        tasks = []

        # Language preference
        if _LANG_AR.search(text):
            tasks.append(self._repo.set_value(user_id, "language", "ar", "preference"))
        elif _LANG_EN.search(text):
            tasks.append(self._repo.set_value(user_id, "language", "en", "preference"))

        # Explanation style
        if _STYLE_BRIEF.search(text):
            tasks.append(
                self._repo.set_value(user_id, "explanation_style", "brief", "preference")
            )
        if _STYLE_LONG.search(text):
            tasks.append(
                self._repo.set_value(user_id, "explanation_style", "detailed", "preference")
            )

        # Skill level
        if _SKILL_BEGINNER.search(text):
            tasks.append(
                self._repo.set_value(user_id, "skill_level", "beginner", "preference")
            )
        if _SKILL_EXPERT.search(text):
            tasks.append(
                self._repo.set_value(user_id, "skill_level", "expert", "preference")
            )

        # Preferred tech
        if _TECH_INTENT.search(text):
            for tech in _KNOWN_TECHS:
                if tech in text:
                    tasks.append(
                        self._repo.set_value(user_id, "preferred_tech", tech, "preference")
                    )
                    break  # store only the first match to avoid noise

        # Name
        m = _NAME_PATTERN.search(user_message)
        if m:
            name = m.group(2).strip()
            if name.lower() not in _STOP_WORDS:
                tasks.append(self._repo.set_value(user_id, "name", name, "identity"))

        # Company
        m = _COMPANY_PATTERN.search(user_message)
        if m:
            tasks.append(
                self._repo.set_value(user_id, "company", m.group(2).strip(), "identity")
            )

        # Run all — ignore individual failures
        for task in tasks:
            try:
                await task
            except Exception:
                log.exception("memory.extract.task_failed")

    # ─── Manual CRUD passthrough ───
    async def list_all(self, user_id: str) -> List[UserMemory]:
        """Return all memory entries for the user."""
        return list(await self._repo.list_for_user(user_id))

    async def set_value(
        self,
        user_id: str,
        key: str,
        value: str,
        category: str = "general",
    ) -> UserMemory:
        """Explicitly set a memory entry."""
        return await self._repo.set_value(user_id, key, value, category)

    async def delete_value(self, user_id: str, key: str) -> bool:
        """Delete a single memory entry."""
        return await self._repo.delete_value(user_id, key)

    async def delete_all(self, user_id: str) -> int:
        """Delete all memory entries for the user."""
        return await self._repo.delete_all_for_user(user_id)

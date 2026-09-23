#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
الخلاقي - مساعد برمجي متعدد المزودين مع نظام محادثات
المطور: حسين غلاب
"""

import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from flask import Flask, request, jsonify, render_template
import requests

# ═══════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════
AI_NAME = "الخلاقي"
DEVELOPER_NAME = "حسين غلاب"
VERSION = "6.0-ChatSystem"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "").strip()
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "").strip()

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith("postgres")
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "khallaqi.db")

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]
CF_MODELS = [
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/meta/llama-3.1-8b-instruct",
]
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
]
OPENROUTER_MODELS = [
    "meta-llama/llama-3.1-8b-instruct:free",
    "google/gemma-2-9b-it:free",
]

# ═══════════════════════════════════════════════════════
# System Prompt
# ═══════════════════════════════════════════════════════
SYSTEM_PROMPT = f"""أنت {AI_NAME}، مبرمج محترف Senior Developer. مهمتك: كتابة الكود فوراً.

🚨 قاعدة ذهبية: عندما يطلب المستخدم أي شيء، اختر أنت التفاصيل واكتب الكود فوراً. لا تسأله "ما نوعه؟" أو "ما التفاصيل؟" — هو يعرف، نفّذ.

📌 أمثلة:
• "لعبة" → اكتب لعبة ثعبان Python/Pygame كاملة
• "موقع" → اكتب موقع Portfolio HTML/CSS/JS
• "بوت" → اكتب بوت تيليجرام Python
• "سكربت" → اكتب سكربت Python مفيد

📌 سلوكك الإلزامي:
1. ابدأ بالكود فوراً بدون ترحيب أو مقدمات
2. الكود كامل — ممنوع "..." أو "// اكتب الباقي"
3. بعد الكود: 3-5 أسطر شرح فقط بالعربية
4. اذكر المكتبات + أوامر التثبيت

💻 اللغات المدعومة:
Python, JavaScript, TypeScript, Node.js, PHP, Ruby, Go, Rust, C, C++, C#, Java, Kotlin, Swift, Dart, Shell/Bash, PowerShell, SQL, HTML, CSS, React, Vue, Angular, Flask, FastAPI, Django, Laravel, Express, Spring, Flutter, Kivy, Tkinter, PyQt, Solidity, Assembly, وغيرها.

❌ ترفض فقط (بجملة واحدة):
1. malware / ransomware
2. DDoS ضد أهداف حقيقية
3. اختراق شبكات/حسابات لا يملكها المستخدم
4. سرقة بيانات

المطور: {DEVELOPER_NAME}
"""

# ═══════════════════════════════════════════════════════
# Flask
# ═══════════════════════════════════════════════════════
app = Flask(__name__)

# ═══════════════════════════════════════════════════════
# قاعدة البيانات - نظام محادثات كامل
# ═══════════════════════════════════════════════════════
def get_db():
    if USE_POSTGRES:
        import psycopg2
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url, connect_timeout=10)
    return sqlite3.connect(SQLITE_PATH, timeout=10)


def init_database():
    try:
        with closing(get_db()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS chats (
                            id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            title TEXT DEFAULT 'محادثة جديدة',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS messages (
                            id SERIAL PRIMARY KEY,
                            chat_id TEXT NOT NULL,
                            role TEXT NOT NULL,
                            content TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                else:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS chats (
                            id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            title TEXT DEFAULT 'محادثة جديدة',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS messages (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            chat_id TEXT NOT NULL,
                            role TEXT NOT NULL,
                            content TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                conn.commit()
        print("[DB] تم تهيئة قاعدة البيانات")
    except Exception as e:
        print(f"[DB] تحذير: {e}")


def create_chat(user_id):
    chat_id = str(uuid.uuid4())
    try:
        with closing(get_db()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute(
                        "INSERT INTO chats (id, user_id, title) VALUES (%s, %s, %s)",
                        (chat_id, user_id, "محادثة جديدة")
                    )
                else:
                    cur.execute(
                        "INSERT INTO chats (id, user_id, title) VALUES (?, ?, ?)",
                        (chat_id, user_id, "محادثة جديدة")
                    )
                conn.commit()
        return chat_id
    except Exception as e:
        print(f"[DB] فشل إنشاء محادثة: {e}")
        return None


def list_chats(user_id):
    try:
        with closing(get_db()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute(
                        "SELECT id, title, created_at, updated_at FROM chats WHERE user_id = %s ORDER BY updated_at DESC",
                        (user_id,)
                    )
                else:
                    cur.execute(
                        "SELECT id, title, created_at, updated_at FROM chats WHERE user_id = ? ORDER BY updated_at DESC",
                        (user_id,)
                    )
                rows = cur.fetchall()
                return [
                    {"id": r[0], "title": r[1], "created_at": str(r[2]), "updated_at": str(r[3])}
                    for r in rows
                ]
    except Exception as e:
        print(f"[DB] فشل جلب المحادثات: {e}")
        return []


def delete_chat(chat_id, user_id):
    try:
        with closing(get_db()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute("DELETE FROM messages WHERE chat_id = %s", (chat_id,))
                    cur.execute("DELETE FROM chats WHERE id = %s AND user_id = %s", (chat_id, user_id))
                else:
                    cur.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
                    cur.execute("DELETE FROM chats WHERE id = ? AND user_id = ?", (chat_id, user_id))
                conn.commit()
        return True
    except Exception as e:
        print(f"[DB] فشل حذف محادثة: {e}")
        return False


def rename_chat(chat_id, user_id, title):
    try:
        with closing(get_db()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute(
                        "UPDATE chats SET title = %s WHERE id = %s AND user_id = %s",
                        (title[:80], chat_id, user_id)
                    )
                else:
                    cur.execute(
                        "UPDATE chats SET title = ? WHERE id = ? AND user_id = ?",
                        (title[:80], chat_id, user_id)
                    )
                conn.commit()
        return True
    except Exception as e:
        print(f"[DB] فشل إعادة التسمية: {e}")
        return False


def get_messages(chat_id, limit=50):
    try:
        with closing(get_db()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute(
                        "SELECT role, content FROM messages WHERE chat_id = %s ORDER BY id ASC LIMIT %s",
                        (chat_id, limit)
                    )
                else:
                    cur.execute(
                        "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id ASC LIMIT ?",
                        (chat_id, limit)
                    )
                rows = cur.fetchall()
                return [{"role": r[0], "content": r[1]} for r in rows]
    except Exception as e:
        print(f"[DB] فشل جلب الرسائل: {e}")
        return []


def add_message(chat_id, role, content):
    try:
        with closing(get_db()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute(
                        "INSERT INTO messages (chat_id, role, content) VALUES (%s, %s, %s)",
                        (chat_id, role, content)
                    )
                    cur.execute(
                        "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (chat_id,)
                    )
                else:
                    cur.execute(
                        "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
                        (chat_id, role, content)
                    )
                    cur.execute(
                        "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (chat_id,)
                    )
                conn.commit()
    except Exception as e:
        print(f"[DB] فشل حفظ رسالة: {e}")


def count_messages(chat_id):
    try:
        with closing(get_db()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute("SELECT COUNT(*) FROM messages WHERE chat_id = %s", (chat_id,))
                else:
                    cur.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,))
                return cur.fetchone()[0]
    except Exception:
        return 0


def chat_belongs_to_user(chat_id, user_id):
    try:
        with closing(get_db()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute("SELECT 1 FROM chats WHERE id = %s AND user_id = %s", (chat_id, user_id))
                else:
                    cur.execute("SELECT 1 FROM chats WHERE id = ? AND user_id = ?", (chat_id, user_id))
                return cur.fetchone() is not None
    except Exception:
        return False


# ═══════════════════════════════════════════════════════
# المزودون
# ═══════════════════════════════════════════════════════
def call_groq(history):
    if not GROQ_API_KEY:
        return None, None
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    for model in GROQ_MODELS:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json={"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 4096},
                timeout=30
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip(), f"Groq/{model.split('/')[-1]}"
            if r.status_code == 401:
                return None, None
        except Exception as e:
            print(f"[GROQ] {model} → {str(e)[:60]}")
    return None, None


def call_cloudflare(history):
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        return None, None
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}
    for model in CF_MODELS:
        url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}"
        try:
            r = requests.post(url, headers=headers, json={"messages": messages, "max_tokens": 4096}, timeout=30)
            if r.status_code == 200:
                data = r.json()
                text = None
                if isinstance(data.get("result"), dict):
                    text = data["result"].get("response") or \
                           (data["result"].get("choices", [{}])[0].get("message", {}).get("content"))
                elif isinstance(data.get("result"), str):
                    text = data["result"]
                if text:
                    return text.strip(), f"Cloudflare/{model.split('/')[-1]}"
        except Exception as e:
            print(f"[CF] {model} → {str(e)[:60]}")
    return None, None


def call_gemini(history):
    if not GEMINI_API_KEY:
        return None, None
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]} for m in history]
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096}
    }
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        try:
            r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=30)
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip(), f"Gemini/{model}"
        except Exception as e:
            print(f"[GEMINI] {model} → {str(e)[:60]}")
    return None, None


def call_openrouter(history):
    if not OPENROUTER_API_KEY:
        return None, None
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://khallaqi.app",
        "X-Title": "Khallaqi AI"
    }
    for model in OPENROUTER_MODELS:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 4096},
                timeout=30
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip(), f"OpenRouter/{model.split('/')[-1]}"
        except Exception as e:
            print(f"[OR] {model} → {str(e)[:60]}")
    return None, None


def call_ai(history):
    for func in (call_groq, call_cloudflare, call_gemini, call_openrouter):
        text, source = func(history)
        if text:
            return text, source, None
    return None, None, "❌ جميع المزودين فشلوا. تحقق من المفاتيح أو انتظر تجديد الحصة."


# ═══════════════════════════════════════════════════════
# المسارات
# ═══════════════════════════════════════════════════════
@app.route('/')
def index():
    return render_template('index.html', ai_name=AI_NAME, developer_name=DEVELOPER_NAME, version=VERSION)


@app.route('/chats', methods=['GET'])
def list_chats_route():
    user_id = str(request.args.get('user_id', '')).strip()[:64]
    if not user_id:
        return jsonify({"error": "user_id مفقود"}), 400
    return jsonify({"chats": list_chats(user_id)})


@app.route('/chats', methods=['POST'])
def new_chat_route():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id', '')).strip()[:64]
    if not user_id:
        return jsonify({"error": "user_id مفقود"}), 400
    chat_id = create_chat(user_id)
    if chat_id:
        return jsonify({"chat_id": chat_id, "title": "محادثة جديدة"})
    return jsonify({"error": "فشل إنشاء محادثة"}), 500


@app.route('/chats/<chat_id>', methods=['DELETE'])
def delete_chat_route(chat_id):
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id', '')).strip()[:64]
    if not user_id:
        return jsonify({"error": "user_id مفقود"}), 400
    if delete_chat(chat_id, user_id):
        return jsonify({"status": "ok"})
    return jsonify({"error": "فشل الحذف"}), 500


@app.route('/chats/<chat_id>/messages', methods=['GET'])
def get_messages_route(chat_id):
    user_id = str(request.args.get('user_id', '')).strip()[:64]
    if not chat_belongs_to_user(chat_id, user_id):
        return jsonify({"error": "غير مصرح"}), 403
    return jsonify({"messages": get_messages(chat_id)})


@app.route('/chat', methods=['POST'])
def chat_route():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "بيانات مفقودة"}), 400

        user_message = str(data.get('message', '')).strip()
        chat_id = str(data.get('chat_id', '')).strip()
        user_id = str(data.get('user_id', '')).strip()[:64]

        if not user_message or len(user_message) > 8000:
            return jsonify({"error": "رسالة فارغة أو طويلة جداً"}), 400
        if not chat_id or not user_id:
            return jsonify({"error": "chat_id أو user_id مفقود"}), 400
        if not chat_belongs_to_user(chat_id, user_id):
            return jsonify({"error": "غير مصرح"}), 403

        # تحديث عنوان المحادثة من أول رسالة
        if count_messages(chat_id) == 0:
            rename_chat(chat_id, user_id, user_message[:50])

        add_message(chat_id, "user", user_message)
        history = get_messages(chat_id, limit=30)

        reply, source, error = call_ai(history)

        if error:
            return jsonify({"error": error, "source": "none"}), 200

        add_message(chat_id, "assistant", reply)
        return jsonify({"response": reply, "source": source})

    except Exception as e:
        print(f"[CHAT] {e}")
        return jsonify({"error": f"خطأ: {str(e)[:150]}"}), 500


@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        "ai_name": AI_NAME,
        "version": VERSION,
        "providers": {
            "groq": bool(GROQ_API_KEY),
            "cloudflare": bool(CF_ACCOUNT_ID and CF_API_TOKEN),
            "gemini": bool(GEMINI_API_KEY),
            "openrouter": bool(OPENROUTER_API_KEY)
        }
    })


@app.errorhandler(Exception)
def unhandled(e):
    print(f"[UNHANDLED] {e}")
    return jsonify({"error": str(e)[:150]}), 500


# ═══════════════════════════════════════════════════════
init_database()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

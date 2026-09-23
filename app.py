#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
الخلاقي - مساعد برمجي متعدد المزودين
المطور: حسين غلاب
يدعم: Groq + Cloudflare + Gemini + OpenRouter
"""

import os
import sqlite3
import json
from contextlib import closing
from flask import Flask, request, jsonify, render_template
import requests

# ═══════════════════════════════════════════════════════
# الإعدادات العامة
# ═══════════════════════════════════════════════════════
AI_NAME = "الخلاقي"
DEVELOPER_NAME = "حسين غلاب"
VERSION = "4.0-MultiProvider"

# ─── المفاتيح من متغيرات البيئة ───
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "").strip()
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "").strip()

# ─── قاعدة البيانات ───
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith("postgres")
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "khallaqi.db")

# ─── النماذج لكل مزود ───
GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

CF_MODELS = [
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/meta/llama-3.1-8b-instruct",
    "@cf/qwen/qwen1.5-14b-chat-awq",
]

GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
]

OPENROUTER_MODELS = [
    "meta-llama/llama-3.1-8b-instruct:free",
    "google/gemma-2-9b-it:free",
    "mistralai/mistral-7b-instruct:free",
]

# ═══════════════════════════════════════════════════════
# System Prompt - عام وبرمجي، مع رفض الطلبات الضارة فقط
# ═══════════════════════════════════════════════════════
SYSTEM_PROMPT = f"""أنت {AI_NAME}، مساعد برمجي متقدم من إعداد {DEVELOPER_NAME}.

✅ تخصصاتك:
1. كتابة الكود الكامل لأي نظام (Linux, Windows, Android, Web, macOS).
2. بايثون، JavaScript، Bash، C، C++، Java، PHP، Go، Rust، SQL.
3. بناء تطبيقات كاملة: Flask، FastAPI، React، Vue، Kivy.
4. تطوير المواقع، APIs، قواعد البيانات، الأتمتة.
5. شرح الكود سطراً بسطر.
6. الأمن السيبراني الدفاعي (حماية، تحصين، مراقبة).
7. DevOps: Docker، CI/CD، Linux admin.

📌 قواعد كتابة الكود:
1. اكتب الكود كاملاً من أول سطر إلى آخر سطر — ممنوع الاختصارات مثل "// اكتب الباقي".
2. اشرح الكود بعد كتابته بالعربية بشكل موجز ومفيد.
3. إذا كان الكود طويلاً جداً، قسمه إلى ملفات واضحة.
4. اذكر المكتبات المطلوبة وأوامر التثبيت.

❌ الطلبات التي سأرفضها بوضوح:
- كود malware أو ransomware أو فيروسات.
- أدوات DDoS أو DoS ضد أهداف حقيقية.
- كود لاختراق أنظمة لا يملكها المستخدم.
- سرقة بيانات أو تجسس على الآخرين.
- أي شيء يضر أطرافاً أخرى.

📌 عند رفض طلب ضار:
- ارفض بجملة واحدة قصيرة.
- اقترح البديل القانوني (HackTheBox, TryHackMe, PortSwigger Academy).

📌 اللغة:
- ترد بالعربية إذا سأل المستخدم بالعربية.
- ترد بالإنجليزية إذا سأل بالإنجليزية.
- الكود نفسه يبقى بالإنجليزية دائماً (أفضل ممارسة).

المطور: {DEVELOPER_NAME}
"""

# ═══════════════════════════════════════════════════════
# Flask
# ═══════════════════════════════════════════════════════
app = Flask(__name__)

# ═══════════════════════════════════════════════════════
# قاعدة البيانات
# ═══════════════════════════════════════════════════════
def get_db_connection():
    if USE_POSTGRES:
        import psycopg2
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url, connect_timeout=10)
    return sqlite3.connect(SQLITE_PATH, timeout=10)


def init_database():
    try:
        with closing(get_db_connection()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS conversations (
                            id SERIAL PRIMARY KEY,
                            session_id TEXT NOT NULL,
                            role TEXT NOT NULL,
                            content TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                else:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS conversations (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            session_id TEXT NOT NULL,
                            role TEXT NOT NULL,
                            content TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                conn.commit()
        print("[DB] تم تهيئة قاعدة البيانات")
    except Exception as e:
        print(f"[DB] تحذير: {e}")


def save_message(session_id, role, content):
    try:
        with closing(get_db_connection()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute(
                        "INSERT INTO conversations (session_id, role, content) VALUES (%s, %s, %s)",
                        (session_id, role, content)
                    )
                else:
                    cur.execute(
                        "INSERT INTO conversations (session_id, role, content) VALUES (?, ?, ?)",
                        (session_id, role, content)
                    )
                conn.commit()
    except Exception as e:
        print(f"[DB] فشل حفظ: {e}")


def load_conversation(session_id, limit=20):
    try:
        with closing(get_db_connection()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute(
                        "SELECT role, content FROM conversations WHERE session_id = %s ORDER BY id DESC LIMIT %s",
                        (session_id, limit)
                    )
                else:
                    cur.execute(
                        "SELECT role, content FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                        (session_id, limit)
                    )
                rows = cur.fetchall()
                return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
    except Exception as e:
        print(f"[DB] فشل تحميل: {e}")
        return []


def clear_conversation(session_id):
    try:
        with closing(get_db_connection()) as conn:
            with conn.cursor() as cur:
                if USE_POSTGRES:
                    cur.execute("DELETE FROM conversations WHERE session_id = %s", (session_id,))
                else:
                    cur.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))
                conn.commit()
        return True
    except Exception as e:
        print(f"[DB] فشل حذف: {e}")
        return False


# ═══════════════════════════════════════════════════════
# 1. Groq (الأولوية الأولى - الأسرع)
# ═══════════════════════════════════════════════════════
def call_groq(history):
    if not GROQ_API_KEY:
        return None, None

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    for model in GROQ_MODELS:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096
        }
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers, json=payload, timeout=30
            )
            if r.status_code == 200:
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()
                return text, f"Groq/{model.split('/')[-1]}"
            if r.status_code == 401:
                print("[GROQ] مفتاح خاطئ")
                return None, None
            print(f"[GROQ] {model} → {r.status_code}")
        except Exception as e:
            print(f"[GROQ] {model} → {str(e)[:80]}")

    return None, None


# ═══════════════════════════════════════════════════════
# 2. Cloudflare Workers AI
# ═══════════════════════════════════════════════════════
def call_cloudflare(history):
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        return None, None

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})

    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json"
    }

    for model in CF_MODELS:
        url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}"
        payload = {
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.7
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                data = r.json()
                # Cloudflare قد يعيد شكلين مختلفين
                text = None
                if "result" in data:
                    if isinstance(data["result"], dict):
                        text = data["result"].get("response") or \
                               (data["result"].get("choices", [{}])[0].get("message", {}).get("content"))
                    elif isinstance(data["result"], str):
                        text = data["result"]
                if text:
                    return text.strip(), f"Cloudflare/{model.split('/')[-1]}"
            print(f"[CF] {model} → {r.status_code}")
        except Exception as e:
            print(f"[CF] {model} → {str(e)[:80]}")

    return None, None


# ═══════════════════════════════════════════════════════
# 3. Google Gemini
# ═══════════════════════════════════════════════════════
def call_gemini(history):
    if not GEMINI_API_KEY:
        return None, None

    contents = []
    for m in history:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096}
    }
    headers = {"Content-Type": "application/json"}

    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                data = r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                return text, f"Gemini/{model}"
            print(f"[GEMINI] {model} → {r.status_code}")
        except Exception as e:
            print(f"[GEMINI] {model} → {str(e)[:80]}")

    return None, None


# ═══════════════════════════════════════════════════════
# 4. OpenRouter
# ═══════════════════════════════════════════════════════
def call_openrouter(history):
    if not OPENROUTER_API_KEY:
        return None, None

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://khallaqi.app",
        "X-Title": "Khallaqi AI"
    }

    for model in OPENROUTER_MODELS:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096
        }
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers, json=payload, timeout=30
            )
            if r.status_code == 200:
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()
                return text, f"OpenRouter/{model.split('/')[-1]}"
            print(f"[OR] {model} → {r.status_code}")
        except Exception as e:
            print(f"[OR] {model} → {str(e)[:80]}")

    return None, None


# ═══════════════════════════════════════════════════════
# الدالة الرئيسية: تجرب المزودين بالترتيب
# ═══════════════════════════════════════════════════════
def call_ai(history):
    """
    ترتيب الأولوية:
    1. Groq (أسرع + حد 14,400/يوم)
    2. Cloudflare (10,000/يوم)
    3. Gemini (1,500/يوم)
    4. OpenRouter (200/يوم)
    """
    # 1. Groq
    text, source = call_groq(history)
    if text:
        return text, source, None

    # 2. Cloudflare
    text, source = call_cloudflare(history)
    if text:
        return text, source, None

    # 3. Gemini
    text, source = call_gemini(history)
    if text:
        return text, source, None

    # 4. OpenRouter
    text, source = call_openrouter(history)
    if text:
        return text, source, None

    return None, None, "❌ جميع المزودين فشلوا. تحقق من المفاتيح أو انتظر تجديد الحصة."


# ═══════════════════════════════════════════════════════
# المسارات
# ═══════════════════════════════════════════════════════
@app.route('/')
def index():
    return render_template(
        'index.html',
        ai_name=AI_NAME,
        developer_name=DEVELOPER_NAME,
        version=VERSION
    )


@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json(silent=True)
        if not data or 'message' not in data:
            return jsonify({"error": "حقل 'message' مفقود"}), 400

        user_message = str(data['message']).strip()
        if not user_message:
            return jsonify({"error": "الرسالة فارغة"}), 400
        if len(user_message) > 8000:
            return jsonify({"error": "الرسالة طويلة جداً (الحد 8000 حرف)"}), 400

        session_id = str(data.get('session_id', 'default'))[:64]

        # حفظ رسالة المستخدم
        save_message(session_id, "user", user_message)

        # تحميل المحادثة
        history = load_conversation(session_id, limit=20)

        # استدعاء AI
        reply, source, error = call_ai(history)

        if error:
            # ⚠️ لا نحفظ الخطأ في قاعدة البيانات
            return jsonify({"error": error, "source": "none"}), 200

        # حفظ الرد
        save_message(session_id, "assistant", reply)

        return jsonify({"response": reply, "source": source})

    except Exception as e:
        print(f"[CHAT] {e}")
        return jsonify({"error": f"خطأ داخلي: {str(e)[:150]}"}), 500


@app.route('/clear', methods=['POST'])
def clear():
    try:
        data = request.get_json(silent=True) or {}
        session_id = str(data.get('session_id', 'default'))[:64]
        if clear_conversation(session_id):
            return jsonify({"status": "ok"})
        return jsonify({"error": "فشل حذف المحادثة"}), 500
    except Exception as e:
        return jsonify({"error": str(e)[:150]}), 500


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
        },
        "database": "postgresql" if USE_POSTGRES else "sqlite"
    })


@app.errorhandler(Exception)
def unhandled(e):
    print(f"[UNHANDLED] {e}")
    return jsonify({"error": f"خطأ: {str(e)[:150]}"}), 500


# ═══════════════════════════════════════════════════════
# التشغيل
# ═══════════════════════════════════════════════════════
init_database()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"""
    ╔══════════════════════════════════════════╗
    ║   {AI_NAME} - النسخة {VERSION}      ║
    ║   المطور: {DEVELOPER_NAME}                ║
    ╚══════════════════════════════════════════╝
    المنفذ: {port}
    المزودون المتاحون:
      - Groq:        {"✅" if GROQ_API_KEY else "❌"}
      - Cloudflare:  {"✅" if (CF_ACCOUNT_ID and CF_API_TOKEN) else "❌"}
      - Gemini:      {"✅" if GEMINI_API_KEY else "❌"}
      - OpenRouter:  {"✅" if OPENROUTER_API_KEY else "❌"}
    قاعدة البيانات: {"PostgreSQL" if USE_POSTGRES else "SQLite"}
    """)
    app.run(host='0.0.0.0', port=port, debug=False)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
الخلاقي - مساعد برمجي متعدد الوسائط
المطور: حسين غلاب
الإصدار: 8.0-Multimodal
يدعم: نص، صوت، صور، فيديو + قاعدة بيانات هجينة + نظام محادثات
"""

import os
import sqlite3
import uuid
import base64
import traceback
from contextlib import closing
from flask import Flask, request, jsonify, render_template
import requests

# ═══════════════════════════════════════════════════════
# الإعدادات العامة
# ═══════════════════════════════════════════════════════
AI_NAME = "الخلاقي"
DEVELOPER_NAME = "حسين غلاب"
VERSION = "8.0-Multimodal"

# ─── مفاتيح API ───
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

# ─── قاعدة البيانات ───
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith("postgres")
SQLITE_PATH = "/tmp/khallaqi.db"

LAST_DB_ERROR = ""

# ─── النماذج (أسماء حقيقية فقط) ───
GEMINI_TEXT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
]

GEMINI_VISION_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
]

GEMINI_VIDEO_MODELS = [
    "veo-3.1-generate-preview",
    "veo-3.1-fast-generate-preview",
]

GROQ_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
]

# ═══════════════════════════════════════════════════════
# System Prompt
# ═══════════════════════════════════════════════════════
SYSTEM_PROMPT = f"""أنت {AI_NAME}، مبرمج محترف Senior Developer من إعداد {DEVELOPER_NAME}.

مهمتك: كتابة الكود فوراً. لا تسأل عن التفاصيل، اختر الأنسب ونفّذ.

قواعد:
1. ابدأ بالكود مباشرة بدون ترحيب.
2. اكتب الكود كاملاً بدون أي اختصار.
3. اشرح الكود بالعربية بعد كتابته.
4. اذكر المكتبات وأوامر التثبيت.
5. تدعم كل لغات البرمجة: Python, JavaScript, PHP, Go, Rust, C, C++, Java, Kotlin, Swift, Ruby, Lua, Bash, SQL, HTML, CSS, React, Vue, Flask, Django, Node.js, وغيرها.

الحالات الأربع المرفوضة فقط:
- malware / ransomware
- DDoS
- اختراق بدون إذن
- سرقة بيانات

المطور: {DEVELOPER_NAME}
"""

# ═══════════════════════════════════════════════════════
# Flask
# ═══════════════════════════════════════════════════════
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB للصور والفيديو


# ═══════════════════════════════════════════════════════
# قاعدة البيانات الهجينة
# ═══════════════════════════════════════════════════════
def get_db():
    if USE_POSTGRES:
        import psycopg2
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url, connect_timeout=10)
    return sqlite3.connect(SQLITE_PATH, timeout=10)


def init_database():
    global LAST_DB_ERROR
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
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
                        message_type TEXT DEFAULT 'text',
                        media_data TEXT,
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
                        message_type TEXT DEFAULT 'text',
                        media_data TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            conn.commit()
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        LAST_DB_ERROR = str(e)
        print(f"[DB] فشل التهيئة: {e}")


def create_chat(user_id):
    global LAST_DB_ERROR
    chat_id = str(uuid.uuid4())
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
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
        finally:
            cur.close()
            conn.close()
        return chat_id
    except Exception as e:
        LAST_DB_ERROR = str(e)
        print(f"[DB] فشل إنشاء محادثة: {e}")
        return None


def list_chats(user_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
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
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"[DB] فشل جلب المحادثات: {e}")
        return []


def delete_chat(chat_id, user_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
            if USE_POSTGRES:
                cur.execute("DELETE FROM messages WHERE chat_id = %s", (chat_id,))
                cur.execute("DELETE FROM chats WHERE id = %s AND user_id = %s", (chat_id, user_id))
            else:
                cur.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
                cur.execute("DELETE FROM chats WHERE id = ? AND user_id = ?", (chat_id, user_id))
            conn.commit()
        finally:
            cur.close()
            conn.close()
        return True
    except Exception as e:
        print(f"[DB] فشل حذف محادثة: {e}")
        return False


def rename_chat(chat_id, user_id, title):
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
            if USE_POSTGRES:
                cur.execute(
                    "UPDATE chats SET title = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s AND user_id = %s",
                    (title[:80], chat_id, user_id)
                )
            else:
                cur.execute(
                    "UPDATE chats SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                    (title[:80], chat_id, user_id)
                )
            conn.commit()
        finally:
            cur.close()
            conn.close()
        return True
    except Exception as e:
        print(f"[DB] فشل إعادة التسمية: {e}")
        return False


def get_messages(chat_id, limit=50):
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
            if USE_POSTGRES:
                cur.execute(
                    "SELECT role, content, message_type, media_data FROM messages WHERE chat_id = %s ORDER BY id ASC LIMIT %s",
                    (chat_id, limit)
                )
            else:
                cur.execute(
                    "SELECT role, content, message_type, media_data FROM messages WHERE chat_id = ? ORDER BY id ASC LIMIT ?",
                    (chat_id, limit)
                )
            rows = cur.fetchall()
            return [
                {
                    "role": r[0],
                    "content": r[1],
                    "type": r[2] or "text",
                    "media": r[3]
                }
                for r in rows
            ]
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"[DB] فشل جلب الرسائل: {e}")
        return []


def add_message(chat_id, role, content, message_type="text", media_data=None):
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
            if USE_POSTGRES:
                cur.execute(
                    "INSERT INTO messages (chat_id, role, content, message_type, media_data) VALUES (%s, %s, %s, %s, %s)",
                    (chat_id, role, content, message_type, media_data)
                )
                cur.execute(
                    "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (chat_id,)
                )
            else:
                cur.execute(
                    "INSERT INTO messages (chat_id, role, content, message_type, media_data) VALUES (?, ?, ?, ?, ?)",
                    (chat_id, role, content, message_type, media_data)
                )
                cur.execute(
                    "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (chat_id,)
                )
            conn.commit()
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"[DB] فشل حفظ رسالة: {e}")


def count_messages(chat_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
            if USE_POSTGRES:
                cur.execute("SELECT COUNT(*) FROM messages WHERE chat_id = %s", (chat_id,))
            else:
                cur.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,))
            return cur.fetchone()[0]
        finally:
            cur.close()
            conn.close()
    except Exception:
        return 0


def chat_belongs_to_user(chat_id, user_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
            if USE_POSTGRES:
                cur.execute("SELECT 1 FROM chats WHERE id = %s AND user_id = %s", (chat_id, user_id))
            else:
                cur.execute("SELECT 1 FROM chats WHERE id = ? AND user_id = ?", (chat_id, user_id))
            return cur.fetchone() is not None
        finally:
            cur.close()
            conn.close()
    except Exception:
        return False


# ═══════════════════════════════════════════════════════
# Gemini API - نصوص
# ═══════════════════════════════════════════════════════
def call_gemini_text(history):
    if not GEMINI_API_KEY:
        return None, None

    contents = []
    for m in history:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 8192}
    }

    for model in GEMINI_TEXT_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        try:
            r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=60)
            if r.status_code == 200:
                d = r.json()
                text = d["candidates"][0]["content"]["parts"][0]["text"].strip()
                return text, f"Gemini/{model}"
            print(f"[GEMINI-TEXT] {model} -> {r.status_code}")
        except Exception as e:
            print(f"[GEMINI-TEXT] {model} -> {str(e)[:80]}")
    return None, None


# ═══════════════════════════════════════════════════════
# Gemini API - صور (Multimodal)
# ═══════════════════════════════════════════════════════
def call_gemini_vision(prompt, image_base64, mime_type="image/jpeg"):
    if not GEMINI_API_KEY:
        return None, None, "GEMINI_API_KEY غير معيّن"

    # إزالة prefix data URL إذا وُجد
    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt or "حلل هذه الصورة بالتفصيل."},
                {"inline_data": {"mime_type": mime_type, "data": image_base64}}
            ]
        }],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096}
    }

    for model in GEMINI_VISION_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        try:
            r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=60)
            if r.status_code == 200:
                d = r.json()
                text = d["candidates"][0]["content"]["parts"][0]["text"].strip()
                return text, f"Gemini-Vision/{model}", None
            print(f"[GEMINI-VISION] {model} -> {r.status_code}")
        except Exception as e:
            print(f"[GEMINI-VISION] {model} -> {str(e)[:80]}")
    return None, None, "فشلت جميع نماذج الرؤية"


# ═══════════════════════════════════════════════════════
# Gemini API - فيديو (Veo)
# ═══════════════════════════════════════════════════════
def call_gemini_video(prompt):
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEY غير معيّن"

    # Veo يستخدم long-running operation
    for model in GEMINI_VIDEO_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning?key={GEMINI_API_KEY}"
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {"aspectRatio": "16:9", "personGeneration": "allow_adult"}
        }
        try:
            r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=60)
            if r.status_code == 200:
                d = r.json()
                op_name = d.get("name")
                if op_name:
                    return {"operation": op_name, "model": model}, None
            print(f"[GEMINI-VIDEO] {model} -> {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[GEMINI-VIDEO] {model} -> {str(e)[:80]}")

    return None, "توليد الفيديو غير متاح لحسابك حالياً. Veo يتطلب صلاحيات خاصة."


def check_video_operation(op_name):
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEY غير معيّن"
    url = f"https://generativelanguage.googleapis.com/v1beta/{op_name}?key={GEMINI_API_KEY}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            return r.json(), None
        return None, f"خطأ {r.status_code}"
    except Exception as e:
        return None, str(e)


# ═══════════════════════════════════════════════════════
# Groq - Fallback
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
                json={"model": model, "messages": messages, "temperature": 0.8, "max_tokens": 4096},
                timeout=30
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip(), f"Groq/{model.split('/')[-1]}"
            if r.status_code == 401:
                return None, None
        except Exception as e:
            print(f"[GROQ] {model} -> {str(e)[:60]}")
    return None, None


def call_ai_text(history):
    """نص: Gemini أولاً، ثم Groq"""
    text, source = call_gemini_text(history)
    if text:
        return text, source, None
    text, source = call_groq(history)
    if text:
        return text, source, None
    return None, None, "❌ جميع المزودين فشلوا. تحقق من المفاتيح أو انتظر تجديد الحصة."


# ═══════════════════════════════════════════════════════
# المسارات - الواجهة
# ═══════════════════════════════════════════════════════
@app.route('/')
def index():
    return render_template(
        'index.html',
        ai_name=AI_NAME,
        developer_name=DEVELOPER_NAME,
        version=VERSION
    )


# ═══════════════════════════════════════════════════════
# REST API - المحادثات
# ═══════════════════════════════════════════════════════
@app.route('/api/chats', methods=['GET'])
def api_list_chats():
    user_id = str(request.args.get('user_id', '')).strip()[:64]
    if not user_id:
        return jsonify({"error": "user_id مفقود"}), 400
    return jsonify({"chats": list_chats(user_id)})


@app.route('/api/chats/new', methods=['POST'])
def api_new_chat():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id', '')).strip()[:64]
    if not user_id:
        return jsonify({"error": "user_id مفقود"}), 400
    chat_id = create_chat(user_id)
    if chat_id:
        return jsonify({"chat_id": chat_id, "title": "محادثة جديدة"})
    return jsonify({"error": f"فشل إنشاء محادثة: {LAST_DB_ERROR}"}), 500


@app.route('/api/chats/<chat_id>', methods=['GET'])
def api_get_chat(chat_id):
    user_id = str(request.args.get('user_id', '')).strip()[:64]
    if not chat_belongs_to_user(chat_id, user_id):
        return jsonify({"error": "غير مصرح"}), 403
    return jsonify({"messages": get_messages(chat_id)})


@app.route('/api/chats/<chat_id>', methods=['DELETE'])
def api_delete_chat(chat_id):
    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id', '')).strip()[:64]
    if not user_id:
        return jsonify({"error": "user_id مفقود"}), 400
    if delete_chat(chat_id, user_id):
        return jsonify({"status": "ok"})
    return jsonify({"error": "فشل الحذف"}), 500


# ═══════════════════════════════════════════════════════
# REST API - إرسال الرسائل (نص + صورة)
# ═══════════════════════════════════════════════════════
@app.route('/api/chat', methods=['POST'])
def api_chat():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "بيانات مفقودة"}), 400

        user_message = str(data.get('message', '')).strip()
        chat_id = str(data.get('chat_id', '')).strip()
        user_id = str(data.get('user_id', '')).strip()[:64]
        image_base64 = data.get('image')  # Base64 string (data URL أو raw)
        image_type = data.get('image_type', 'image/jpeg')

        if not chat_id or not user_id:
            return jsonify({"error": "chat_id أو user_id مفقود"}), 400
        if not user_message and not image_base64:
            return jsonify({"error": "لا يوجد نص ولا صورة"}), 400
        if len(user_message) > 8000:
            return jsonify({"error": "النص طويل جداً"}), 400
        if not chat_belongs_to_user(chat_id, user_id):
            return jsonify({"error": "غير مصرح"}), 403

        # إذا كانت أول رسالة، استخدم النص أو "صورة" كعنوان
        if count_messages(chat_id) == 0:
            title = user_message[:50] if user_message else "🖼️ صورة"
            rename_chat(chat_id, user_id, title)

        # ─── حالة الصورة ───
        if image_base64:
            # احفظ رسالة المستخدم مع الصورة
            add_message(
                chat_id, "user",
                user_message or "حلل هذه الصورة",
                message_type="image",
                media_data=image_base64
            )

            # استدعاء Gemini Vision
            prompt = user_message or "حلل هذه الصورة بالتفصيل واشرح محتواها."
            reply, source, error = call_gemini_vision(prompt, image_base64, image_type)

            if error or not reply:
                return jsonify({"error": error or "فشل تحليل الصورة", "source": "none"}), 200

            add_message(chat_id, "assistant", reply, message_type="text")
            return jsonify({"response": reply, "source": source, "type": "text"})

        # ─── حالة النص العادي ───
        add_message(chat_id, "user", user_message, message_type="text")
        history = get_messages(chat_id, limit=30)

        # حول السجل لصيغة Gemini
        gemini_history = []
        for m in history:
            gemini_history.append({"role": m["role"], "content": m["content"]})

        reply, source, error = call_ai_text(gemini_history)

        if error:
            return jsonify({"error": error, "source": "none"}), 200

        add_message(chat_id, "assistant", reply, message_type="text")
        return jsonify({"response": reply, "source": source, "type": "text"})

    except Exception as e:
        print(f"[CHAT] {e}")
        traceback.print_exc()
        return jsonify({"error": f"خطأ: {str(e)[:150]}"}), 500


# ═══════════════════════════════════════════════════════
# REST API - توليد الفيديو
# ═══════════════════════════════════════════════════════
@app.route('/api/generate-video', methods=['POST'])
def api_generate_video():
    try:
        data = request.get_json(silent=True) or {}
        prompt = str(data.get('prompt', '')).strip()
        chat_id = str(data.get('chat_id', '')).strip()
        user_id = str(data.get('user_id', '')).strip()[:64]

        if not prompt:
            return jsonify({"error": "الوصف مطلوب"}), 400
        if len(prompt) > 2000:
            return jsonify({"error": "الوصف طويل جداً"}), 400

        result, error = call_gemini_video(prompt)

        if error or not result:
            return jsonify({
                "error": error or "فشل توليد الفيديو",
                "hint": "Veo يتطلب تفعيلاً خاصاً في Google AI Studio. يمكنك استخدام نماذج فيديو أخرى."
            }), 200

        if chat_id and user_id and chat_belongs_to_user(chat_id, user_id):
            add_message(chat_id, "user", f"🎬 طلب فيديو: {prompt}", message_type="text")
            add_message(
                chat_id, "assistant",
                f"جاري توليد الفيديو... العملية: {result['operation']}",
                message_type="video_pending",
                media_data=result["operation"]
            )

        return jsonify({
            "status": "pending",
            "operation": result["operation"],
            "model": result["model"],
            "message": "جاري توليد الفيديو. استخدم /api/video-status لمتابعة الحالة."
        })

    except Exception as e:
        print(f"[VIDEO] {e}")
        return jsonify({"error": str(e)[:150]}), 500


@app.route('/api/video-status', methods=['POST'])
def api_video_status():
    try:
        data = request.get_json(silent=True) or {}
        op_name = str(data.get('operation', '')).strip()
        if not op_name:
            return jsonify({"error": "operation مطلوب"}), 400

        result, error = check_video_operation(op_name)
        if error:
            return jsonify({"error": error}), 200

        done = result.get("done", False)
        if done:
            response = result.get("response", {})
            # استخراج رابط الفيديو إن وُجد
            videos = response.get("generateVideoResponse", {}).get("generatedSamples", [])
            video_uri = videos[0].get("video", {}).get("uri") if videos else None
            return jsonify({
                "done": True,
                "video_url": video_uri,
                "raw": response
            })
        return jsonify({"done": False, "status": "still_processing"})

    except Exception as e:
        return jsonify({"error": str(e)[:150]}), 500


# ═══════════════════════════════════════════════════════
# REST API - حالة المزودين
# ═══════════════════════════════════════════════════════
@app.route('/api/status', methods=['GET'])
def api_status():
    db_ok = False
    db_error = ""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM chats")
        cur.fetchone()
        cur.close()
        conn.close()
        db_ok = True
    except Exception as e:
        db_error = str(e)

    return jsonify({
        "ai_name": AI_NAME,
        "version": VERSION,
        "database": "postgresql" if USE_POSTGRES else f"sqlite ({SQLITE_PATH})",
        "db_ok": db_ok,
        "db_error": db_error,
        "providers": {
            "gemini": bool(GEMINI_API_KEY),
            "groq": bool(GROQ_API_KEY),
            "openrouter": bool(OPENROUTER_API_KEY)
        },
        "features": {
            "text": bool(GEMINI_API_KEY or GROQ_API_KEY),
            "image": bool(GEMINI_API_KEY),
            "video": bool(GEMINI_API_KEY),
            "voice": True
        }
    })


# ═══════════════════════════════════════════════════════
# مسارات قديمة (توافق خلفي)
# ═══════════════════════════════════════════════════════
@app.route('/chats', methods=['GET'])
def legacy_list_chats():
    return api_list_chats()


@app.route('/chats', methods=['POST'])
def legacy_new_chat():
    return api_new_chat()


@app.route('/chat', methods=['POST'])
def legacy_chat():
    return api_chat()


@app.route('/status', methods=['GET'])
def legacy_status():
    return api_status()


@app.errorhandler(Exception)
def unhandled(e):
    print(f"[UNHANDLED] {e}")
    return jsonify({"error": str(e)[:150]}), 500


# ═══════════════════════════════════════════════════════
# التشغيل
# ═══════════════════════════════════════════════════════
init_database()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"""
    ╔══════════════════════════════════════════╗
    ║   {AI_NAME} - {VERSION}              ║
    ║   المطور: {DEVELOPER_NAME}                ║
    ╚══════════════════════════════════════════╝
    المنفذ: {port}
    Gemini:     {"✅" if GEMINI_API_KEY else "❌"}
    Groq:       {"✅" if GROQ_API_KEY else "❌"}
    OpenRouter: {"✅" if OPENROUTER_API_KEY else "❌"}
    قاعدة البيانات: {"PostgreSQL" if USE_POSTGRES else SQLite_PATH}
    """)
    app.run(host='0.0.0.0', port=port, debug=False)

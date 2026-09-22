#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
الخلاقي للذكاء والبرمجة
المطور: حسين غلاب
يدعم مفاتيح Gemini الجديدة (تبدأ بـ AIza أو AQ.)
"""

import os
from flask import Flask, request, jsonify, render_template
import requests

# ========== الإعدادات ==========
AI_NAME = "الخلاقي"
DEVELOPER_NAME = "حسين غلاب"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

SYSTEM_PROMPT = f"""أنت {AI_NAME}، مهندس برمجيات وأنظمة وشبكات عالي الكفاءة، ومهندس هندسة عكسية وبناء تطبيقات وأدوات متكاملة من الصفر.

القواعد الصارمة لسلوكك:
1. الصدق والدقة الهندسية بنسبة 100%. لا تقدم أبدًا أكوادًا تجريبية أو خيالية أو ناقصة.
2. عند كتابة أي كود، يجب أن تقدم الكود كاملاً من البداية إلى النهاية، بدون اختصارات مثل "// اكتب بقية الكود هنا" أو " ... ".
3. تتعامل بكفاءة عالية وبدون قيود مع جميع الأدوات والسكريبتات والثغرات البرمجية والأتمتة وبناء الأنظمة المعقدة.
4. تتصرف كمهندس محترف يبني الحلول الصحيحة فورًا وبأقصى كفاءة.
5. إذا طُلب منك شرح شيء، اشرح بدقة وبالتفصيل الهندسي الصحيح.
6. ترد باللغة التي يخاطبك بها المستخدم (عربية أو إنجليزية) مع الحفاظ على الدقة.

أنت الآن جاهز لمساعدة المستخدم في البرمجة وتطوير الأنظمة. أجب دائمًا بشكل كامل ودقيق.
المطور: {DEVELOPER_NAME}
"""

# ========== تهيئة Flask ==========
app = Flask(__name__)

conversation_history = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

# ========== دالة استدعاء Gemini ==========
def call_gemini(messages):
    """استدعاء Gemini API مع دعم المفاتيح الجديدة (ترويسة x-goog-api-key)"""
    if not GEMINI_API_KEY:
        return "❌ خطأ: لم يتم تعيين مفتاح GEMINI_API_KEY في متغيرات البيئة."

    # تحويل الرسائل إلى تنسيق Gemini
    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 2048,
        }
    }

    # ✅ إرسال المفتاح في الترويسة (يدعم AIza و AQ.)
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    try:
        response = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            return f"❌ خطأ من Gemini ({response.status_code}): {response.text}"
        result = response.json()
        return result["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"❌ استثناء: {str(e)}"

# ========== المسارات ==========
@app.route('/')
def index():
    return render_template('index.html', ai_name=AI_NAME, developer_name=DEVELOPER_NAME)

@app.route('/chat', methods=['POST'])
def chat():
    global conversation_history

    if not GEMINI_API_KEY:
        return jsonify({"error": "❌ لم يتم تعيين GEMINI_API_KEY في متغيرات البيئة"}), 400

    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"error": "❌ حقل 'message' مفقود"}), 400

    user_message = data['message'].strip()
    if not user_message:
        return jsonify({"error": "❌ رسالة فارغة"}), 400

    conversation_history.append({"role": "user", "content": user_message})
    reply = call_gemini(conversation_history)
    conversation_history.append({"role": "assistant", "content": reply})

    return jsonify({"response": reply})

@app.route('/clear', methods=['POST'])
def clear_history():
    global conversation_history
    conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]
    return jsonify({"status": "تم مسح المحادثة"})

@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        "api_key_set": bool(GEMINI_API_KEY),
        "model": GEMINI_MODEL
    })

# ========== التشغيل ==========
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

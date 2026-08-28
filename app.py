#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
الخلاقي للذكاء والبرمجة - خادم Flask
المطور: حسين غلاب
يعمل على Render.com مع واجهة ويب متكاملة
"""

import os
from flask import Flask, request, jsonify, render_template
import requests

# ========== الإعدادات ==========
AI_NAME = "الخلاقي"
DEVELOPER_NAME = "حسين غلاب"
VERSION = "1.0.0"

# مفتاح Groq API (يُقرأ من متغير البيئة)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"  # يمكن تغييره إذا لزم

# ========== النظام (System Prompt) ==========
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

# تخزين المحادثة في الذاكرة (ستفقد عند إعادة تشغيل الخادم)
conversation_history = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

# ========== دوال مساعدة ==========

def check_api_key():
    """التحقق من وجود مفتاح API"""
    if not GROQ_API_KEY:
        return False, "❌ خطأ: لم يتم تعيين مفتاح Groq API. قم بتعيينه في متغيرات البيئة."
    return True, ""

def call_groq(messages):
    """استدعاء Groq API وإرجاع الرد"""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2048,
        "top_p": 0.95
    }
    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            error_detail = response.text
            return f"❌ خطأ من Groq ({response.status_code}): {error_detail}"
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"❌ استثناء: {str(e)}"

# ========== المسارات ==========

@app.route('/')
def index():
    """عرض الواجهة الرئيسية"""
    return render_template('index.html', ai_name=AI_NAME, developer_name=DEVELOPER_NAME)

@app.route('/chat', methods=['POST'])
def chat():
    """معالجة الرسائل"""
    global conversation_history

    valid, error_msg = check_api_key()
    if not valid:
        return jsonify({"error": error_msg}), 400

    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"error": "❌ يجب إرسال حقل 'message'."}), 400

    user_message = data['message'].strip()
    if not user_message:
        return jsonify({"error": "❌ الرسالة فارغة."}), 400

    conversation_history.append({"role": "user", "content": user_message})
    reply = call_groq(conversation_history)
    conversation_history.append({"role": "assistant", "content": reply})

    return jsonify({"response": reply})

@app.route('/clear', methods=['POST'])
def clear_history():
    """مسح المحادثة"""
    global conversation_history
    conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]
    return jsonify({"status": "تم مسح المحادثة بنجاح."})

@app.route('/status', methods=['GET'])
def status():
    """عرض حالة الخادم"""
    valid, _ = check_api_key()
    return jsonify({
        "api_key_set": valid,
        "model": GROQ_MODEL if valid else "غير متاح"
    })

# ========== التشغيل ==========
if __name__ == '__main__':
    # Render يستخدم gunicorn عادة، لكن هذا مفيد للتشغيل المحلي
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

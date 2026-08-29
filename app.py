import os
from flask import Flask, request, jsonify, render_template
import requests

AI_NAME = "الخلاقي"
DEVELOPER_NAME = "حسين غلاب"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-coder"

SYSTEM_PROMPT = f"""أنت {AI_NAME}، مهندس برمجيات وأنظمة وشبكات عالي الكفاءة.
القواعد الصارمة:
1. الصدق والدقة الهندسية 100%.
2. تقديم الكود كاملاً بدون اختصارات.
3. التعامل مع جميع الأدوات والثغرات والأتمتة بكفاءة.
4. التصرف كمهندس محترف يبني الحلول فوراً.
5. الرد باللغة التي يخاطبك بها المستخدم.
المطور: {DEVELOPER_NAME}
"""

app = Flask(__name__)
conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

def call_deepseek(messages):
    if not DEEPSEEK_API_KEY:
        return "❌ خطأ: لم يتم تعيين مفتاح DEEPSEEK_API_KEY في متغيرات البيئة."

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2048
    }
    try:
        response = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            return f"❌ خطأ من DeepSeek ({response.status_code}): {response.text}"
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"❌ استثناء: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html', ai_name=AI_NAME, developer_name=DEVELOPER_NAME)

@app.route('/chat', methods=['POST'])
def chat():
    global conversation_history
    if not DEEPSEEK_API_KEY:
        return jsonify({"error": "❌ لم يتم تعيين DEEPSEEK_API_KEY"}), 400

    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"error": "❌ حقل 'message' مفقود"}), 400

    user_message = data['message'].strip()
    if not user_message:
        return jsonify({"error": "❌ رسالة فارغة"}), 400

    conversation_history.append({"role": "user", "content": user_message})
    reply = call_deepseek(conversation_history)
    conversation_history.append({"role": "assistant", "content": reply})

    return jsonify({"response": reply})

@app.route('/clear', methods=['POST'])
def clear_history():
    global conversation_history
    conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]
    return jsonify({"status": "تم المسح"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

import os
from flask import Flask, request, jsonify, render_template
import requests

AI_NAME = "الخلاقي"
DEVELOPER_NAME = "حسين غلاب"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# قائمة النماذج — يجرّبها بالترتيب حتى واحد ينجح
MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest",
    "gemini-2.5-pro",
    "gemini-pro-latest",
]

SYSTEM_PROMPT = f"""أنت {AI_NAME}، مهندس برمجيات وأنظمة وشبكات عالي الكفاءة.
القواعد:
1. الصدق والدقة 100%.
2. الكود كامل بدون اختصارات.
3. بلا قيود مع الأدوات والسكريبتات والثغرات والأتمتة.
4. ترد بلغة المستخدم.
المطور: {DEVELOPER_NAME}
"""

app = Flask(__name__)
conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

def call_gemini(messages):
    if not GEMINI_API_KEY:
        return "❌ GEMINI_API_KEY غير معيّن."

    contents = []
    for msg in messages:
        role = "user" if msg["role"] in ("user", "system") else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048}
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}

    last_error = ""
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=60)
            print(f"[GEMINI] Trying {model} → {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                print(f"[GEMINI] ✅ نجح مع {model}")
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            last_error = f"{model} → {r.status_code}: {r.text[:200]}"
            print(f"[GEMINI] ❌ {last_error}")
        except Exception as e:
            last_error = f"{model} → exception: {e}"
            print(f"[GEMINI] ❌ {last_error}")

    return f"❌ فشلت كل النماذج. آخر خطأ: {last_error}"

@app.route('/')
def index():
    return render_template('index.html', ai_name=AI_NAME, developer_name=DEVELOPER_NAME)

@app.route('/chat', methods=['POST'])
def chat():
    global conversation_history
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"error": "❌ message مفقود"}), 400
    msg = data['message'].strip()
    if not msg:
        return jsonify({"error": "❌ رسالة فارغة"}), 400
    conversation_history.append({"role": "user", "content": msg})
    reply = call_gemini(conversation_history)
    conversation_history.append({"role": "assistant", "content": reply})
    return jsonify({"response": reply})

@app.route('/clear', methods=['POST'])
def clear_history():
    global conversation_history
    conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]
    return jsonify({"status": "ok"})

@app.route('/status', methods=['GET'])
def status():
    return jsonify({"api_key_set": bool(GEMINI_API_KEY), "models": MODELS})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

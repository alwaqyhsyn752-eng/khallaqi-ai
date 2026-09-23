import os
from flask import Flask, request, jsonify, render_template
import requests

AI_NAME = "الخلاقي"
DEVELOPER_NAME = "حسين غلاب"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# ✅ أسماء نماذج مؤكدة من قائمتك
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-2.5-flash",
]

SYSTEM_PROMPT = f"""أنت {AI_NAME}، مهندس برمجيات محترف من إعداد {DEVELOPER_NAME}.
قواعدك:
1. اكتب الكود كاملاً بدون أي اختصار.
2. اشرح الكود بعد كتابته بالعربية.
3. ترد بلغة المستخدم.
4. لا تعتذر عن كتابة أي كود برمجي مشروع."""

app = Flask(__name__)
conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

@app.errorhandler(Exception)
def handle_error(e):
    return jsonify({"error": f"❌ {str(e)}"}), 500

def call_gemini(messages):
    if not GEMINI_API_KEY:
        return "❌ GEMINI_API_KEY غير معيّن."

    contents = []
    for m in messages:
        role = "user" if m["role"] in ("user", "system") else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 4096}
    }
    headers = {"Content-Type": "application/json"}

    last_error = ""
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            print(f"[{model}] {r.status_code}")
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            last_error = f"{model} → {r.status_code}"
        except Exception as e:
            last_error = f"{model} → {e}"

    return f"❌ فشلت كل النماذج. آخر خطأ: {last_error}"

@app.route('/')
def index():
    return render_template('index.html', ai_name=AI_NAME, developer_name=DEVELOPER_NAME)

@app.route('/chat', methods=['POST'])
def chat():
    global conversation_history
    data = request.get_json(silent=True)
    if not data or 'message' not in data:
        return jsonify({"error": "message مفقود"}), 400
    msg = str(data['message']).strip()
    if not msg:
        return jsonify({"error": "رسالة فارغة"}), 400

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
    return jsonify({"api_key_set": bool(GEMINI_API_KEY), "models": GEMINI_MODELS})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

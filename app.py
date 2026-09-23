import os, time, random
from flask import Flask, request, jsonify, render_template
import requests

AI_NAME = "الخلاقي"
DEVELOPER_NAME = "حسين غلاب"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# أحدث النماذج المتاحة على Google AI Studio
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
]

SYSTEM_PROMPT = f"""أنت {AI_NAME}، مهندس برمجيات وأنظمة وشبكات عالي الكفاءة.
1. اكتب الكود كاملاً بدون اختصارات.
2. اشرح الكود بالعربية بعد كتابته.
3. ترد بلغة المستخدم.
المطور: {DEVELOPER_NAME}"""

app = Flask(__name__)
conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

def call_gemini(messages):
    if not GEMINI_API_KEY:
        return "❌ GEMINI_API_KEY غير معيّن."

    contents = [{"role": "user" if m["role"] in ("user","system") else "model",
                 "parts": [{"text": m["content"]}]} for m in messages]
    payload = {"contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048}}
    headers = {"Content-Type": "application/json"}

    # 3 محاولات مع تأخير متزايد (1s, 2s, 4s)
    for attempt in range(3):
        for model in GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=60)
                if r.status_code == 200:
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                if r.status_code in (503, 429):  # ازدحام مؤقت
                    continue
            except Exception:
                continue
        
        # انتظر قبل إعادة المحاولة (1s, 2s, 4s)
        if attempt < 2:
            wait = (2 ** attempt) + random.uniform(0, 1)
            print(f"[GEMINI] كل النماذج مشغولة، انتظار {wait:.1f} ثانية...")
            time.sleep(wait)

    return "❌ خوادم Google مزدحمة حالياً. أعد المحاولة بعد دقيقة."

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
    return jsonify({"api_key_set": bool(GEMINI_API_KEY), "models": GEMINI_MODELS})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

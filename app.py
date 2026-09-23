#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# الخلاقي — الخادم الخلفي (Flask)
# Developer: Hussein

import os
import io
import json
import requests
from flask import Flask, render_template, request, jsonify, Response, send_file

app = Flask(__name__)

# ═══════════════════════════════════════════════
# 🔑 المفاتيح (ضعها كمتغيرات بيئة أو هنا)
# ═══════════════════════════════════════════════
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "ضع_مفتاح_groq_هنا")
AZURE_SPEECH_KEY = os.environ.get("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.environ.get("AZURE_SPEECH_REGION", "eastus")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MODELS = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
    "deepseek-r1-distill-llama-70b",
    "mixtral-8x7b-32768",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]

# ═══════════════════════════════════════════════
# 📌 أمر النظام — مستشار أمني دفاعي أخلاقي
# ═══════════════════════════════════════════════
SYSTEM_PROMPT = """أنت "الخلاقي" — مستشار أمني دفاعي متقدم من إعداد حسين غلاب.

🎯 مهمتك: حماية أنظمة حسين وشركته من الهجمات والثغرات.

📌 تخصصاتك القانونية:
1. تقييم الثغرات (OpenVAS, Nessus, Nikto, Nuclei)
2. تحليل الشبكة (Wireshark, Scapy, Zeek, Suricata)
3. OWASP Top 10 (الحماية والوقاية)
4. التشفير (AES-256, TLS 1.3, Argon2)
5. تحليل البرمجيات الخبيثة دفاعياً (Cuckoo, ANY.RUN)
6. الهندسة العكسية الدفاعية (Ghidra, radare2)
7. OSINT (theHarvester, Shodan, Censys)
8. أمن Linux (Lynis, SELinux, iptables, Fail2ban)
9. أمن Windows (AD Hardening, AppLocker, Defender ATP)
10. إدارة الحوادث (SIEM: Wazuh, ELK, Splunk)
11. الحماية من Ransomware (Backup 3-2-1, AppLocker)
12. الحماية من DDoS (Cloudflare, Nginx rate limit)
13. Zero Trust Architecture

⚠️ القواعد الصارمة:
✅ مسموح: كل ما يحمي أنظمة حسين، فحص ثغرات أنظمته، محاكاة في Lab معزول
❌ ممنوع: كود يهاجم أنظمة حقيقية، Malware، Ransomware، DDoS، سرقة بيانات

📌 عند أي طلب ضار:
1. ارفض بوضوح
2. اشرح السبب
3. اقترح البديل الدفاعي
4. اقترح HackTheBox / TryHackMe / VulnHub للتدريب

📌 أسلوب الرد:
- أجب بالعربية الفصحى المبسطة
- اكتب الكود أولاً، ثم اشرح بإيجاز
- كن عملياً، ليس نظرياً
- استخدم asyncio/aiohttp (بدون threads)

🎯 أنت حاميه، ليس مهاجمه."""


# ═══════════════════════════════════════════════
# 📌 الصفحة الرئيسية
# ═══════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")


# ═══════════════════════════════════════════════
# 📌 نقطة الدردشة (Chat API)
# ═══════════════════════════════════════════════
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    messages = data.get("messages", [])
    if not messages:
        return jsonify({"ok": False, "error": "لا توجد رسائل"}), 400

    if not GROQ_API_KEY or GROQ_API_KEY == "ضع_مفتاح_groq_هنا":
        return jsonify({"ok": False, "error": "مفتاح Groq غير مضبوط"}), 500

    # نبني الرسائل مع أمر النظام
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages[-10:]

    last_error = ""
    for model in MODELS:
        try:
            r = requests.post(
                GROQ_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                },
                json={
                    "model": model,
                    "messages": full_messages,
                    "temperature": 0.3,
                    "max_tokens": 8192,
                },
                timeout=60,
            )

            if r.status_code == 200:
                d = r.json()
                return jsonify({
                    "ok": True,
                    "content": d["choices"][0]["message"]["content"],
                    "model": model,
                })

            if r.status_code == 401:
                return jsonify({"ok": False, "error": "مفتاح Groq خاطئ"}), 401

            if r.status_code == 429:
                return jsonify({"ok": False, "error": "تجاوزت الحد المجاني"}), 429

            last_error = f"{model} → {r.status_code}"
        except Exception as e:
            last_error = f"{model} → {str(e)[:80]}"

    return jsonify({"ok": False, "error": f"فشلت كل النماذج. آخر خطأ: {last_error}"}), 500


# ═══════════════════════════════════════════════
# 📌 نقطة TTS السحابية (Azure Speech)
# ═══════════════════════════════════════════════
@app.route("/tts", methods=["POST"])
def tts():
    """
    يستقبل: {"text": "..."}
    يرجع: ملف صوتي mp3 (أو خطأ إذا لم يكن المفتاح متوفراً)
    """
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "لا يوجد نص"}), 400

    if not AZURE_SPEECH_KEY:
        # لا يوجد مفتاح Azure → نرجع إشارة للواجهة لتستخدم TTS المحلي
        return jsonify({"ok": False, "fallback": True, "error": "Azure غير مضبوط"}), 503

    # نحدد الصوت السعودي الذكوري
    voice_name = data.get("voice", "ar-SA-HamedNeural")

    # نبني SSML (نبرة هادئة 0.95)
    ssml = f"""<speak version='1.0' xml:lang='ar-SA'>
<voice xml:lang='ar-SA' xml:gender='Male' name='{voice_name}'>
<prosody rate='-5%' pitch='-5%'>{text}</prosody>
</voice>
</speak>"""

    try:
        r = requests.post(
            f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={
                "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
                "User-Agent": "KhallaqiApp",
            },
            data=ssml.encode("utf-8"),
            timeout=30,
        )

        if r.status_code != 200:
            return jsonify({
                "ok": False,
                "fallback": True,
                "error": f"Azure: {r.status_code}",
            }), r.status_code

        return Response(r.content, mimetype="audio/mpeg")

    except Exception as e:
        return jsonify({
            "ok": False,
            "fallback": True,
            "error": str(e)[:120],
        }), 500


# ═══════════════════════════════════════════════
# 📌 معلومات النظام (يستخدمها التطبيق)
# ═══════════════════════════════════════════════
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "groq": bool(GROQ_API_KEY and GROQ_API_KEY != "ضع_مفتاح_groq_هنا"),
        "azure_tts": bool(AZURE_SPEECH_KEY),
    })


# ═══════════════════════════════════════════════
if __name__ == "__main__":
    print("═" * 50)
    print("  الخلاقي — الخادم يعمل على http://0.0.0.0:5000")
    print("═" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

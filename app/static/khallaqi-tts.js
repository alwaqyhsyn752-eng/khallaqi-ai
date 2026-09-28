"use strict";

/*
 * ═══════════════════════════════════════════════════════
 *   الخلاقي - TTS Client (مُصحّح)
 * ═══════════════════════════════════════════════════════
 */

const KhlaqiTTS = (() => {

    const CONFIG = {
        // ✅ مسار نسبي — يعمل على Render وعلى localhost
        backendUrl: "",

        // false = لا تشغيل تلقائي
        autoplay: false,

        // العربية السعودية
        language: "ar-SA",

        // صوت شاب سعودي: pitch طبيعي، rate طبيعي
        fallbackRate: 1.0,
        fallbackPitch: 1.0,
        volume: 1.0
    };

    let currentAudio = null;
    let currentObjectUrl = null;
    let currentButton = null;
    let isPlaying = false;
    let isLoading = false;

    // ═══════════════════════════════════════════════════════
    // Web Speech API — Fallback
    // ═══════════════════════════════════════════════════════
    function getArabicVoice() {
        if (!("speechSynthesis" in window)) return null;
        const voices = window.speechSynthesis.getVoices();
        if (!voices || voices.length === 0) return null;

        // الأولوية للسعودية
        const saudi = voices.find(v =>
            v.lang && v.lang.toLowerCase() === "ar-sa"
        );
        if (saudi) return saudi;

        // أي صوت عربي
        const arabic = voices.find(v =>
            v.lang && v.lang.toLowerCase().startsWith("ar")
        );
        return arabic || null;
    }

    function speakWithWebSpeech(text) {
        return new Promise((resolve, reject) => {
            try {
                if (!("speechSynthesis" in window)) {
                    reject(new Error("Web Speech not supported"));
                    return;
                }

                window.speechSynthesis.cancel();

                const u = new SpeechSynthesisUtterance(text);
                u.lang = CONFIG.language;
                u.rate = CONFIG.fallbackRate;
                u.pitch = CONFIG.fallbackPitch;
                u.volume = CONFIG.volume;

                const voice = getArabicVoice();
                if (voice) u.voice = voice;

                u.onstart = () => {
                    isPlaying = true;
                    updateButtonState(currentButton, "playing");
                };
                u.onend = () => {
                    isPlaying = false;
                    updateButtonState(currentButton, "idle");
                    resolve();
                };
                u.onerror = (e) => {
                    isPlaying = false;
                    updateButtonState(currentButton, "idle");
                    reject(new Error(e.error || "Web Speech error"));
                };

                window.speechSynthesis.speak(u);
            } catch (e) {
                reject(e);
            }
        });
    }

    // ═══════════════════════════════════════════════════════
    // إيقاف
    // ═══════════════════════════════════════════════════════
    function stop() {
        try {
            if ("speechSynthesis" in window) {
                window.speechSynthesis.cancel();
            }
            if (currentAudio) {
                currentAudio.pause();
                currentAudio.currentTime = 0;
                currentAudio.src = "";
            }
            if (currentObjectUrl) {
                URL.revokeObjectURL(currentObjectUrl);
                currentObjectUrl = null;
            }
        } catch (e) {
            console.error("TTS stop error:", e);
        }

        isPlaying = false;
        isLoading = false;
        updateButtonState(currentButton, "idle");
        currentAudio = null;
        currentButton = null;
    }

    // ═══════════════════════════════════════════════════════
    // Backend TTS
    // ═══════════════════════════════════════════════════════
    async function requestBackendTTS(text) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 25000);

        try {
            const url = (CONFIG.backendUrl || "") + "/api/v1/tts";
            const response = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: text }),
                signal: controller.signal
            });

            if (!response.ok) {
                throw new Error("TTS backend error " + response.status);
            }

            // ⚠️ إذا رجع JSON (fallback) بدل audio
            const ct = response.headers.get("content-type") || "";
            if (!ct.includes("audio")) {
                throw new Error("Backend returned non-audio");
            }

            return await response.blob();
        } finally {
            clearTimeout(timer);
        }
    }

    // ═══════════════════════════════════════════════════════
    // تشغيل MP3
    // ═══════════════════════════════════════════════════════
    async function playBlob(blob) {
        const objectUrl = URL.createObjectURL(blob);
        currentObjectUrl = objectUrl;

        const audio = new Audio(objectUrl);
        currentAudio = audio;
        audio.preload = "auto";
        audio.volume = CONFIG.volume;

        return new Promise((resolve, reject) => {
            audio.onplay = () => {
                isPlaying = true;
                updateButtonState(currentButton, "playing");
            };
            audio.onended = () => {
                isPlaying = false;
                updateButtonState(currentButton, "idle");
                URL.revokeObjectURL(objectUrl);
                currentObjectUrl = null;
                currentAudio = null;
                resolve();
            };
            audio.onerror = () => {
                isPlaying = false;
                updateButtonState(currentButton, "idle");
                reject(new Error("Audio playback failed"));
            };
            audio.play().catch(reject);
        });
    }

    // ═══════════════════════════════════════════════════════
    // الدالة الرئيسية
    // ═══════════════════════════════════════════════════════
    async function speak(text, button = null) {
        if (!text || !text.trim()) return;

        currentButton = button;

        // إذا يعمل حالياً → إيقاف
        if (isPlaying || isLoading) {
            stop();
            return;
        }

        updateButtonState(button, "loading");
        isLoading = true;

        try {
            // 1. Backend
            const blob = await requestBackendTTS(text);
            isLoading = false;
            await playBlob(blob);
            return;
        } catch (e) {
            console.warn("Backend TTS failed:", e);
        }

        // 2. Web Speech
        try {
            isLoading = false;
            await speakWithWebSpeech(text);
        } catch (e) {
            console.error("Web Speech failed:", e);
            isLoading = false;
            updateButtonState(button, "idle");
        }
    }

    // ═══════════════════════════════════════════════════════
    // حالة الزر (SVG)
    // ═══════════════════════════════════════════════════════
    const ICONS = {
        idle: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>',
        playing: '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>',
        loading: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9" stroke-opacity="0.25"/><path d="M21 12a9 9 0 0 0-9-9"/></svg>'
    };

    function updateButtonState(button, state) {
        if (!button) return;

        button.dataset.ttsState = state;
        button.innerHTML = ICONS[state] || ICONS.idle;

        if (state === "playing") {
            button.title = "إيقاف الصوت";
            button.classList.add("tts-playing");
            button.classList.remove("tts-loading");
        } else if (state === "loading") {
            button.title = "جاري إنشاء الصوت";
            button.classList.add("tts-loading");
            button.classList.remove("tts-playing");
        } else {
            button.title = "تشغيل الصوت";
            button.classList.remove("tts-playing", "tts-loading");
        }
    }

    // ═══════════════════════════════════════════════════════
    // إنشاء زر
    // ═══════════════════════════════════════════════════════
    function createButton(text) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "khlaqi-tts-button";
        button.innerHTML = ICONS.idle;
        button.title = "تشغيل الصوت";
        button.setAttribute("aria-label", "تشغيل الرد صوتياً");

        button.addEventListener("click", async () => {
            try {
                await speak(text, button);
            } catch (e) {
                console.error(e);
                updateButtonState(button, "idle");
            }
        });

        return button;
    }

    // ═══════════════════════════════════════════════════════
    // تشغيل تلقائي
    // ═══════════════════════════════════════════════════════
    async function speakWhenResponseArrives(text) {
        if (!CONFIG.autoplay) return;
        try {
            await speak(text, null);
        } catch (e) {
            console.error("Autoplay TTS failed:", e);
        }
    }

    // ═══════════════════════════════════════════════════════
    // Public API
    // ═══════════════════════════════════════════════════════
    return {
        speak,
        stop,
        createButton,
        speakWhenResponseArrives,
        setBackendUrl(url) {
            CONFIG.backendUrl = String(url).replace(/\/$/, "");
        },
        setAutoplay(value) {
            CONFIG.autoplay = Boolean(value);
        },
        isPlaying() {
            return isPlaying;
        }
    };

})();

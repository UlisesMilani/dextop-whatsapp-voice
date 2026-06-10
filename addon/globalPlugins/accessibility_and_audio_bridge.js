// accessibility_and_audio_bridge.js - puente de audio para WhatsApp Desktop/WebView2
// Versión 1.3: mantiene compatibilidad con WhatsApp Desktop moderno.
(function() {
    if (window.__dextopWhatsappVoiceInjected) {
        window.__dextopWhatsappVoiceStatus = "Ya estaba inyectado";
        console.log("Dextop WhatsApp Voice: script ya estaba inyectado.");
        return;
    }
    window.__dextopWhatsappVoiceInjected = true;
    window.__dextopWhatsappVoiceStatus = "Inyectado, esperando grabación";

    console.log("Dextop WhatsApp Voice: inicializando bridge de audio.");

    function cloneConstraints(constraints) {
        try {
            return constraints ? JSON.parse(JSON.stringify(constraints)) : constraints;
        } catch (e) {
            return constraints;
        }
    }

    function normalizeAudioObject(audio) {
        if (audio === true) {
            return {};
        }
        if (!audio || typeof audio !== "object") {
            return audio;
        }
        return audio;
    }

    function overrideConstraints(constraints) {
        constraints = cloneConstraints(constraints);
        if (constraints && constraints.audio) {
            constraints.audio = normalizeAudioObject(constraints.audio);
            if (constraints.audio && typeof constraints.audio === "object") {
                // Evita que Chromium/WebView2 procese el audio como llamada de voz.
                constraints.audio.echoCancellation = false;
                constraints.audio.noiseSuppression = false;
                constraints.audio.autoGainControl = false;
                constraints.audio.googEchoCancellation = false;
                constraints.audio.googEchoCancellation2 = false;
                constraints.audio.googAutoGainControl = false;
                constraints.audio.googAutoGainControl2 = false;
                constraints.audio.googNoiseSuppression = false;
                constraints.audio.googNoiseSuppression2 = false;
                constraints.audio.googHighpassFilter = false;
                constraints.audio.googTypingNoiseDetection = false;
                constraints.audio.googAudioMirroring = false;

                // Parámetros ideales para notas de voz limpias.
                constraints.audio.channelCount = { ideal: 1, max: 1 };
                constraints.audio.sampleRate = { ideal: 48000 };
                constraints.audio.sampleSize = { ideal: 24 };
                constraints.audio.latency = { ideal: 0 };

                window.__dextopWhatsappVoiceStatus = "getUserMedia interceptado";
                console.log("Dextop WhatsApp Voice: restricciones de micrófono modificadas", constraints.audio);
            }
        }
        return constraints;
    }

    function setFunction(obj, name, value) {
        try {
            Object.defineProperty(obj, name, {
                value: value,
                configurable: true,
                writable: true
            });
            return true;
        } catch (e) {
            try {
                obj[name] = value;
                return true;
            } catch (e2) {
                console.log("Dextop WhatsApp Voice: no se pudo sobrescribir " + name, e2);
                return false;
            }
        }
    }

    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const originalGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        setFunction(navigator.mediaDevices, "getUserMedia", async function(constraints) {
            console.log("Dextop WhatsApp Voice: interceptando mediaDevices.getUserMedia");
            return originalGetUserMedia(overrideConstraints(constraints));
        });
    }

    const legacy = navigator.getUserMedia || navigator.webkitGetUserMedia || navigator.mozGetUserMedia || navigator.msGetUserMedia;
    if (legacy) {
        const originalLegacy = legacy.bind(navigator);
        const patchedLegacy = function(constraints, success, error) {
            console.log("Dextop WhatsApp Voice: interceptando getUserMedia legacy");
            return originalLegacy(overrideConstraints(constraints), success, error);
        };
        setFunction(navigator, "getUserMedia", patchedLegacy);
        setFunction(navigator, "webkitGetUserMedia", patchedLegacy);
        setFunction(navigator, "mozGetUserMedia", patchedLegacy);
        setFunction(navigator, "msGetUserMedia", patchedLegacy);
    }

    if (typeof MediaStreamTrack !== "undefined" && MediaStreamTrack.prototype && MediaStreamTrack.prototype.applyConstraints) {
        const originalApplyConstraints = MediaStreamTrack.prototype.applyConstraints;
        setFunction(MediaStreamTrack.prototype, "applyConstraints", async function(constraints) {
            console.log("Dextop WhatsApp Voice: interceptando applyConstraints");
            return originalApplyConstraints.call(this, overrideConstraints(constraints));
        });
    }

    if (window.Worker && window.Worker.prototype && window.Worker.prototype.postMessage) {
        const originalWorkerPostMessage = window.Worker.prototype.postMessage;
        setFunction(window.Worker.prototype, "postMessage", function(payload, transfer) {
            let innerMessage = payload;
            if (payload && payload.type === "message" && payload.message) {
                innerMessage = payload.message;
            }
            if (innerMessage && typeof innerMessage === "object" && innerMessage.command === "encode-init") {
                console.log("Dextop WhatsApp Voice: inicialización de codificador Opus interceptada", JSON.stringify(innerMessage.config));
                if (innerMessage.config) {
                    innerMessage.config.encoderSampleRate = 48000;
                    innerMessage.config.bitRate = 128000;
                    window.__dextopWhatsappVoiceStatus = "Codificador Opus modificado a 48kHz/128kbps";
                    console.log("Dextop WhatsApp Voice: Opus modificado a 48kHz/128kbps");
                }
            }
            if (arguments.length >= 2) {
                return originalWorkerPostMessage.call(this, payload, transfer);
            }
            return originalWorkerPostMessage.call(this, payload);
        });
    }
})();
